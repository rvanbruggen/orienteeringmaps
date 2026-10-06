"""Maps, versions, events and courses."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import services
from ..db import get_session

router = APIRouter(prefix="/api", tags=["maps"])


def _apply(obj, data: s._In, *, required: tuple[str, ...] = ()) -> None:
    values = data.model_dump(exclude_unset=True)
    for key in required:
        if key in values and values[key] is None:
            raise HTTPException(422, f"{key} cannot be empty")
    for key, value in values.items():
        setattr(obj, key, value)


def _check_club(db: Session, club_id: int | None) -> None:
    if club_id is not None:
        services.get_or_404(db, m.Club, club_id)


def _check_file_page(db: Session, file_id: int | None, page_no: int | None) -> None:
    if file_id is None:
        return
    f = services.get_or_404(db, m.File, file_id)
    if page_no is not None and page_no > f.page_count:
        raise HTTPException(422, f"File {file_id} has only {f.page_count} page(s)")


# -------------------------------------------------------------------- maps --

@router.get("/maps", response_model=list[s.MapSummary])
def list_maps(db: Session = Depends(get_session)):
    maps = db.scalars(select(m.Map).options(*services.MAP_LOAD).order_by(m.Map.name)).all()
    return [services.map_summary(mp) for mp in maps]


@router.get("/maps/{map_id}", response_model=s.MapDetail)
def get_map(map_id: int, db: Session = Depends(get_session)):
    return services.map_detail(services.load_map(db, map_id))


@router.post("/maps", response_model=s.MapDetail, status_code=201)
def create_map(data: s.MapCreate, db: Session = Depends(get_session)):
    if not data.name:
        raise HTTPException(422, "name is required")
    _check_club(db, data.club_id)
    mp = m.Map(name=data.name, location=data.location, lat=data.lat, lon=data.lon,
               map_type=data.map_type, club_id=data.club_id, tags=data.tags or [], notes=data.notes,
               needs_review=int(bool(data.needs_review)))
    version = m.MapVersion(**(data.version.model_dump() if data.version else {}))
    mp.versions.append(version)
    db.add(mp)
    db.flush()
    for fid in data.file_ids:
        f = services.get_or_404(db, m.File, fid)
        f.map_version_id = version.id
    if data.event or data.courses:
        ev_data = data.event.model_dump() if data.event else {}
        ev_data["name"] = ev_data.get("name") or data.name
        _check_club(db, ev_data.get("organiser_club_id"))
        ev = m.Event(map_version_id=version.id, **ev_data)
        for c in data.courses:
            _check_file_page(db, c.file_id, c.page_no)
            ev.courses.append(m.Course(**c.model_dump()))
        db.add(ev)
    db.commit()
    return services.map_detail(services.load_map(db, mp.id))


@router.patch("/maps/{map_id}", response_model=s.MapDetail)
def update_map(map_id: int, data: s.MapIn, db: Session = Depends(get_session)):
    mp = services.get_or_404(db, m.Map, map_id)
    _check_club(db, data.club_id)
    _apply(mp, data, required=("name",))
    if "tags" in data.model_fields_set and mp.tags is None:
        mp.tags = []
    db.commit()
    return services.map_detail(services.load_map(db, map_id))


@router.delete("/maps/{map_id}", status_code=204)
def delete_map(map_id: int, db: Session = Depends(get_session)):
    """Delete a map with its versions, events and courses. Its files go back to the inbox."""
    mp = services.load_map(db, map_id)
    for v in mp.versions:
        for f in v.files:
            f.map_version_id = None
    db.flush()
    db.delete(mp)
    db.commit()


# ---------------------------------------------------------------- versions --

@router.post("/maps/{map_id}/versions", response_model=s.VersionOut, status_code=201)
def create_version(map_id: int, data: s.VersionIn, db: Session = Depends(get_session)):
    services.get_or_404(db, m.Map, map_id)
    v = m.MapVersion(map_id=map_id, **data.model_dump())
    db.add(v)
    db.commit()
    return services.version_out(v)


@router.patch("/versions/{version_id}", response_model=s.VersionOut)
def update_version(version_id: int, data: s.VersionIn, db: Session = Depends(get_session)):
    v = services.get_or_404(db, m.MapVersion, version_id)
    _apply(v, data)
    db.commit()
    return services.version_out(v)


@router.delete("/versions/{version_id}", status_code=204)
def delete_version(version_id: int, db: Session = Depends(get_session)):
    """Delete a version with its events. Its files go back to the inbox."""
    v = services.get_or_404(db, m.MapVersion, version_id)
    if len(v.map.versions) <= 1:
        raise HTTPException(409, "A map needs at least one version; delete the map instead")
    for f in v.files:
        f.map_version_id = None
    db.flush()
    db.delete(v)
    db.commit()


# ------------------------------------------------------------------ events --

@router.post("/versions/{version_id}/events", response_model=s.EventOut, status_code=201)
def create_event(version_id: int, data: s.EventIn, db: Session = Depends(get_session)):
    services.get_or_404(db, m.MapVersion, version_id)
    if not data.name:
        raise HTTPException(422, "name is required")
    _check_club(db, data.organiser_club_id)
    ev = m.Event(map_version_id=version_id, **data.model_dump())
    db.add(ev)
    db.commit()
    return services.event_out(ev)


@router.patch("/events/{event_id}", response_model=s.EventOut)
def update_event(event_id: int, data: s.EventIn, db: Session = Depends(get_session)):
    ev = services.get_or_404(db, m.Event, event_id)
    _check_club(db, data.organiser_club_id)
    _apply(ev, data, required=("name",))
    db.commit()
    return services.event_out(ev)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_session)):
    db.delete(services.get_or_404(db, m.Event, event_id))
    db.commit()


# ----------------------------------------------------------------- courses --

@router.post("/events/{event_id}/courses", response_model=s.CourseOut, status_code=201)
def create_course(event_id: int, data: s.CourseIn, db: Session = Depends(get_session)):
    services.get_or_404(db, m.Event, event_id)
    if not data.name:
        raise HTTPException(422, "name is required")
    _check_file_page(db, data.file_id, data.page_no)
    c = m.Course(event_id=event_id, **data.model_dump())
    db.add(c)
    db.commit()
    return services.course_out(c)


@router.post("/events/{event_id}/courses/from-file", response_model=list[s.CourseOut], status_code=201)
def courses_from_file(event_id: int, data: s.CoursesFromFile, db: Session = Depends(get_session)):
    """One course per page of a (multi-page) file, named after the page's first line of text."""
    services.get_or_404(db, m.Event, event_id)
    f = services.get_or_404(db, m.File, data.file_id)
    created = []
    for p in f.pages:
        if data.skip_first_page and p.page_no == 1:
            continue
        first_line = next((ln.strip() for ln in (p.text or "").splitlines() if len(ln.strip()) > 2), None)
        name = f"Page {p.page_no}" + (f" – {first_line[:60]}" if first_line else "")
        c = m.Course(event_id=event_id, name=name, file_id=f.id, page_no=p.page_no)
        db.add(c)
        created.append(c)
    db.commit()
    return [services.course_out(c) for c in created]


@router.patch("/courses/{course_id}", response_model=s.CourseOut)
def update_course(course_id: int, data: s.CourseIn, db: Session = Depends(get_session)):
    c = services.get_or_404(db, m.Course, course_id)
    vals = data.model_dump(exclude_unset=True)
    _check_file_page(db, vals.get("file_id", c.file_id), vals.get("page_no", c.page_no))
    _apply(c, data, required=("name",))
    db.commit()
    return services.course_out(c)


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: int, db: Session = Depends(get_session)):
    db.delete(services.get_or_404(db, m.Course, course_id))
    db.commit()
