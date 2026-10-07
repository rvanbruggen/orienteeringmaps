"""Placing page images on the world map (georeferencing)."""
import pymupdf
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import georef as g
from .. import models as m
from .. import processing, runs
from .. import schemas as s
from .. import services
from ..db import get_session

router = APIRouter(prefix="/api", tags=["georef"])


def _ensure_dpi(db: Session, page: m.Page) -> None:
    """Pages rendered before v0.2.0 have no DPI stored; work it out from the PDF page size."""
    if page.dpi is not None or page.file.format != "pdf":
        return
    try:
        with pymupdf.open(processing.original_path(page.file.stored_name)) as doc:
            width_pt = doc[page.page_no - 1].rect.width
        page.dpi = round(page.width / (width_pt / 72), 3)
        db.commit()
    except Exception:
        pass


def _georef_out(geo: m.Georeference | None) -> s.GeorefOut | None:
    if geo is None:
        return None
    return s.GeorefOut(requested_method=geo.requested_method, method=geo.method, points=geo.points, clip=geo.clip,
                       corners=geo.corners, rms_m=geo.rms_m, scale=geo.scale, rotation_deg=geo.rotation_deg,
                       metres_per_px=geo.metres_per_px, updated_at=geo.updated_at)


def _context(db: Session, page: m.Page) -> s.GeorefContext:
    f = page.file
    version = f.version
    mp = version.map if version else None
    stated = None
    if version:
        stated = version.scale
        course = db.scalars(select(m.Course).where(m.Course.file_id == f.id)).first()
        if course and course.scale:
            stated = course.scale  # the course print scale is what is on this paper
    others = []
    if mp:
        for v in mp.versions:
            for of in v.files:
                for op in of.pages:
                    if op.georef and op.id != page.id:
                        others.append({"page_id": op.id, "file_name": of.original_name, "page_no": op.page_no,
                                       "image_url": services.derived_url(op.image_name), "width": op.width,
                                       "height": op.height, "corners": op.georef.corners, "clip": op.georef.clip})
    my_runs = runs.map_runs(mp) if mp else []
    sid = (f.suggestions or {}).get("strava_activity_id")
    if sid and all(r["activity_id"] != sid for r in my_runs) and (a := db.get(m.StravaActivity, sid)):
        my_runs.insert(0, {"activity_id": a.id, "date": (a.start_local or "")[:10] or None, "event_name": a.name,
                           "course_name": None, "result_time_s": None})
    return s.GeorefContext(
        page=services.page_out(page), file_id=f.id, file_name=f.original_name, file_format=f.format,
        page_count=f.page_count, map_id=mp.id if mp else None, map_name=mp.name if mp else None,
        map_lat=mp.lat if mp else None, map_lon=mp.lon if mp else None, map_location=mp.location if mp else None,
        stated_scale=stated, exif_lat=f.exif_lat, exif_lon=f.exif_lon,
        same_layout_pages=[services.page_out(p) for p in f.pages
                           if p.id != page.id and (p.width, p.height) == (page.width, page.height)],
        other_placed=others[:20], georef=_georef_out(page.georef), runs=my_runs,
    )


def _load_page(db: Session, page_id: int) -> m.Page:
    page = db.scalars(select(m.Page).where(m.Page.id == page_id).options(
        selectinload(m.Page.georef), selectinload(m.Page.file).selectinload(m.File.pages))).first()
    if page is None:
        raise HTTPException(404, f"Page {page_id} not found")
    return page


@router.get("/pages/{page_id}/georef", response_model=s.GeorefContext)
def get_georef(page_id: int, db: Session = Depends(get_session)):
    page = _load_page(db, page_id)
    _ensure_dpi(db, page)
    return _context(db, page)


@router.post("/georef/fit")
def fit_points(req: s.FitRequest):
    """Stateless fit for live feedback while placing points."""
    try:
        return g.fit([p.model_dump() for p in req.points], req.width, req.height, req.method, req.dpi).as_dict()
    except g.FitError as exc:
        raise HTTPException(422, str(exc))


@router.put("/pages/{page_id}/georef", response_model=s.GeorefContext)
def save_georef(page_id: int, data: s.GeorefSave, db: Session = Depends(get_session)):
    page = _load_page(db, page_id)
    _ensure_dpi(db, page)
    points = [p.model_dump() for p in data.points]
    try:
        result = g.fit(points, page.width, page.height, data.method, page.dpi)
    except g.FitError as exc:
        raise HTTPException(422, str(exc))

    targets = [page]
    for pid in data.also_page_ids:
        other = services.get_or_404(db, m.Page, pid)
        if other.file_id != page.file_id or (other.width, other.height) != (page.width, page.height):
            raise HTTPException(422, f"Page {pid} does not have the same layout")
        targets.append(other)

    for target in targets:
        geo = target.georef or m.Georeference(page_id=target.id)
        geo.requested_method, geo.method, geo.points, geo.clip = data.method, result.method, points, data.clip
        geo.matrix, geo.corners, geo.rms_m = result.matrix, result.corners, result.rms_m
        geo.scale, geo.rotation_deg, geo.metres_per_px = result.scale, result.rotation_deg, result.metres_per_px
        target.georef = geo

    # Give the map a location if it has none yet.
    mp = page.file.version.map if page.file.version else None
    if mp and mp.lat is None:
        mp.lat, mp.lon = round(result.center[0], 6), round(result.center[1], 6)
    db.commit()
    db.refresh(page)
    return _context(db, page)


@router.delete("/pages/{page_id}/georef", status_code=204)
def delete_georef(page_id: int, db: Session = Depends(get_session)):
    page = _load_page(db, page_id)
    if page.georef:
        db.delete(page.georef)
        db.commit()
