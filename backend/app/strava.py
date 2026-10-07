"""Strava: connect (OAuth), keep the access token fresh, and import activities.

The app is registered by you at strava.com/settings/api; its client ID and
secret come from OMAPS_STRAVA_CLIENT_ID / OMAPS_STRAVA_CLIENT_SECRET. After
"Connect with Strava" the tokens are kept in the settings table under the
key "strava" (never returned by the API, never published).

Strava's API agreement allows showing an athlete's data only to that
athlete, so none of this reaches the public site.
"""
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from . import config
from . import models as m

log = logging.getLogger(__name__)
_lock = threading.Lock()

SCOPE = "read,activity:read_all"
PER_PAGE = 200  # Strava's maximum
PAGES_PER_CALL = 5  # one sync call fetches at most 1000 activities; the page asks again for more
FOOT_SPORTS = {"Run", "TrailRun", "Walk", "Hike", "VirtualRun"}
# Names that mean orienteering, in English, Dutch, French and German, plus Flemish permanent courses.
ORIENTEERING_RE = re.compile(
    r"orient|oriënt|course d.orientation|\bo-?(loop|lopen|sprint|race|training)\b|\bOL\b|\bhitta\b|mapico|postenloop",
    re.IGNORECASE,
)
# ...but not the walk or jog to the start and back.
NOT_A_RACE_RE = re.compile(r"\bto the start\b|\bback (to|from)\b|\bfrom the finish\b|warm.?up", re.IGNORECASE)


class StravaError(Exception):
    pass


def configured() -> bool:
    return bool(config.STRAVA_CLIENT_ID and config.STRAVA_CLIENT_SECRET)


def _client() -> httpx.Client:
    """One place to build the HTTP client, so tests can swap in a mock transport."""
    return httpx.Client(timeout=30, headers={"User-Agent": "orienteeringmaps"})


# --- stored connection --------------------------------------------------------

def _get(db: Session, key: str) -> dict | None:
    row = db.get(m.Setting, key)
    return dict(row.value) if row and isinstance(row.value, dict) else None


def _put(db: Session, key: str, value: dict | None) -> None:
    row = db.get(m.Setting, key)
    if value is None:
        if row:
            db.delete(row)
    else:
        row = row or m.Setting(key=key)
        row.value = dict(value)
        flag_modified(row, "value")
        db.add(row)
    db.commit()


def connection(db: Session) -> dict | None:
    return _get(db, "strava")


def status(db: Session) -> dict:
    conn = connection(db) or {}
    total = db.scalar(select(func.count()).select_from(m.StravaActivity)) or 0
    orienteering = db.scalar(select(func.count()).select_from(m.StravaActivity)
                             .where(m.StravaActivity.orienteering == 1)) or 0
    return {
        "configured": configured(),
        "connected": bool(conn.get("refresh_token")),
        "athlete": conn.get("athlete"),
        "scope": conn.get("scope"),
        "private_activities": "activity:read_all" in (conn.get("scope") or ""),
        "last_sync": conn.get("last_sync"),
        "error": conn.get("error"),
        "counts": {"activities": total, "orienteering": orienteering},
    }


# --- OAuth ----------------------------------------------------------------------

def authorize_url(db: Session, redirect_uri: str) -> str:
    if not configured():
        raise StravaError("Strava is not set up: add OMAPS_STRAVA_CLIENT_ID and OMAPS_STRAVA_CLIENT_SECRET to .env.")
    state = secrets.token_urlsafe(16)
    _put(db, "strava_oauth_state", {"state": state, "at": time.time()})
    return config.STRAVA_OAUTH + "/authorize?" + urlencode({
        "client_id": config.STRAVA_CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code",
        "approval_prompt": "auto", "scope": SCOPE, "state": state,
    })


def _token_request(data: dict) -> dict:
    try:
        with _client() as c:
            r = c.post(config.STRAVA_OAUTH + "/token", data={
                "client_id": config.STRAVA_CLIENT_ID, "client_secret": config.STRAVA_CLIENT_SECRET, **data})
    except httpx.HTTPError as exc:
        raise StravaError(f"Strava unreachable: {exc}") from exc
    if r.status_code in (400, 401):
        raise StravaError("Strava refused the request: check the client ID and secret, or connect again.")
    if r.status_code != 200:
        raise StravaError(f"Strava said {r.status_code}: {r.text[:200]}")
    return r.json()


def finish_connect(db: Session, code: str, state: str, scope: str) -> dict:
    saved = _get(db, "strava_oauth_state") or {}
    _put(db, "strava_oauth_state", None)
    if not state or not secrets.compare_digest(state, saved.get("state", "")) or time.time() - saved.get("at", 0) > 3600:
        raise StravaError("The Strava sign-in expired or didn't start here. Please try again.")
    if "activity:read" not in scope:
        raise StravaError("Strava access to your activities was not granted. Connect again and keep "
                          "“View data about your activities” ticked.")
    tok = _token_request({"code": code, "grant_type": "authorization_code"})
    a = tok.get("athlete") or {}
    conn = {
        "access_token": tok["access_token"], "refresh_token": tok["refresh_token"], "expires_at": tok["expires_at"],
        "scope": scope,
        "athlete": {"id": a.get("id"), "name": " ".join(filter(None, [a.get("firstname"), a.get("lastname")])) or None,
                    "profile": a.get("profile_medium")},
        "last_sync": None,
    }
    _put(db, "strava", conn)
    return conn


def _access_token(db: Session) -> str:
    conn = connection(db)
    if not conn or not conn.get("refresh_token"):
        raise StravaError("Not connected to Strava.")
    if conn.get("expires_at", 0) > time.time() + 120:
        return conn["access_token"]
    try:
        tok = _token_request({"refresh_token": conn["refresh_token"], "grant_type": "refresh_token"})
    except StravaError as exc:
        _put(db, "strava", conn | {"error": str(exc)})
        raise
    conn |= {"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
             "expires_at": tok["expires_at"], "error": None}
    _put(db, "strava", conn)
    return conn["access_token"]


def disconnect(db: Session) -> int:
    """Revoke access at Strava (best effort), forget the tokens and delete the imported activities."""
    conn = connection(db)
    if conn and conn.get("access_token"):
        try:
            with _client() as c:
                c.post(config.STRAVA_OAUTH + "/deauthorize", data={"access_token": _access_token(db)})
        except (httpx.HTTPError, StravaError) as exc:
            log.warning("Strava deauthorize failed: %s", exc)
    n = db.query(m.StravaActivity).delete()
    db.commit()
    _put(db, "strava", None)
    return n


# --- import -----------------------------------------------------------------------

def _api_get(token: str, path: str, params: dict) -> list | dict:
    try:
        with _client() as c:
            r = c.get(config.STRAVA_API + path, params=params, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise StravaError(f"Strava unreachable: {exc}") from exc
    if r.status_code == 429:
        raise StravaError("Strava's rate limit is reached. Try again in 15 minutes.")
    if r.status_code == 401:
        raise StravaError("Strava no longer accepts the connection. Disconnect and connect again.")
    if r.status_code != 200:
        raise StravaError(f"Strava said {r.status_code}: {r.text[:200]}")
    return r.json()


def decode_polyline(s: str) -> list[tuple[float, float]]:
    """Google's encoded polyline format (5 decimals), as used by Strava."""
    out, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lon += vals[1]
        out.append((lat / 1e5, lon / 1e5))
    return out


def looks_like_orienteering(a: dict) -> bool:
    if a.get("sport_type") not in FOOT_SPORTS or a.get("commute"):
        return False
    name = a.get("name") or ""
    return bool(ORIENTEERING_RE.search(name)) and not NOT_A_RACE_RE.search(name)


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def upsert(db: Session, a: dict) -> bool:
    """Store one activity from Strava's list. Returns True if it is new."""
    row = db.get(m.StravaActivity, a["id"])
    new = row is None
    row = row or m.StravaActivity(id=a["id"])
    poly = (a.get("map") or {}).get("summary_polyline") or None
    pts = decode_polyline(poly) if poly else []
    start = a.get("start_latlng") or []
    row.name = a.get("name") or ""
    row.sport_type = a.get("sport_type") or a.get("type")
    row.start_date = _parse_time(a["start_date"])
    row.start_local = (a.get("start_date_local") or "")[:19] or None
    row.distance_m = a.get("distance")
    row.moving_time_s = a.get("moving_time")
    row.elapsed_time_s = a.get("elapsed_time")
    row.elevation_gain_m = a.get("total_elevation_gain")
    row.workout_type = a.get("workout_type")
    row.commute = int(bool(a.get("commute")))
    row.private = int(bool(a.get("private")))
    row.start_lat, row.start_lon = (start[0], start[1]) if len(start) == 2 else (None, None)
    row.bbox = ([min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
                if pts else None)
    row.polyline = poly
    if not row.orienteering_manual:
        row.orienteering = int(looks_like_orienteering(a))
    row.raw = a
    db.add(row)
    return new


def reclassify(db: Session) -> None:
    """Apply the current orienteering rules to every activity you haven't marked yourself."""
    rows = db.scalars(select(m.StravaActivity).where(m.StravaActivity.orienteering_manual == 0)).all()
    for row in rows:
        row.orienteering = int(looks_like_orienteering(row.raw or {"name": row.name, "sport_type": row.sport_type}))
    db.commit()


def sync(db: Session, full: bool = False, cursor: dict | None = None) -> dict:
    """Import activities, PAGES_PER_CALL pages at a time.

    Without `full`, only activities that started after the newest one already
    stored are fetched. Returns counts and a `next` cursor to pass back for
    the following batch, or None when done.
    """
    if not _lock.acquire(blocking=False):
        raise StravaError("A Strava sync is already running.")
    try:
        token = _access_token(db)
        if cursor:
            after, page = cursor.get("after"), int(cursor.get("page", 1))
        else:
            page = 1
            latest = None if full else db.scalar(select(func.max(m.StravaActivity.start_date)))
            # Overlap by a day, so activities uploaded a little late are not missed.
            after = int(latest.replace(tzinfo=latest.tzinfo or timezone.utc).timestamp()) - 86400 if latest else None
        added = updated = 0
        nxt = None
        for _ in range(PAGES_PER_CALL):
            params = {"per_page": PER_PAGE, "page": page}
            if after:
                params["after"] = after
            batch = _api_get(token, "/athlete/activities", params)
            for a in batch:
                if upsert(db, a):
                    added += 1
                else:
                    updated += 1
            db.commit()
            page += 1
            if len(batch) < PER_PAGE:
                nxt = None
                break
            nxt = {"after": after, "page": page}
        if nxt is None:
            reclassify(db)
        conn = connection(db) or {}
        if nxt is None:
            conn["last_sync"] = datetime.now(timezone.utc).isoformat()
        conn["error"] = None
        _put(db, "strava", conn)
        return {"added": added, "updated": updated, "next": nxt}
    finally:
        _lock.release()
