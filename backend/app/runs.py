"""Your runs: match Strava activities to maps and events, and link them.

A placed map is suggested when your route lies on it (the share of route
points inside its placed outline); a map that only has a location, when the
route passes close by. Maps whose name appears in the activity's name rank
higher, which separates neighbouring maps of a multi-day event. Events on a
map are ranked by date: same day first, then permanent courses open that day.
"""
import io
import math
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models as m
from . import opunch, services, strava
from .ingest import ingest_stream

MIN_INSIDE = 0.15  # share of the route on a placed map to suggest it
NEAR_M = 1500  # for a map that is not placed: the route passes this close to its location
NAME_WEIGHT = 0.3  # ranking bonus when the map's name appears in the activity's name
MAX_POINTS = 300  # route points used for matching


def load_maps(db: Session) -> list[m.Map]:
    return db.scalars(select(m.Map).options(*services.MAP_LOAD)).all()


def _outlines(mp: m.Map) -> list[list[list[float]]]:
    """Placed outlines ([[lat, lon]]) of every placed page of the map."""
    return [services.footprint(p) for v in mp.versions for f in v.files for p in f.pages
            if p.georef is not None and f.kind != "manual"]


def _inside(lat: float, lon: float, poly: list[list[float]]) -> bool:
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (yi, xi), (yj, xj) = poly[i], poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return 6371000 * math.radians(math.hypot(a[0] - b[0], (a[1] - b[1]) * k))


def route_points(a: m.StravaActivity) -> list[tuple[float, float]]:
    pts = strava.decode_polyline(a.polyline) if a.polyline else []
    if not pts and a.start_lat is not None:
        pts = [(a.start_lat, a.start_lon)]
    step = max(1, len(pts) // MAX_POINTS)
    return pts[::step]


def route_centre(a: m.StravaActivity) -> tuple[float, float] | None:
    if a.bbox:
        return ((a.bbox[0] + a.bbox[2]) / 2, (a.bbox[1] + a.bbox[3]) / 2)
    return (a.start_lat, a.start_lon) if a.start_lat is not None else None


def _bbox(polys) -> tuple[float, float, float, float]:
    lats = [p[0] for poly in polys for p in poly]
    lons = [p[1] for poly in polys for p in poly]
    return min(lats), min(lons), max(lats), max(lons)


def score(pts: list[tuple[float, float]], mp: m.Map, outlines=None) -> dict | None:
    """How well a route fits a map: {inside, distance_m}, or None if it doesn't."""
    if not pts:
        return None
    outlines = _outlines(mp) if outlines is None else outlines
    inside = 0.0
    if outlines:
        b = _bbox(outlines)
        cand = [p for p in pts if b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]]
        if cand:
            inside = sum(1 for p in cand if any(_inside(p[0], p[1], o) for o in outlines)) / len(pts)
    dist = None
    if mp.lat is not None and mp.lon is not None:
        dist = min(_dist_m(p, (mp.lat, mp.lon)) for p in pts)
    if inside >= MIN_INSIDE or (not outlines and dist is not None and dist <= NEAR_M):
        return {"inside": round(inside, 2), "distance_m": round(dist) if dist is not None else None}
    return None


def _words(s: str | None) -> set[str]:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z0-9]+", s) if len(w) >= 4}


def name_match(map_name: str, activity_name: str) -> float:
    """Share of the map name's words (4+ letters) that appear in the activity name."""
    mw = _words(map_name)
    return len(mw & _words(activity_name)) / len(mw) if mw else 0.0


def suggest_maps(a: m.StravaActivity, maps: list[m.Map], cache: dict | None = None, limit: int = 5) -> list[tuple[m.Map, dict]]:
    pts = route_points(a)
    out = []
    for mp in maps:
        outlines = cache.setdefault(mp.id, _outlines(mp)) if cache is not None else None
        sc = score(pts, mp, outlines)
        if sc:
            sc["name_match"] = round(name_match(mp.name, a.name), 2)
            out.append((mp, sc))
    out.sort(key=lambda x: (-(x[1]["inside"] + NAME_WEIGHT * x[1]["name_match"]),
                            x[1]["distance_m"] if x[1]["distance_m"] is not None else 1e9))
    return out[:limit]


def _day(a: m.StravaActivity) -> str | None:
    return a.start_local[:10] if a.start_local else a.start_date.date().isoformat()


def date_fit(e: m.Event, day: str | None) -> str | None:
    """'same_day', 'open' (a permanent or multi-day event covering that day) or None."""
    if not day:
        return None
    if e.date and not e.end_date and day.startswith(e.date) and len(e.date) == 10:
        return "same_day"
    if not e.date and (day in (e.name or "") or day.replace("-", "") in (e.name or "")):
        return "same_day"  # undated, but the name says "20261004 Grobbendonk"
    start, end = e.date or "", e.end_date or ""
    if end and start <= day and day[:len(end)] <= end:
        return "open"
    if e.event_type == "permanent" and (not start or day >= start):
        return "open"
    if e.date and day.startswith(e.date):  # "2026" or "2026-10"
        return "open"
    return None


def version_on(mp: m.Map, day: str | None) -> m.MapVersion | None:
    """The map version in use on that day: the newest one surveyed before it (undated = oldest)."""
    vs = sorted(mp.versions, key=lambda v: (v.survey_date or "", v.id))
    if not vs:
        return None
    before = [v for v in vs if not v.survey_date or not day or v.survey_date <= day]
    return (before or vs)[-1]


def races_for(db: Session, a: m.StravaActivity) -> list[dict]:
    """O'Punch races on the day of the run, close to where it started (nearest first)."""
    day = _day(a)
    if not day:
        return []
    races = opunch.races_on(db, day)
    if not races:
        return []
    lat, lon = (a.start_lat, a.start_lon) if a.start_lat is not None else (route_centre(a) or (None, None))
    return opunch.near(races, lat, lon)


def race_suggestion(a: m.StravaActivity, races_by_day: dict[str, list[m.OpunchEvent]]) -> dict | None:
    """The one race that most likely is this run: the nearest within reach, or the only one that day."""
    day = _day(a)
    races = races_by_day.get(day or "", [])
    if not races:
        return None
    lat, lon = (a.start_lat, a.start_lon) if a.start_lat is not None else (route_centre(a) or (None, None))
    located = [r for r in races if r.lat is not None]
    if lat is not None and located:
        best = min(located, key=lambda r: opunch._dist_m(lat, lon, r.lat, r.lon))
        d = opunch._dist_m(lat, lon, best.lat, best.lon)
        return {"id": best.id, "name": best.name, "distance_m": round(d)} if d <= opunch.NEAR_RACE_M else None
    if len(races) == 1:  # no way to tell by distance; the only race that day is a fair guess
        return {"id": races[0].id, "name": races[0].name, "distance_m": None}
    return None


def map_choice(mp: m.Map, a: m.StravaActivity, sc: dict | None) -> dict:
    """A map as the link dialog shows it: its events (best date fit first) and courses."""
    day = _day(a)
    events = []
    for v in mp.versions:
        for e in v.events:
            fit = date_fit(e, day)
            events.append({
                "id": e.id, "name": e.name, "date": e.date, "end_date": e.end_date, "event_type": e.event_type,
                "version_id": v.id, "fit": fit, "opunch_id": e.opunch_id,
                "courses": [{"id": c.id, "name": c.name, "length_km": c.length_km} for c in e.courses],
            })
    rank = {"same_day": 0, "open": 1, None: 2}
    events.sort(key=lambda e: (rank[e["fit"]], -(int((e["date"] or "0")[:4]))))
    v = version_on(mp, day)
    versions = [{"id": x.id, "label": x.label, "survey_date": x.survey_date, "scale": x.scale,
                 "contour_interval": x.contour_interval}
                for x in sorted(mp.versions, key=lambda x: (x.survey_date or "", x.id), reverse=True)]
    return {"map_id": mp.id, "name": mp.name, "location": mp.location, "score": sc, "events": events,
            "version_id": v.id if v else None, "versions": versions}


def link(db: Session, a: m.StravaActivity, data) -> m.Participation:
    """Link an activity to a map, event and course, creating any that are new. Replaces an earlier link."""
    day = _day(a)
    # Map
    if data.map_id:
        mp = services.load_map(db, data.map_id)
    elif data.new_map and data.new_map.name:
        centre = route_centre(a)
        mp = m.Map(name=data.new_map.name.strip(), location=data.new_map.location or None,
                   lat=centre[0] if centre else None, lon=centre[1] if centre else None,
                   map_type=data.new_map.map_type or None, needs_review=1)
        mp.versions.append(m.MapVersion())
        db.add(mp)
        db.flush()
    else:
        raise HTTPException(422, "Choose a map, or name a new one")
    # Event
    if data.event_id:
        ev = db.get(m.Event, data.event_id)
        if not ev or ev.version.map_id != mp.id:
            raise HTTPException(422, "That event is not on this map")
    elif data.new_event and data.new_event.name:
        if data.new_event.version_id:
            v = next((x for x in mp.versions if x.id == data.new_event.version_id), None)
            if v is None:
                raise HTTPException(422, "That version is not on this map")
        else:
            v = version_on(mp, day)
        if v is None:
            v = m.MapVersion(map_id=mp.id)
            db.add(v)
            db.flush()
        ne = data.new_event
        ev = m.Event(map_version_id=v.id, name=ne.name.strip(), date=ne.date or day, event_type=ne.event_type or None,
                     discipline=ne.discipline or None)
        db.add(ev)
        db.flush()
        if ne.opunch_id:
            race = db.get(m.OpunchEvent, ne.opunch_id)
            if race is None:
                raise HTTPException(422, "That O'Punch race is not known here")
            db.refresh(ev)
            opunch.apply_to_event(db, race, ev)
    else:
        raise HTTPException(422, "Choose an event, or name a new one")
    # Course
    course = None
    if data.course_id:
        course = db.get(m.Course, data.course_id)
        if not course or course.event_id != ev.id:
            raise HTTPException(422, "That course is not part of this event")
    elif data.new_course and data.new_course.name:
        course = m.Course(event_id=ev.id, name=data.new_course.name.strip(), length_km=data.new_course.length_km)
        db.add(course)
        db.flush()

    p = db.scalars(select(m.Participation).where(m.Participation.strava_activity_id == a.id)).first()
    p = p or m.Participation(strava_activity_id=a.id)
    p.event_id = ev.id
    p.course_id = course.id if course else None
    p.date = day
    p.result_time_s, p.position, p.competitors = data.result_time_s, data.position, data.competitors
    p.notes = data.notes or None
    db.add(p)
    # A course map photo of this run, imported before the course was chosen, becomes the course's file.
    if course is not None and course.file_id is None:
        photo = next((f for f in run_files(db, a) if f.kind == "course"), None)
        if photo is not None:
            course.file_id, course.page_no = photo.id, 1
    # A linked activity is an orienteering run, whatever a later sync thinks of its name.
    a.orienteering, a.orienteering_manual = 1, 1
    if ev.opunch_id and (race := db.get(m.OpunchEvent, ev.opunch_id)):
        race.ran = 1
    db.commit()
    db.refresh(p)
    return p


def participations_by_activity(db: Session) -> dict[int, m.Participation]:
    rows = db.scalars(select(m.Participation).where(m.Participation.strava_activity_id.is_not(None)).options(
        selectinload(m.Participation.event).selectinload(m.Event.version).selectinload(m.MapVersion.map),
        selectinload(m.Participation.course), selectinload(m.Participation.activity))).all()
    return {p.strava_activity_id: p for p in rows}


def route(db: Session, a: m.StravaActivity) -> dict:
    """The run's GPS track, fetched from Strava the first time and kept."""
    if a.streams is None:
        a.streams = strava.streams(db, a.id)
        db.commit()
    s = a.streams or {}
    return {"activity_id": a.id, "name": a.name, "start_local": a.start_local,
            "latlng": s.get("latlng") or [], "time": s.get("time") or [], "distance": s.get("distance") or [],
            "altitude": s.get("altitude") or []}


def map_runs(mp: m.Map) -> list[dict]:
    """Your runs with a Strava track on this map, newest first."""
    out = []
    for v in mp.versions:
        for e in v.events:
            for p in e.participations:
                if p.strava_activity_id:
                    out.append({"activity_id": p.strava_activity_id, "date": p.date, "event_name": e.name,
                                "course_name": p.course.name if p.course else None, "result_time_s": p.result_time_s})
    return sorted(out, key=lambda r: r["date"] or "", reverse=True)


def photos(db: Session, a: m.StravaActivity) -> list[dict]:
    """The activity's Strava photos, marked with the library file they were imported as (if any)."""
    items = strava.photos(db, a.id)
    ids = [p["id"] for p in items]
    files = db.scalars(select(m.File).where(m.File.source == "strava", m.File.source_id.in_(ids))).all() if ids else []
    by_id = {f.source_id: f for f in files}
    for f in files:  # imported before files remembered their run
        if (f.suggestions or {}).get("strava_activity_id") != a.id:
            f.suggestions = (f.suggestions or {}) | {"strava_activity_id": a.id}
    if files:
        db.commit()
    for p in items:
        f = by_id.get(p["id"])
        p["file"] = {"id": f.id, "kind": f.kind, "map_id": f.version.map_id if f.version else None,
                     "thumb_url": services.derived_url(f.pages[0].thumb_name) if f.pages else None} if f else None
    return items


def import_photos(db: Session, a: m.StravaActivity, wanted: list) -> list[dict]:
    """Add Strava photos to the library, like an upload.

    If the activity is linked, the files are attached to the map version of its event, and a
    course print becomes the file of your course if that has none yet. Otherwise they go to
    the inbox. Without GPS in the photo, the route's middle is kept as its location, so placing
    it starts in the right spot.
    """
    available = {p["id"]: p for p in strava.photos(db, a.id)}
    link = participations_by_activity(db).get(a.id)
    centre = route_centre(a)
    out = []
    for n, w in enumerate(wanted, 1):
        p = available.get(w.id)
        if p is None:
            raise HTTPException(404, f"Photo {w.id} is not on this activity")
        existing = db.scalars(select(m.File).where(m.File.source == "strava", m.File.source_id == w.id)).first()
        if existing:
            out.append({"photo_id": w.id, "status": "already", "file_id": existing.id})
            continue
        name = f"{a.name} – Strava photo {n}.jpg"
        res = ingest_stream(db, io.BytesIO(strava.download(p["url"])), name)
        if res.status == "error":
            out.append({"photo_id": w.id, "status": "error", "error": res.error})
            continue
        f = db.get(m.File, res.file.id)
        if res.status == "created":
            f.source, f.source_id = "strava", w.id
            f.kind = w.kind
            # Remember the run, so the placing editor can show its route even before the file is on a map.
            f.suggestions = (f.suggestions or {}) | {"strava_activity_id": a.id}
            if f.exif_lat is None and centre:
                f.exif_lat, f.exif_lon = centre
        place_file(link, f)
        db.commit()
        out.append({"photo_id": w.id, "status": res.status, "file_id": f.id})
    return out


def run_files(db: Session, a: m.StravaActivity) -> list[m.File]:
    """Library files imported from this run's Strava photos, oldest first."""
    files = db.scalars(select(m.File).where(m.File.source == "strava").order_by(m.File.id)).all()
    return [f for f in files if (f.suggestions or {}).get("strava_activity_id") == a.id]


def place_file(link: m.Participation | None, f: m.File) -> None:
    """Put a run's photo where it belongs: on the map of the linked event (if it is in the inbox),
    and as the file of your course if it is a course map and the course has none yet."""
    if link is None:
        return
    if f.map_version_id is None:
        f.map_version_id = link.event.map_version_id
    if link.course is not None and f.kind == "course" and link.course.file_id is None:
        link.course.file_id, link.course.page_no = f.id, 1


def set_photo_kind(db: Session, a: m.StravaActivity, photo_id: str, kind: str) -> m.File:
    """Change what an imported photo is (course map, map, result card / other), and keep the
    course's file in step: a photo that is no longer a course map stops being the course's file,
    and another course map photo of the same run takes its place."""
    f = db.scalars(select(m.File).where(m.File.source == "strava", m.File.source_id == photo_id)).first()
    if f is None:
        raise HTTPException(404, "That photo is not in the library")
    f.kind = kind
    f.suggestions = (f.suggestions or {}) | {"strava_activity_id": a.id}
    link = participations_by_activity(db).get(a.id)
    course = link.course if link else None
    if course is not None and course.file_id == f.id and kind != "course":
        other = next((x for x in run_files(db, a) if x.kind == "course" and x.id != f.id), None)
        course.file_id, course.page_no = (other.id, 1) if other else (None, None)
    place_file(link, f)
    db.commit()
    db.refresh(f)
    return f
