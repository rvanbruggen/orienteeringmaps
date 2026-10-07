"""Shared queries and ORM → API conversion."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import georef as g
from . import models as m
from . import schemas as s


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {obj_id} not found")
    return obj


def derived_url(name: str) -> str:
    return f"/media/{name}"


def georef_summary(g: m.Georeference | None) -> s.GeorefSummary | None:
    if g is None:
        return None
    return s.GeorefSummary(method=g.method, corners=g.corners, clip=g.clip, rms_m=g.rms_m, scale=g.scale,
                           rotation_deg=g.rotation_deg, point_count=len(g.points), updated_at=g.updated_at)


def page_out(p: m.Page) -> s.PageOut:
    return s.PageOut(id=p.id, page_no=p.page_no, width=p.width, height=p.height, dpi=p.dpi,
                     image_url=derived_url(p.image_name), thumb_url=derived_url(p.thumb_name),
                     georef=georef_summary(p.georef))


def file_out(f: m.File, with_pages: bool = True) -> s.FileOut:
    version = f.version
    return s.FileOut(
        id=f.id, map_version_id=f.map_version_id,
        map_id=version.map_id if version else None,
        map_name=version.map.name if version else None,
        kind=f.kind, original_name=f.original_name, format=f.format, size_bytes=f.size_bytes,
        page_count=f.page_count, text_source=f.text_source, exif_lat=f.exif_lat, exif_lon=f.exif_lon,
        suggestions=f.suggestions or {}, notes=f.notes, source=f.source, created_at=f.created_at,
        original_url=f"/api/files/{f.id}/original",
        thumb_url=derived_url(f.pages[0].thumb_name) if f.pages else None,
        pages=[page_out(p) for p in f.pages] if with_pages else [],
    )


def _cols(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def course_out(c: m.Course) -> s.CourseOut:
    thumb = None
    if c.file is not None and c.file.pages:
        idx = min(max((c.page_no or 1) - 1, 0), len(c.file.pages) - 1)
        thumb = derived_url(c.file.pages[idx].thumb_name)
    return s.CourseOut(**_cols(c), thumb_url=thumb)


def participation_out(p: m.Participation) -> dict:
    a = p.activity
    return {
        "id": p.id, "event_id": p.event_id, "course_id": p.course_id, "strava_activity_id": p.strava_activity_id,
        "date": p.date, "result_time_s": p.result_time_s, "position": p.position, "competitors": p.competitors,
        "notes": p.notes, "course_name": p.course.name if p.course else None, "route_adjust": p.route_adjust,
        "strava": {"name": a.name, "distance_m": a.distance_m, "moving_time_s": a.moving_time_s,
                   "elapsed_time_s": a.elapsed_time_s, "url": f"https://www.strava.com/activities/{a.id}"} if a else None,
    }


def event_out(e: m.Event) -> s.EventOut:
    return s.EventOut(**_cols(e), organiser_name=e.organiser.name if e.organiser else None,
                      courses=[course_out(c) for c in e.courses],
                      participations=[participation_out(p) for p in e.participations])


def version_out(v: m.MapVersion) -> s.VersionOut:
    return s.VersionOut(**_cols(v), events=[event_out(e) for e in v.events],
                        files=[file_out(f) for f in v.files])


def _sort_key(date: str | None) -> str:
    return date or ""


def latest_version(mp: m.Map) -> m.MapVersion | None:
    if not mp.versions:
        return None
    # Undated versions count as the oldest; ties go to the most recently created.
    return max(mp.versions, key=lambda v: (_sort_key(v.survey_date), v.id))


# Which files can stand for the map, best first: a map, then a course print, then anything else
# (result cards, control descriptions, ...). Manuals never do.
KIND_RANK = {"map": 0, "blank": 0, "course": 1}


def _picture_files(mp: m.Map) -> list[m.File]:
    """The map's files in the order they are tried as its picture: the one you chose, then newest
    version first, and within a version by kind (KIND_RANK), then oldest file first."""
    versions = sorted(mp.versions, key=lambda v: (_sort_key(v.survey_date), v.id), reverse=True)
    files = [f for v in versions
             for f in sorted(v.files, key=lambda f: (KIND_RANK.get(f.kind, 2), f.id)) if f.kind != "manual"]
    chosen = [f for f in files if f.id == mp.cover_file_id]
    return chosen + [f for f in files if f.id != mp.cover_file_id]


def cover_file(mp: m.Map) -> m.File | None:
    """The file that pictures the map: your choice if it is still on the map, else the best by kind."""
    return next((f for f in _picture_files(mp) if f.pages), None)


def primary_page(mp: m.Map) -> m.Page | None:
    """The placed page that represents a map, in the same order as its picture."""
    for f in _picture_files(mp):
        for p in f.pages:
            if p.georef is not None:
                return p
    return None


def footprint(page: m.Page) -> list[list[float]]:
    geo = page.georef
    if geo.clip and len(geo.clip) >= 3:
        return g.pixels_to_latlon(geo.matrix, geo.clip)
    return geo.corners


def overlay_of(page: m.Page) -> dict:
    return {"page_id": page.id, "image_url": derived_url(page.image_name), "width": page.width,
            "height": page.height, "corners": page.georef.corners, "clip": page.georef.clip}


def map_summary(mp: m.Map) -> dict:
    latest = latest_version(mp)
    events = [e for v in mp.versions for e in v.events]
    files = [f for v in mp.versions for f in v.files]
    surveys = [v.survey_date for v in mp.versions if v.survey_date]
    event_dates = [e.date for e in events if e.date]
    cover = cover_file(mp)
    thumb = derived_url(cover.pages[0].thumb_name) if cover else None
    return dict(
        id=mp.id, name=mp.name, location=mp.location, lat=mp.lat, lon=mp.lon,
        map_type=mp.map_type, club_id=mp.club_id, club_name=mp.club.name if mp.club else None,
        tags=mp.tags or [], needs_review=bool(mp.needs_review), publish_level=mp.publish_level or "private",
        scale=latest.scale if latest else None,
        contour_interval=latest.contour_interval if latest else None,
        last_survey=max(surveys) if surveys else None,
        last_event=max(event_dates) if event_dates else None,
        version_count=len(mp.versions), event_count=len(events),
        course_count=sum(len(e.courses) for e in events), file_count=len(files),
        placed_count=sum(1 for f in files for p in f.pages if p.georef is not None),
        thumb_url=thumb, cover_file_id=cover.id if cover else None, updated_at=mp.updated_at,
        **_placement(mp),
    )


def _placement(mp: m.Map) -> dict:
    page = primary_page(mp)
    if page is None:
        return {"footprint": None, "overlay": None}
    return {"footprint": footprint(page), "overlay": overlay_of(page)}


MAP_LOAD = (
    selectinload(m.Map.club),
    selectinload(m.Map.versions).selectinload(m.MapVersion.files).selectinload(m.File.pages)
    .selectinload(m.Page.georef),
    selectinload(m.Map.versions).selectinload(m.MapVersion.events).selectinload(m.Event.courses)
    .selectinload(m.Course.file).selectinload(m.File.pages).selectinload(m.Page.georef),
    selectinload(m.Map.versions).selectinload(m.MapVersion.events).selectinload(m.Event.organiser),
    selectinload(m.Map.versions).selectinload(m.MapVersion.events).selectinload(m.Event.participations)
    .selectinload(m.Participation.activity),
)


def load_map(db: Session, map_id: int) -> m.Map:
    mp = db.scalars(select(m.Map).where(m.Map.id == map_id).options(*MAP_LOAD)).first()
    if mp is None:
        raise HTTPException(404, f"Map {map_id} not found")
    return mp


def map_detail(mp: m.Map) -> s.MapDetail:
    return s.MapDetail(
        **map_summary(mp), cover_chosen=mp.cover_file_id is not None and mp.cover_file_id == getattr(cover_file(mp), "id", None),
        notes=mp.notes, public_note=mp.public_note, created_at=mp.created_at,
        versions=[version_out(v) for v in sorted(mp.versions, key=lambda v: (_sort_key(v.survey_date), v.id), reverse=True)],
    )


def find_club_by_name(db: Session, name: str) -> m.Club | None:
    key = name.strip().lower()
    for club in db.scalars(select(m.Club)):
        if key in {club.name.lower(), (club.short_name or "").lower()}:
            return club
    return None


def candidate_maps(db: Session, name: str | None, limit: int = 5) -> list[dict]:
    """Existing maps whose name resembles a suggested name."""
    if not name:
        return []
    words = {w for w in name.lower().split() if len(w) > 2}
    if not words:
        return []
    out = []
    for mp in db.scalars(select(m.Map)):
        hay = f"{mp.name} {mp.location or ''}".lower()
        score = sum(1 for w in words if w in hay)
        if score:
            out.append((score, {"id": mp.id, "name": mp.name, "location": mp.location}))
    out.sort(key=lambda t: -t[0])
    return [o for _, o in out[:limit]]
