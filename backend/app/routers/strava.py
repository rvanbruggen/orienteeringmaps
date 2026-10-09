"""Strava: connect, sync and browse your activities (Runs page)."""
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import opunch, runs, services, strava
from ..db import get_session

router = APIRouter(prefix="/api/strava", tags=["strava"])


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full: bool = False
    cursor: dict | None = None


class ActivityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orienteering: bool


class NewMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    location: str | None = None
    map_type: str | None = None


class NewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    date: str | None = Field(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")
    event_type: str | None = None
    discipline: str | None = None
    version_id: int | None = None  # which version of the map; default: the one in use on the day
    opunch_id: int | None = None  # the race on O'Punch this event is: date, organiser and results are copied


class NewCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    length_km: float | None = Field(None, ge=0)


class PhotoWanted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str = "course"


class PhotoImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photos: list[PhotoWanted]


class LinkIn(BaseModel):
    """Which map, event and course you ran (existing ones by id, or new ones), and your result."""
    model_config = ConfigDict(extra="forbid")
    map_id: int | None = None
    new_map: NewMap | None = None
    event_id: int | None = None
    new_event: NewEvent | None = None
    course_id: int | None = None
    new_course: NewCourse | None = None
    result_time_s: int | None = Field(None, ge=0)
    position: int | None = Field(None, ge=1)
    competitors: int | None = Field(None, ge=1)
    notes: str | None = None


def _link_out(p: m.Participation | None) -> dict | None:
    if p is None:
        return None
    ev = p.event
    return services.participation_out(p) | {"event_name": ev.name, "map_id": ev.version.map_id,
                                        "map_name": ev.version.map.name}


def _out(a: m.StravaActivity, link: m.Participation | None = None, suggestion: dict | None = None,
         opunch_race: dict | None = None) -> dict:
    return {
        "id": a.id, "name": a.name, "sport_type": a.sport_type, "start_date": a.start_date,
        "start_local": a.start_local, "distance_m": a.distance_m, "moving_time_s": a.moving_time_s,
        "elapsed_time_s": a.elapsed_time_s, "elevation_gain_m": a.elevation_gain_m,
        "race": a.workout_type in (1, 11), "commute": bool(a.commute), "private": bool(a.private),
        "start_lat": a.start_lat, "start_lon": a.start_lon, "bbox": a.bbox,
        "orienteering": bool(a.orienteering), "orienteering_manual": bool(a.orienteering_manual),
        "strava_url": f"https://www.strava.com/activities/{a.id}",
        "photo_count": (a.raw or {}).get("total_photo_count") or 0,
        "link": _link_out(link), "suggestion": suggestion, "opunch_race": opunch_race,
    }


def _activity(db: Session, activity_id: int) -> m.StravaActivity:
    a = db.get(m.StravaActivity, activity_id)
    if not a:
        raise HTTPException(404, "Activity not found")
    return a


def _runs_page(error: str | None = None) -> RedirectResponse:
    return RedirectResponse("/#/runs" + (f"?error={quote(error)}" if error else "?connected=1"), status_code=302)


@router.get("/status")
def get_status(db: Session = Depends(get_session)):
    return strava.status(db)


@router.get("/connect")
def connect(request: Request, db: Session = Depends(get_session)):
    """Opened by the browser (not fetched): sends you to Strava to approve access."""
    try:
        url = strava.authorize_url(db, str(request.url_for("strava_callback")))
    except strava.StravaError as exc:
        return _runs_page(str(exc))
    return RedirectResponse(url, status_code=302)


@router.get("/callback", name="strava_callback")
def callback(code: str = "", state: str = "", scope: str = "", error: str = "",
             db: Session = Depends(get_session)):
    """Strava sends the browser back here after you approve (or deny) access."""
    if error:
        return _runs_page("Strava access was not granted." if error == "access_denied" else f"Strava: {error}")
    try:
        strava.finish_connect(db, code, state, scope)
    except strava.StravaError as exc:
        return _runs_page(str(exc))
    return _runs_page()


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_session)):
    return {"deleted": strava.disconnect(db)}


@router.post("/sync")
def sync(data: SyncIn, db: Session = Depends(get_session)):
    try:
        return strava.sync(db, full=data.full, cursor=data.cursor)
    except strava.StravaError as exc:
        raise HTTPException(409, str(exc))


@router.get("/activities")
def list_activities(all: bool = False, db: Session = Depends(get_session)):
    """Activities, newest first, with their link (if linked) or the best map suggestion (orienteering runs)."""
    q = select(m.StravaActivity).order_by(m.StravaActivity.start_date.desc())
    if not all:
        q = q.where(m.StravaActivity.orienteering == 1)
    links = runs.participations_by_activity(db)
    maps, cache = runs.load_maps(db), {}
    races_by_day: dict[str, list[m.OpunchEvent]] = {}
    for r in db.scalars(select(m.OpunchEvent)):
        races_by_day.setdefault(r.date, []).append(r)
        if r.end_date:  # a race over several days counts on each of them
            d = date.fromisoformat(r.date)
            while (d := d + timedelta(days=1)).isoformat() <= r.end_date:
                races_by_day.setdefault(d.isoformat(), []).append(r)
    out = []
    for a in db.scalars(q):
        link = links.get(a.id)
        sug = race = None
        if link is None and a.orienteering:
            best = runs.suggest_maps(a, maps, cache, limit=1)
            if best:
                mp, sc = best[0]
                sug = {"map_id": mp.id, "map_name": mp.name, **sc}
            race = runs.race_suggestion(a, races_by_day)
        out.append(_out(a, link, sug, opunch_race=race))
    return out


@router.get("/activities/{activity_id}/choices")
def choices(activity_id: int, map_id: int | None = None, db: Session = Depends(get_session)):
    """What the link dialog offers: suggested maps with their events and courses, and the current link."""
    a = _activity(db, activity_id)
    link = runs.participations_by_activity(db).get(a.id)
    maps = runs.load_maps(db)
    suggested = [runs.map_choice(mp, a, sc) for mp, sc in runs.suggest_maps(a, maps)]
    extra_id = map_id or (link.event.version.map_id if link else None)
    if extra_id and all(c["map_id"] != extra_id for c in suggested):
        mp = next((x for x in maps if x.id == extra_id), None)
        if mp is None:
            raise HTTPException(404, "Map not found")
        suggested.append(runs.map_choice(mp, a, runs.score(runs.route_points(a), mp)))
    centre = runs.route_centre(a)
    return {"activity": _out(a, link), "maps": suggested, "centre": centre, "races": runs.races_for(db, a)}


@router.put("/activities/{activity_id}/link")
def put_link(activity_id: int, data: LinkIn, db: Session = Depends(get_session)):
    a = _activity(db, activity_id)
    p = runs.link(db, a, data)
    return _out(a, p)


@router.delete("/activities/{activity_id}/link", status_code=204)
def delete_link(activity_id: int, db: Session = Depends(get_session)):
    """Forget that this run belongs to an event. Maps, events and courses stay."""
    a = _activity(db, activity_id)
    p = runs.participations_by_activity(db).get(a.id)
    if p:
        db.delete(p)
        db.commit()


@router.get("/activities/{activity_id}/route")
def get_route(activity_id: int, db: Session = Depends(get_session)):
    """The run's GPS track: latlng, time, distance and altitude (fetched from Strava once)."""
    a = _activity(db, activity_id)
    try:
        return runs.route(db, a)
    except strava.StravaError as exc:
        raise HTTPException(409, str(exc))


@router.get("/activities/{activity_id}/photos")
def get_photos(activity_id: int, db: Session = Depends(get_session)):
    """The photos on the activity at Strava, with the library file each was imported as."""
    a = _activity(db, activity_id)
    try:
        return runs.photos(db, a)
    except strava.StravaError as exc:
        raise HTTPException(409, str(exc))


@router.post("/activities/{activity_id}/photos/import")
def import_photos(activity_id: int, data: PhotoImport, db: Session = Depends(get_session)):
    a = _activity(db, activity_id)
    bad = [p.kind for p in data.photos if p.kind not in s.FILE_KINDS]
    if bad:
        raise HTTPException(422, f"kind must be one of {s.FILE_KINDS}")
    try:
        return runs.import_photos(db, a, data.photos)
    except strava.StravaError as exc:
        raise HTTPException(409, str(exc))


class PhotoKind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str


@router.patch("/activities/{activity_id}/photos/{photo_id}")
def set_photo_kind(activity_id: int, photo_id: str, data: PhotoKind, db: Session = Depends(get_session)):
    """Change the type of a photo already imported from this run (e.g. "course" or "other")."""
    a = _activity(db, activity_id)
    if data.kind not in s.FILE_KINDS:
        raise HTTPException(422, f"kind must be one of {s.FILE_KINDS}")
    f = runs.set_photo_kind(db, a, photo_id, data.kind)
    return {"id": f.id, "kind": f.kind, "map_id": f.version.map_id if f.version else None}


@router.patch("/activities/{activity_id}")
def update_activity(activity_id: int, data: ActivityUpdate, db: Session = Depends(get_session)):
    a = _activity(db, activity_id)
    a.orienteering = int(data.orienteering)
    a.orienteering_manual = 1
    db.commit()
    return _out(a, runs.participations_by_activity(db).get(a.id))
