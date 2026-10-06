"""Metadata, geocoding and full export."""
import json
import tempfile
import zipfile
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from fastapi.responses import JSONResponse, Response

from .. import __version__, config, kml, processing
from .. import models as m
from .. import schemas as s
from .. import services
from ..db import get_session

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/meta")
def meta(db: Session = Depends(get_session)):
    count = lambda model: db.scalar(select(func.count()).select_from(model)) or 0  # noqa: E731
    inbox = db.scalar(select(func.count()).select_from(m.File).where(m.File.map_version_id.is_(None))) or 0
    return {
        "version": __version__,
        "counts": {"maps": count(m.Map), "files": count(m.File), "events": count(m.Event),
                   "clubs": count(m.Club), "inbox": inbox},
        "enums": {"map_types": s.MAP_TYPES, "file_kinds": s.FILE_KINDS, "event_types": s.EVENT_TYPES,
                  "disciplines": s.DISCIPLINES, "standards": s.STANDARDS, "publish_levels": s.PUBLISH_LEVELS},
    }


@router.get("/geocode")
def geocode(q: str):
    """Look up a place name with OpenStreetMap Nominatim (low volume, user-triggered only)."""
    if not q.strip():
        return []
    try:
        r = httpx.get(config.GEOCODER_URL, timeout=10,
                      params={"q": q, "format": "jsonv2", "limit": 5, "countrycodes": "be,nl,fr,de,lu"},
                      headers={"User-Agent": config.GEOCODER_UA})
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Geocoder unavailable: {exc}")
    return [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"])} for x in r.json()]


def _export_payload(db: Session) -> dict:
    maps = db.scalars(select(m.Map).options(*services.MAP_LOAD).order_by(m.Map.id)).all()
    inbox = db.scalars(select(m.File).where(m.File.map_version_id.is_(None))).all()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "app_version": __version__,
        "clubs": [services._cols(c) for c in db.scalars(select(m.Club).order_by(m.Club.id))],
        "maps": [services.map_detail(mp).model_dump(mode="json") for mp in maps],
        "inbox": [services.file_out(f, with_pages=False).model_dump(mode="json") for f in inbox],
    }


@router.get("/export")
def export_all(include_files: bool = True, db: Session = Depends(get_session)):
    """A zip with all metadata as JSON plus every original file, named for humans."""
    payload = _export_payload(db)
    tmp = tempfile.NamedTemporaryFile(dir=config.DATA_DIR, suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("library.json", json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        if include_files:
            for f in db.scalars(select(m.File)):
                src = processing.original_path(f.stored_name)
                if src.exists():
                    z.write(src, f"files/{f.id:05d} {f.original_name}", compress_type=zipfile.ZIP_STORED)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return FileResponse(tmp.name, media_type="application/zip", filename=f"orienteeringmaps-{stamp}.zip",
                        background=BackgroundTask(lambda: __import__("os").unlink(tmp.name)))


@router.get("/export/kmz")
def export_kmz(db: Session = Depends(get_session)):
    """All maps for Google Earth: the main placed page of each, plus pins for maps with only a location."""
    maps = db.scalars(select(m.Map).options(*services.MAP_LOAD).order_by(m.Map.name)).all()
    items = []
    for mp in maps:
        page = services.primary_page(mp)
        if page or mp.lat is not None:
            items.append((mp, [page] if page else []))
    data = kml.build_kmz("Orienteering maps", items)
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(data, media_type="application/vnd.google-earth.kmz",
                    headers={"Content-Disposition": f'attachment; filename="orienteering-maps-{stamp}.kmz"'})


@router.get("/export/geojson")
def export_geojson(db: Session = Depends(get_session)):
    """Map outlines (placed) and points (location only) as GeoJSON, e.g. for QGIS or uMap."""
    maps = db.scalars(select(m.Map).options(*services.MAP_LOAD).order_by(m.Map.name)).all()
    return JSONResponse(kml.build_geojson(maps), media_type="application/geo+json",
                        headers={"Content-Disposition": 'attachment; filename="orienteering-maps.geojson"'})
