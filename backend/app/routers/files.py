"""Uploading, listing and managing source files (PDFs and images)."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from .. import processing
from .. import schemas as s
from .. import services
from ..db import get_session
from ..ingest import ingest_stream, similar_files
from ..suggest import suggest

router = APIRouter(prefix="/api/files", tags=["files"])

MEDIA_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "tif": "image/tiff",
               "webp": "image/webp", "heic": "image/heic", "gif": "image/gif", "bmp": "image/bmp"}


@router.post("", response_model=list[s.UploadResult])
def upload(files: list[UploadFile], db: Session = Depends(get_session)):
    return [ingest_stream(db, uf.file, uf.filename or "upload") for uf in files]


@router.get("", response_model=list[s.FileOut])
def list_files(unassigned: bool = False, db: Session = Depends(get_session)):
    q = select(m.File).options(selectinload(m.File.pages), selectinload(m.File.version)).order_by(m.File.id.desc())
    if unassigned:
        q = q.where(m.File.map_version_id.is_(None))
    return [services.file_out(f) for f in db.scalars(q)]


@router.get("/{file_id}", response_model=s.UploadResult)
def get_file(file_id: int, db: Session = Depends(get_session)):
    """A file with its similar files and candidate maps (same shape as an upload result)."""
    f = services.get_or_404(db, m.File, file_id)
    return s.UploadResult(original_name=f.original_name, status="existing", file=services.file_out(f),
                          similar=similar_files(db, f),
                          candidate_maps=services.candidate_maps(db, (f.suggestions or {}).get("name")))


@router.get("/{file_id}/text")
def get_text(file_id: int, db: Session = Depends(get_session)):
    f = services.get_or_404(db, m.File, file_id)
    return {"text_source": f.text_source, "text": f.extracted_text or ""}


@router.patch("/{file_id}", response_model=s.FileOut)
def update_file(file_id: int, data: s.FileUpdate, db: Session = Depends(get_session)):
    f = services.get_or_404(db, m.File, file_id)
    vals = data.model_dump(exclude_unset=True)
    if vals.get("map_version_id") is not None:
        services.get_or_404(db, m.MapVersion, vals["map_version_id"])
    if "kind" in vals and vals["kind"] not in s.FILE_KINDS:
        raise HTTPException(422, f"kind must be one of {s.FILE_KINDS}")
    for k, v in vals.items():
        setattr(f, k, v if k != "kind" else (v or "map"))
    db.commit()
    db.refresh(f)
    return services.file_out(f)


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: int, db: Session = Depends(get_session)):
    """Permanently delete a file: the stored original, its renders and its database row."""
    f = services.get_or_404(db, m.File, file_id)
    stored, digest = f.stored_name, f.sha256
    db.delete(f)
    db.commit()
    processing.delete_original(stored)
    processing.delete_derived(digest)


@router.get("/{file_id}/original")
def download_original(file_id: int, db: Session = Depends(get_session)):
    f = services.get_or_404(db, m.File, file_id)
    path = processing.original_path(f.stored_name)
    if not path.exists():
        raise HTTPException(404, "Original file missing on disk")
    return FileResponse(path, media_type=MEDIA_TYPES.get(f.format, "application/octet-stream"),
                        filename=f.original_name, content_disposition_type="inline")


@router.post("/{file_id}/reprocess", response_model=s.FileOut)
def reprocess(file_id: int, db: Session = Depends(get_session)):
    """Re-render pages and re-extract text, e.g. after changing render settings."""
    f = services.get_or_404(db, m.File, file_id)
    processing.delete_derived(f.sha256)
    pf = processing.render_pages(f.stored_name, f.format, f.sha256)
    f.pages = [m.Page(page_no=p.page_no, width=p.width, height=p.height, image_name=p.image_name,
                      thumb_name=p.thumb_name, text=p.text) for p in pf.pages]
    f.page_count, f.phash = pf.page_count, pf.phash
    f.extracted_text, f.text_source = pf.text, pf.text_source
    f.exif_lat, f.exif_lon = pf.exif_lat, pf.exif_lon
    f.suggestions = suggest(f.original_name, pf.text, pf.page_count)
    db.commit()
    db.refresh(f)
    return services.file_out(f)
