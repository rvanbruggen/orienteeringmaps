"""Strava: connect, sync and browse your activities (Runs page)."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import strava
from ..db import get_session

router = APIRouter(prefix="/api/strava", tags=["strava"])


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full: bool = False
    cursor: dict | None = None


class ActivityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orienteering: bool


def _out(a: m.StravaActivity) -> dict:
    return {
        "id": a.id, "name": a.name, "sport_type": a.sport_type, "start_date": a.start_date,
        "start_local": a.start_local, "distance_m": a.distance_m, "moving_time_s": a.moving_time_s,
        "elapsed_time_s": a.elapsed_time_s, "elevation_gain_m": a.elevation_gain_m,
        "race": a.workout_type in (1, 11), "commute": bool(a.commute), "private": bool(a.private),
        "start_lat": a.start_lat, "start_lon": a.start_lon, "bbox": a.bbox,
        "orienteering": bool(a.orienteering), "orienteering_manual": bool(a.orienteering_manual),
        "strava_url": f"https://www.strava.com/activities/{a.id}",
    }


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
    q = select(m.StravaActivity).order_by(m.StravaActivity.start_date.desc())
    if not all:
        q = q.where(m.StravaActivity.orienteering == 1)
    return [_out(a) for a in db.scalars(q)]


@router.patch("/activities/{activity_id}")
def update_activity(activity_id: int, data: ActivityUpdate, db: Session = Depends(get_session)):
    a = db.get(m.StravaActivity, activity_id)
    if not a:
        raise HTTPException(404, "Activity not found")
    a.orienteering = int(data.orienteering)
    a.orienteering_manual = 1
    db.commit()
    return _out(a)
