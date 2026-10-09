"""O'Punch races: pull the calendar, browse the races, mark the ones you ran, tie them to events (Races page)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from .. import opunch
from ..db import get_session

router = APIRouter(prefix="/api/opunch", tags=["opunch"])


class RaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ran: bool


class RaceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: int


def _race(db: Session, race_id: int) -> m.OpunchEvent:
    r = db.get(m.OpunchEvent, race_id)
    if not r:
        raise HTTPException(404, "Race not found")
    return r


def _event_brief(e: m.Event) -> dict:
    return {"id": e.id, "name": e.name, "date": e.date, "map_id": e.version.map_id, "map_name": e.version.map.name,
            "runs": len(e.participations)}


def _out(r: m.OpunchEvent, events: list[m.Event]) -> dict:
    evs = [_event_brief(e) for e in events]
    return opunch.race_out(r) | {"events": evs, "you_ran": bool(r.ran) or any(e["runs"] for e in evs)}


@router.get("/status")
def get_status(db: Session = Depends(get_session)):
    return opunch.status(db)


@router.post("/pull")
def pull(db: Session = Depends(get_session)):
    try:
        return opunch.pull(db)
    except opunch.OpunchError as exc:
        raise HTTPException(502, str(exc))


@router.get("/races")
def list_races(db: Session = Depends(get_session)):
    """Every race seen so far, newest first, with the library events tied to it."""
    linked = opunch.linked_events(db)
    for evs in linked.values():
        for e in evs:
            db.refresh(e, ["version", "participations"])
    races = db.scalars(select(m.OpunchEvent).order_by(m.OpunchEvent.date.desc(), m.OpunchEvent.start.desc())).all()
    return [_out(r, linked.get(r.id, [])) for r in races]


@router.get("/races/{race_id}")
def get_race(race_id: int, db: Session = Depends(get_session)):
    r = _race(db, race_id)
    return _out(r, opunch.linked_events(db).get(r.id, []))


@router.post("/races/{race_id}/details")
def fetch_details(race_id: int, db: Session = Depends(get_session)):
    """Read the race's page on O'Punch for the club, level, map name and results."""
    r = _race(db, race_id)
    try:
        opunch.fetch_details(db, r)
    except opunch.OpunchError as exc:
        raise HTTPException(502, str(exc))
    return _out(r, opunch.linked_events(db).get(r.id, []))


@router.patch("/races/{race_id}")
def update_race(race_id: int, data: RaceUpdate, db: Session = Depends(get_session)):
    r = _race(db, race_id)
    r.ran = int(data.ran)
    db.commit()
    return _out(r, opunch.linked_events(db).get(r.id, []))


@router.post("/races/{race_id}/link")
def link_event(race_id: int, data: RaceLink, db: Session = Depends(get_session)):
    """Tie an event of a map to this race. The event's blanks (date, organiser, results) are filled from the race."""
    r = _race(db, race_id)
    ev = db.scalars(select(m.Event).where(m.Event.id == data.event_id).options(
        selectinload(m.Event.version).selectinload(m.MapVersion.map), selectinload(m.Event.participations))).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    opunch.apply_to_event(db, r, ev)
    db.commit()
    return _out(r, opunch.linked_events(db).get(r.id, []))


@router.delete("/races/{race_id}/link/{event_id}", status_code=204)
def unlink_event(race_id: int, event_id: int, db: Session = Depends(get_session)):
    ev = db.get(m.Event, event_id)
    if ev and ev.opunch_id == race_id:
        ev.opunch_id = None
        db.commit()
