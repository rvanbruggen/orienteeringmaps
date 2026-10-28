"""Splitting a PDF that holds several maps into one file per map.

The file keeps the first part (so its map, map picture and import stay as they are); every
other part becomes a new file in the inbox, to be filed with a map of its own. Pages keep
their images, placements, submap and result card marks, and courses follow their page.
"""
import shutil
import tempfile
from pathlib import Path

import fitz
import imagehash
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, processing
from . import models as m
from .suggest import suggest


class SplitError(ValueError):
    pass


def _check(f: m.File, parts: list[list[int]]) -> list[list[int]]:
    if f.format != "pdf" or len(f.pages) < 2:
        raise SplitError("Only a PDF with several pages can be split")
    parts = [sorted(set(p)) for p in parts if p]
    if len(parts) < 2:
        raise SplitError("Split into at least two parts")
    seen = sorted(n for p in parts for n in p)
    if seen != [p.page_no for p in f.pages]:
        raise SplitError("Every page must be in exactly one part")
    return sorted(parts)


def _name(f: m.File, pages: list[int]) -> str:
    stem = Path(f.original_name).stem
    if pages == list(range(pages[0], pages[-1] + 1)):
        nos = f"p{pages[0]}" if len(pages) == 1 else f"p{pages[0]}-{pages[-1]}"
    else:
        nos = "p" + ",".join(map(str, pages))
    return f"{stem} ({nos}).pdf"


def _write_part(f: m.File, pages: list[int]) -> Path:
    """A temporary PDF with just these pages of f."""
    with tempfile.NamedTemporaryFile(dir=config.DATA_DIR, delete=False, suffix=".pdf") as tmp:
        tmp_path = Path(tmp.name)
    with fitz.open(processing.original_path(f.stored_name)) as doc:
        doc.select([n - 1 for n in pages])
        doc.save(tmp_path, garbage=3, deflate=True)
    return tmp_path


def _copy_images(page: m.Page, digest: str, page_no: int) -> None:
    base = f"{digest[:2]}/{digest}"
    image_name, thumb_name = f"{base}/p{page_no}.webp", f"{base}/p{page_no}.thumb.webp"
    processing.derived_path(image_name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(processing.derived_path(page.image_name), processing.derived_path(image_name))
    shutil.copyfile(processing.derived_path(page.thumb_name), processing.derived_path(thumb_name))
    page.image_name, page.thumb_name = image_name, thumb_name


def _phash(page: m.Page) -> str | None:
    try:
        with Image.open(processing.derived_path(page.image_name)) as img:
            return str(imagehash.phash(img))
    except Exception:
        return None


def split_file(db: Session, f: m.File, parts: list[list[int]]) -> list[m.File]:
    """Split f into the given parts (lists of 1-based page numbers). Returns the files, f first."""
    parts = _check(f, parts)
    by_no = {p.page_no: p for p in f.pages}
    courses = db.scalars(select(m.Course).where(m.Course.file_id == f.id)).all()
    old_stored, old_digest = f.stored_name, f.sha256

    # Write every part first, and only store them once none is already in the library.
    tmps, seen = [], set()
    try:
        for pages in parts:
            tmps.append(_write_part(f, pages))
            digest = processing.sha256_of(tmps[-1])
            if digest in seen or db.scalars(select(m.File).where(m.File.sha256 == digest)).first():
                raise SplitError(f"Pages {', '.join(map(str, pages))} are already in the library as a file of their own")
            seen.add(digest)
        written = [processing.store_original(tmp, "part.pdf") for tmp in tmps]
    finally:
        for tmp in tmps:
            tmp.unlink(missing_ok=True)

    keep_sid = {k: v for k, v in (f.suggestions or {}).items() if k == "strava_activity_id"}
    names = [_name(f, pages) for pages in parts]
    targets = [f] + [m.File(kind=f.kind, format="pdf", source=f.source, source_id=f.source_id, notes=f.notes,
                            exif_lat=f.exif_lat, exif_lon=f.exif_lon, map_version_id=None) for _ in parts[1:]]
    # Courses follow their page: old page number -> (file, new page number).
    moves = {n: (targets[i], k) for i, pages in enumerate(parts) for k, n in enumerate(pages, start=1)}
    for c in courses:
        c.file, c.page_no = moves[c.page_no or 1] if (c.page_no or 1) in moves else (f, c.page_no)

    files = []
    for i, (pages, (digest, _fmt, stored_name, size)) in enumerate(zip(parts, written)):
        target = targets[i]
        moved = [by_no[n] for n in pages]
        for new_no, page in enumerate(moved, start=1):
            _copy_images(page, digest, new_no)
            page.page_no = new_no
        if i:
            f.pages = [p for p in f.pages if p not in moved]
        target.pages = moved
        target.original_name = names[i]
        target.stored_name, target.sha256, target.size_bytes, target.page_count = stored_name, digest, size, len(pages)
        texts = [p.text for p in moved if p.text]
        target.extracted_text = "\n".join(texts)[:200_000] or None
        target.text_source = f.text_source if target.extracted_text else None
        target.phash = _phash(moved[0])
        target.suggestions = suggest(target.original_name, target.extracted_text, len(pages)) | keep_sid
        files.append(target)
    for extra in files[1:]:
        db.add(extra)
    db.commit()
    processing.delete_original(old_stored)
    processing.delete_derived(old_digest)
    return files
