"""O'Punch (opunch.org): the Belgian orienteering calendar.

Two sources, both public, no login:

* The iCalendar feed (OPUNCH_FEED_URL) lists the upcoming races, about a year
  ahead, with their id, name, times, coordinates and location. It never shows
  the past, so `pull()` runs once a day and keeps every race it has seen.
* A race's page (OPUNCH_EVENT_URL) adds what the feed leaves out: the club,
  level, map name, number of registrations and the Helga results links. It is
  plain HTML with a stable layout; `fetch_details()` reads one page on demand,
  `backfill()` reads a range of ids once to recover the last months.

Nothing here needs an API key. Everything stays in the app: races are not
published on the public site.
"""
import html as html_mod
import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from . import config
from . import models as m

log = logging.getLogger(__name__)
_lock = threading.Lock()

PULL_INTERVAL = timedelta(hours=24)
NEAR_RACE_M = 10_000  # a race this close to where your run started is offered when linking
LEVELS = {1: "local", 2: "regional", 3: "national"}


class OpunchError(Exception):
    pass


def _client() -> httpx.Client:
    """One place to build the HTTP client, so tests can swap in a mock transport."""
    return httpx.Client(timeout=30, follow_redirects=True,
                        headers={"User-Agent": "orienteeringmaps (personal map library)"})


# --- status, kept in the settings table under "opunch" ----------------------------

def _get(db: Session) -> dict:
    row = db.get(m.Setting, "opunch")
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def _put(db: Session, value: dict) -> None:
    row = db.get(m.Setting, "opunch") or m.Setting(key="opunch")
    row.value = dict(value)
    flag_modified(row, "value")
    db.add(row)
    db.commit()


def status(db: Session) -> dict:
    st = _get(db)
    count = lambda *where: db.scalar(select(func.count()).select_from(m.OpunchEvent).where(*where)) or 0  # noqa: E731
    today = datetime.now().date().isoformat()
    linked = db.scalar(select(func.count(func.distinct(m.Event.opunch_id))).where(m.Event.opunch_id.is_not(None))) or 0
    return {
        "last_pull": st.get("last_pull"), "last_result": st.get("last_result"), "error": st.get("error"),
        "auto_pull": config.OPUNCH_AUTO_PULL, "feed_url": config.OPUNCH_FEED_URL,
        "counts": {"races": count(), "past": count(m.OpunchEvent.date < today),
                   "with_details": count(m.OpunchEvent.details_at.is_not(None)),
                   "linked": linked, "ran": count(m.OpunchEvent.ran == 1)},
    }


# --- the iCalendar feed ------------------------------------------------------------

def _unescape_ics(s: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda mo: "\n" if mo.group(1) in "nN" else mo.group(1), s)


def _strip_html(s: str) -> str:
    s = re.sub(r"<\s*(br|/p|/li|/h\d|/div|/tr)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*(li|td|th)\b[^>]*>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)  # inline markup (strong, a, span) sits inside words: no space added
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip()


def _ics_dt(value: str) -> tuple[str, str]:
    """('2026-10-10', '2026-10-10T08:45') from 20261010T084500 (local or Z) or 20261010 (all day)."""
    v = value.strip().rstrip("Z")
    day = f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    return day, f"{day}T{v[9:11]}:{v[11:13]}" if len(v) >= 13 else day


def parse_ics(text: str) -> list[dict]:
    """The VEVENTs of an iCalendar file, as dicts ready for `upsert`. Hand-rolled: the feed is simple."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    out = []
    for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)\r?\nEND:VEVENT", unfolded, re.S):
        props: dict[str, str] = {}
        for line in block.split("\n"):
            line = line.rstrip("\r")
            name, _, value = line.partition(":")
            props[name.split(";", 1)[0].upper()] = value
        uid = props.get("UID", "")
        if not uid.isdigit() or "DTSTART" not in props or "SUMMARY" not in props:
            continue
        date, start = _ics_dt(props["DTSTART"])
        end_date = end = None
        if props.get("DTEND"):
            end_date, end = _ics_dt(props["DTEND"])
            if end_date == date:
                end_date = None
        loc = _unescape_ics(props.get("LOCATION", "")).strip()
        lines = [x.strip() for x in loc.split("\n") if x.strip() and x.strip() != "."]
        geo = re.match(r"\s*([+-]?\d+(?:\.\d+)?)\s*;\s*([+-]?\d+(?:\.\d+)?)", props.get("GEO", ""))
        desc = _unescape_ics(props.get("DESCRIPTION", ""))
        desc = re.sub(r"\s*https://www\.opunch\.org/\S+\s*$", "", desc)  # the feed ends every description with the link
        out.append({
            "id": int(uid), "name": _unescape_ics(props["SUMMARY"]).strip(),
            "date": date, "end_date": end_date, "start": start, "end": end,
            "lat": float(geo.group(1)) if geo else None, "lon": float(geo.group(2)) if geo else None,
            "venue": lines[0] if lines else None,
            # "Venue / Street / Town / Belgium / directions": the town is the line before the country.
            "town": next((lines[i - 1] for i, x in enumerate(lines) if x.lower() in ("belgium", "belgique", "belgië", "luxembourg") and i > 0), None),
            "location": "\n".join(lines) or None,
            "description": _strip_html(desc) or None,
            "url": config.OPUNCH_EVENT_URL.format(id=uid),
        })
    return out


def upsert(db: Session, data: dict, source: str = "feed") -> bool:
    """Add or refresh one race. Returns True when it is new. Never touches `ran` or page details."""
    row = db.get(m.OpunchEvent, data["id"])
    new = row is None
    if new:
        row = m.OpunchEvent(id=data["id"], source=source, ran=0)
        db.add(row)
    for k, v in data.items():
        if k == "id":
            continue
        if v is None and not new and k in ("lat", "lon", "venue", "town", "location", "description"):
            continue  # don't lose what an earlier pull or the page gave us
        setattr(row, k, v)
    row.last_seen = datetime.now(timezone.utc)
    return new


def fetch_feed() -> str:
    try:
        with _client() as c:
            r = c.get(config.OPUNCH_FEED_URL)
    except httpx.HTTPError as exc:
        raise OpunchError(f"O'Punch unreachable: {exc}") from exc
    if r.status_code != 200:
        raise OpunchError(f"O'Punch said {r.status_code} for the calendar feed")
    if "BEGIN:VCALENDAR" not in r.text[:500]:
        raise OpunchError("The O'Punch calendar did not return an iCalendar file")
    return r.text


def pull(db: Session) -> dict:
    """Fetch the feed and add or update every race in it. Races that dropped out of the feed stay."""
    if not _lock.acquire(blocking=False):
        raise OpunchError("An O'Punch pull is already running.")
    try:
        st = _get(db)
        try:
            events = parse_ics(fetch_feed())
            added = sum(upsert(db, e) for e in events)
            db.commit()
            result = {"added": added, "updated": len(events) - added, "in_feed": len(events)}
            st.update(last_pull=datetime.now(timezone.utc).isoformat(), last_result=result, error=None)
            _put(db, st)
            log.info("O'Punch: %d races in the feed, %d new", len(events), added)
            return result
        except OpunchError as exc:
            st["error"] = str(exc)
            _put(db, st)
            raise
    finally:
        _lock.release()


# --- a race's page -------------------------------------------------------------------

MONTHS = {mo: i for i, mo in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"], 1)}


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_event_page(page: str) -> dict | None:
    """What a race's page tells us, or None when the id has no (public) race: O'Punch shows its home page then."""
    title = re.search(r"<title>\s*O'Punch \| (\d{2})/(\d{2})/(\d{4}) - (.*?)\s*</title>", page, re.S)
    if not title:
        return None
    d, mo, y, name = title.groups()
    out: dict = {"id": None, "name": html_mod.unescape(name).strip(), "date": f"{y}-{mo}-{d}", "end_date": None}
    if (h4 := re.search(r"<h4>\s*(.*?)<br\s*/?>\s*<small>(.*?)</small>", page, re.S)):
        out["venue"] = _text(h4.group(1)) or None
        when = _text(h4.group(2))
        # "On Saturday, 4 October 2025" or "From Thursday, 29 October 2026 to Sunday, 1 November 2026"
        days = [f"{yy}-{MONTHS[mm.lower()]:02d}-{int(dd):02d}" for dd, mm, yy in
                re.findall(r"(\d{1,2}) ([A-Za-z]+) (\d{4})", when) if mm.lower() in MONTHS]
        if len(days) >= 2 and days[-1] != days[0]:
            out["end_date"] = days[-1]
        if days:
            out["date"] = days[0]
    if (logo := re.search(r'<img class="org-logo" src="/static/img/orgs/([^."]+)\.[a-z]+" title="([^"]*)"', page)):
        out["club_code"], out["club_name"] = logo.group(1).lower(), html_mod.unescape(logo.group(2)).strip() or None
    if (lvl := re.search(r'event-level event-level-(\d)', page)):
        out["level"] = int(lvl.group(1))
    if (reg := re.search(r'title="(\d+) registrations?"', page)):
        out["registrations"] = int(reg.group(1))
    if (mp := re.search(r'<div class="box-title"><i class="fa fa-map"></i>\s*(.*?)</div>', page, re.S)):
        out["map_name"] = _text(mp.group(1)) or None
    if (geo := re.search(r"data-geo='(\{.*?\})'", page)):
        try:
            g = json.loads(geo.group(1))
            out["lat"], out["lon"] = float(g["latitude"]), float(g["longitude"])
        except (ValueError, KeyError, TypeError):
            pass
    if (res := re.search(r'id="helga_res_a" href="([^"]+)"', page)):
        out["results_url"] = html_mod.unescape(res.group(1))
    if (spl := re.search(r'id="helga_splits_a" href="([^"]+)"', page)):
        out["splits_url"] = html_mod.unescape(spl.group(1))
    if (info := re.search(r'<i class="fa fa-info-circle"></i>\s*Informations</div>\s*</div>\s*<div class="box-body">(.*?)<ul class="list-unstyled', page, re.S)):
        out["description"] = _strip_html(info.group(1)) or None
    return out


def fetch_page(opunch_id: int) -> dict | None:
    """Read one race's page. None when there is no public race with that id."""
    try:
        with _client() as c:
            r = c.get(config.OPUNCH_EVENT_URL.format(id=opunch_id))
    except httpx.HTTPError as exc:
        raise OpunchError(f"O'Punch unreachable: {exc}") from exc
    if r.status_code != 200:
        raise OpunchError(f"O'Punch said {r.status_code} for race {opunch_id}")
    data = parse_event_page(r.text)
    if data:
        data["id"] = opunch_id
        data["url"] = config.OPUNCH_EVENT_URL.format(id=opunch_id)
    return data


def fetch_details(db: Session, race: m.OpunchEvent) -> m.OpunchEvent:
    """Fill in club, level, map name, results and registrations from the race's page."""
    data = fetch_page(race.id)
    if data is None:
        raise OpunchError("That race is no longer on O'Punch")
    for k in ("club_code", "club_name", "level", "map_name", "results_url", "splits_url", "registrations"):
        if data.get(k) is not None:
            setattr(race, k, data[k])
    for k in ("venue", "lat", "lon", "description", "end_date"):
        if getattr(race, k) is None and data.get(k) is not None:
            setattr(race, k, data[k])
    race.details_at = datetime.now(timezone.utc)
    db.commit()
    return race


def backfill(db: Session, first_id: int, last_id: int, since: str, delay: float = 1.0,
             progress=None) -> dict:
    """Read the pages for a range of ids once, keeping races dated on or after `since` (YYYY-MM-DD).

    Ids are not in date order on O'Punch and about half of them are not public, so
    the whole range is scanned. Pages are fetched one at a time with a pause between.
    """
    kept = skipped = missing = 0
    for i in range(first_id, last_id + 1):
        data = fetch_page(i)
        if data is None:
            missing += 1
            state = "no race"
        elif data["date"] < since:
            skipped += 1
            state = f"skipped ({data['date']})"
        else:
            new = upsert(db, {k: data.get(k) for k in ("id", "name", "date", "end_date", "lat", "lon", "venue", "description", "url")},
                         source="page")
            race = db.get(m.OpunchEvent, i)
            for k in ("club_code", "club_name", "level", "map_name", "results_url", "splits_url", "registrations"):
                if data.get(k) is not None:
                    setattr(race, k, data[k])
            race.details_at = datetime.now(timezone.utc)
            db.commit()
            kept += 1
            state = f"{'added' if new else 'updated'}  {data['date']}  {data['name']}"
        if progress:
            progress(i, state)
        if delay and i < last_id:
            time.sleep(delay)
    return {"kept": kept, "skipped": skipped, "missing": missing}


# --- races for a run -------------------------------------------------------------------

def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * 111_320, (lon1 - lon2) * 111_320 * k)


def races_on(db: Session, day: str) -> list[m.OpunchEvent]:
    """Races held on that day, including those spanning several days."""
    return db.scalars(select(m.OpunchEvent).where(
        (m.OpunchEvent.date == day) | ((m.OpunchEvent.date <= day) & (m.OpunchEvent.end_date >= day)))).all()


def near(races: list[m.OpunchEvent], lat: float | None, lon: float | None, limit: int = 6) -> list[dict]:
    """Races close to a point, nearest first; races without coordinates last. None of them beyond NEAR_RACE_M."""
    out = []
    for r in races:
        d = _dist_m(lat, lon, r.lat, r.lon) if lat is not None and r.lat is not None else None
        if d is not None and d > NEAR_RACE_M:
            continue
        out.append(race_out(r) | {"distance_m": round(d) if d is not None else None})
    out.sort(key=lambda x: (x["distance_m"] is None, x["distance_m"] or 0))
    return out[:limit]


def race_out(r: m.OpunchEvent) -> dict:
    return {
        "id": r.id, "name": r.name, "date": r.date, "end_date": r.end_date, "start": r.start, "end": r.end,
        "lat": r.lat, "lon": r.lon, "venue": r.venue, "town": r.town, "location": r.location,
        "description": r.description, "url": r.url, "club_code": r.club_code, "club_name": r.club_name,
        "level": r.level, "level_name": LEVELS.get(r.level), "map_name": r.map_name,
        "results_url": r.results_url, "splits_url": r.splits_url, "registrations": r.registrations,
        "has_details": r.details_at is not None, "source": r.source, "ran": bool(r.ran),
    }


def guess_type(r: m.OpunchEvent) -> tuple[str | None, str | None]:
    """(event_type, discipline) from the race's name and level, for a new event made from it."""
    n = r.name.lower()
    discipline = ("sprint" if "sprint" in n or "city" in n else "long" if re.search(r"\b(long|lang)\b", n) else
                  "middle" if re.search(r"\bmiddle\b|\bmidden", n) else "night" if re.search(r"night|nacht|nuit|avond", n) else
                  "relay" if re.search(r"relay|estafette|aflossing|relais", n) else None)
    event_type = ("championship" if re.search(r"\bbk\b|champ|kampioen", n) else
                  "relay" if discipline == "relay" else
                  "training" if re.search(r"training|entra[iî]nement|stage|ecole|école|school", n) else
                  "race" if r.level or re.search(r"regionale|nationale|series|challenge|cup|#\d", n) else None)
    return event_type, discipline


# --- linking a race to an event of a map ------------------------------------------------

def organiser(db: Session, race: m.OpunchEvent) -> m.Club | None:
    """The club that organised the race, created in the library if it isn't there yet."""
    from .services import find_club_by_name
    for key in (race.club_name, race.club_code):
        if key and (club := find_club_by_name(db, key)):
            return club
    if race.club_name:
        club = m.Club(name=race.club_name, short_name=race.club_code.upper() if race.club_code and len(race.club_code) <= 8 else None)
        db.add(club)
        db.flush()
        return club
    return None


def apply_to_event(db: Session, race: m.OpunchEvent, ev: m.Event) -> None:
    """Tie an event to a race and fill the event's blanks from it, including the map's pin."""
    ev.opunch_id = race.id
    if not ev.date:
        ev.date, ev.end_date = race.date, race.end_date
    if not ev.results_url and race.results_url and race.date <= datetime.now().date().isoformat():
        ev.results_url = race.results_url
    if ev.organiser_club_id is None and (club := organiser(db, race)):
        ev.organiser_club_id = club.id
    if ev.event_type is None or ev.discipline is None:
        t, d = guess_type(race)
        ev.event_type = ev.event_type or t
        ev.discipline = ev.discipline or d
    mp = ev.version.map if ev.version else None
    if mp is not None:
        if mp.lat is None and race.lat is not None:
            mp.lat, mp.lon = race.lat, race.lon
        if not mp.location and race.town:
            mp.location = race.town
    if ev.participations:
        race.ran = 1


def new_event(db: Session, race: m.OpunchEvent, version: m.MapVersion) -> m.Event:
    t, d = guess_type(race)
    ev = m.Event(map_version_id=version.id, name=race.name, date=race.date, end_date=race.end_date,
                 event_type=t, discipline=d)
    db.add(ev)
    db.flush()
    db.refresh(ev)
    apply_to_event(db, race, ev)
    return ev


def linked_events(db: Session) -> dict[int, list[m.Event]]:
    """opunch id -> the library events tied to it."""
    out: dict[int, list[m.Event]] = {}
    for e in db.scalars(select(m.Event).where(m.Event.opunch_id.is_not(None))):
        out.setdefault(e.opunch_id, []).append(e)
    return out


# --- the daily pull --------------------------------------------------------------------

def due(db: Session) -> bool:
    last = _get(db).get("last_pull")
    if not last:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= PULL_INTERVAL


def _loop(session_factory, first_delay: float, every: float) -> None:
    time.sleep(first_delay)
    while True:
        try:
            with session_factory() as db:
                if due(db):
                    pull(db)
        except Exception as exc:  # noqa: BLE001 - keep the thread alive, whatever went wrong
            log.warning("O'Punch pull failed: %s", exc)
        time.sleep(every)


def start_scheduler(session_factory, first_delay: float = 20.0, every: float = 3600.0) -> threading.Thread | None:
    """Pull the feed once a day, in a background thread (checked hourly, so a restart doesn't skip a day)."""
    if not config.OPUNCH_AUTO_PULL:
        return None
    t = threading.Thread(target=_loop, args=(session_factory, first_delay, every), name="opunch-pull", daemon=True)
    t.start()
    return t
