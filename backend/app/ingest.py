"""Adding files to the library: shared by the upload API and the bulk import CLI."""
import logging
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, processing, services
from . import models as m
from . import schemas as s
from .suggest import suggest

log = logging.getLogger(__name__)

SIMILAR_MAX_DISTANCE = 8  # phash Hamming distance; 0 = identical image


def similar_files(db: Session, f: m.File) -> list[s.SimilarFile]:
    out = []
    for other in db.scalars(select(m.File).where(m.File.id != f.id, m.File.phash.is_not(None))):
        d = processing.phash_distance(f.phash, other.phash)
        if d is not None and d <= SIMILAR_MAX_DISTANCE:
            v = other.version
            out.append(s.SimilarFile(file_id=other.id, original_name=other.original_name, distance=d,
                                     map_id=v.map_id if v else None, map_name=v.map.name if v else None))
    return sorted(out, key=lambda x: x.distance)


def ingest_stream(db: Session, stream: BinaryIO, original_name: str) -> s.UploadResult:
    config.ensure_dirs()
    with tempfile.NamedTemporaryFile(dir=config.DATA_DIR, delete=False, suffix=".upload") as tmp:
        shutil.copyfileobj(stream, tmp)
        tmp_path = Path(tmp.name)
    try:
        return ingest_path(db, tmp_path, original_name, move=True)
    finally:
        tmp_path.unlink(missing_ok=True)


def ingest_path(db: Session, path: Path, original_name: str, *, move: bool = False) -> s.UploadResult:
    """Store, render and analyse one file. With move=False the source is copied."""
    name = Path(original_name).name
    try:
        if not move:
            with tempfile.NamedTemporaryFile(dir=config.DATA_DIR, delete=False, suffix=".upload") as tmp:
                with path.open("rb") as src:
                    shutil.copyfileobj(src, tmp)
                path = Path(tmp.name)
        try:
            with path.open("rb") as fh:
                processing.detect_format(name, fh.read(8))
            digest = processing.sha256_of(path)
            existing = db.scalars(select(m.File).where(m.File.sha256 == digest)).first()
            if existing:
                return s.UploadResult(original_name=name, status="duplicate",
                                      file=services.file_out(existing, with_pages=False))
            digest, fmt, stored_name, size = processing.store_original(path, name)
        finally:
            if not move:
                path.unlink(missing_ok=True)

        try:
            pf = processing.render_pages(stored_name, fmt, digest)
        except Exception:
            processing.delete_original(stored_name)
            processing.delete_derived(digest)
            raise
        sugg = suggest(name, pf.text, pf.page_count)
        f = m.File(
            kind=sugg.get("kind", "map"), original_name=name, stored_name=stored_name, format=fmt,
            size_bytes=size, sha256=digest, phash=pf.phash, page_count=pf.page_count,
            extracted_text=pf.text, text_source=pf.text_source, exif_lat=pf.exif_lat,
            exif_lon=pf.exif_lon, suggestions=sugg,
            pages=[m.Page(page_no=p.page_no, width=p.width, height=p.height, image_name=p.image_name,
                          thumb_name=p.thumb_name, text=p.text, dpi=p.dpi) for p in pf.pages],
        )
        db.add(f)
        db.commit()
        db.refresh(f)
        return s.UploadResult(
            original_name=name, status="created", file=services.file_out(f),
            similar=similar_files(db, f), candidate_maps=services.candidate_maps(db, sugg.get("name")),
        )
    except processing.UnsupportedFile as exc:
        return s.UploadResult(original_name=name, status="error", error=str(exc))
    except Exception as exc:
        db.rollback()
        log.exception("Failed to ingest %s", name)
        return s.UploadResult(original_name=name, status="error", error=f"{type(exc).__name__}: {exc}")
