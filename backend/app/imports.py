"""Import tasks: upload a batch of scans, have them processed in the background, then review them.

Uploading only stores the files (in STAGING_DIR, or they stay in the server's import folder);
a worker thread then runs each one through the normal ingest (duplicate check, rendering,
text). With match_by_date, a file name that starts with YYYYMMDD is matched to your run of
that day (orienteering runs first; otherwise runs and walks that are not commutes):

- the run is linked to an event already: the scan goes onto that event's map, and is done;
- the run's route lies clearly on one placed map: the run is linked to that map (the day's
  event on it, else that day's O'Punch race, else an open permanent course, else a new
  event named after the run) and the scan goes with it; marked auto-linked, for you to check;
- otherwise the scan waits in the inbox, tagged with the run, or with the runs to choose from.

Each item is then reviewed: confirmed when it is where it belongs, or set aside.
"""
import logging
import re
import shutil
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from . import config, opunch, processing, runs
from . import models as m
from .ingest import ingest_path
from .models import utcnow

log = logging.getLogger(__name__)

DATE_RX = re.compile(r"^(\d{4})(\d{2})(\d{2})(?!\d)")
AUTO_INSIDE = 0.5  # share of the route on the one placed map it touches, to link it without asking
FOOT_SPORTS = {"Run", "TrailRun", "Walk", "Hike"}
# Review groups, in the order the Imports page shows them.
GROUPS = ("waiting", "error", "choose", "check", "link", "file", "aside", "done")


def day_from_name(name: str) -> str | None:
    """'2019-04-13' for '20190413 Grobbendonk.pdf'; None without a valid date in front."""
    mt = DATE_RX.match(Path(name).name)
    if not mt:
        return None
    try:
        return date(int(mt[1]), int(mt[2]), int(mt[3])).isoformat()
    except ValueError:
        return None


def runs_on(db: Session, day: str) -> list[m.StravaActivity]:
    """Your runs on that day: the orienteering ones if there are any, else runs and walks (no commutes)."""
    d = date.fromisoformat(day)
    lo = datetime.combine(d - timedelta(days=1), time.min, tzinfo=timezone.utc)
    hi = datetime.combine(d + timedelta(days=2), time.min, tzinfo=timezone.utc)
    q = select(m.StravaActivity).where(or_(
        m.StravaActivity.start_local.startswith(day),
        and_(m.StravaActivity.start_local.is_(None), m.StravaActivity.start_date >= lo,
             m.StravaActivity.start_date < hi),
    )).order_by(m.StravaActivity.start_date)
    acts = [a for a in db.scalars(q) if runs._day(a) == day]
    orienteering = [a for a in acts if a.orienteering]
    return orienteering or [a for a in acts if a.sport_type in FOOT_SPORTS and not a.commute]


def runs_around(db: Session, day: str, days: int = 3) -> list[m.StravaActivity]:
    """Runs and walks within a few days of a date, for choosing a run by hand."""
    d = date.fromisoformat(day)
    lo = datetime.combine(d - timedelta(days=days + 1), time.min, tzinfo=timezone.utc)
    hi = datetime.combine(d + timedelta(days=days + 2), time.min, tzinfo=timezone.utc)
    first, last = (d - timedelta(days=days)).isoformat(), (d + timedelta(days=days)).isoformat()
    q = select(m.StravaActivity).where(m.StravaActivity.start_date >= lo, m.StravaActivity.start_date < hi)
    return [a for a in db.scalars(q.order_by(m.StravaActivity.start_date))
            if first <= (runs._day(a) or "") <= last and (a.orienteering or a.sport_type in FOOT_SPORTS)]


def link_of(db: Session, a: m.StravaActivity) -> m.Participation | None:
    return db.scalars(select(m.Participation).where(m.Participation.strava_activity_id == a.id)).first()


# --- matching -------------------------------------------------------------------------------

def auto_link(db: Session, a: m.StravaActivity) -> m.Participation | None:
    """Link the run to the one placed map its route clearly lies on. None (and nothing changed)
    if no placed map fits, if several do, or if the map has more than one event that day."""
    from .routers.strava import LinkIn, NewEvent  # the same request the link dialog sends

    pts = runs.route_points(a)
    fits = []
    for mp in runs.load_maps(db):
        outlines = runs._outlines(mp)
        if outlines and (sc := runs.score(pts, mp, outlines)) and sc["inside"] >= runs.MIN_INSIDE:
            fits.append((mp, sc))
    if len(fits) != 1 or fits[0][1]["inside"] < AUTO_INSIDE:
        return None
    mp = fits[0][0]
    day = runs._day(a)
    events = [e for v in mp.versions for e in v.events]
    same_day = [e for e in events if runs.date_fit(e, day) == "same_day"]
    open_ = [e for e in events if runs.date_fit(e, day) == "open"]
    race = runs.race_suggestion(a, {day: opunch.races_on(db, day)}) if day else None
    # The day's event on the map; else that day's race (also when a permanent course is open: a
    # race on the day is the likelier run); else the one open permanent course; else a new event.
    if len(same_day) > 1 or (not same_day and not race and len(open_) > 1):
        return None
    if same_day:
        data = LinkIn(map_id=mp.id, event_id=same_day[0].id)
    elif race:
        tied = [e for e in events if e.opunch_id == race["id"]]
        data = (LinkIn(map_id=mp.id, event_id=tied[0].id) if tied else
                LinkIn(map_id=mp.id, new_event=NewEvent(name=race["name"], date=day, opunch_id=race["id"])))
    elif open_:
        data = LinkIn(map_id=mp.id, event_id=open_[0].id)
    else:
        data = LinkIn(map_id=mp.id, new_event=NewEvent(name=a.name, date=day))  # as the link dialog suggests
    try:
        return runs.link(db, a, data)
    except HTTPException as exc:
        log.warning("Could not link run %s to %s: %s", a.id, mp.name, exc.detail)
        db.rollback()
        return None


def _where(p: m.Participation) -> str:
    ev = p.event
    return f"{ev.version.map.name} · {ev.name}" + (f" · {p.course.name}" if p.course else "")


def assign(db: Session, item: m.ImportItem, a: m.StravaActivity | None) -> None:
    """Tie the item's scan to a run (or to none) and file it as far as can be done without you."""
    f = item.file
    if f is not None:
        sugg = dict(f.suggestions or {})
        if a is None:
            sugg.pop("strava_activity_id", None)
        else:
            sugg["strava_activity_id"] = a.id
        f.suggestions = sugg
    item.activity_id = a.id if a else None
    item.note = None
    if a is None:
        item.outcome = "no_run" if item.day else "no_date"
        db.commit()
        return
    if (p := link_of(db, a)) is not None:
        on_map = f is not None and f.map_version_id is not None
        if f is not None and not on_map:
            runs.place_file(p, f)
        item.outcome = "linked"
        item.note = (f"Your run was already linked to {_where(p)}" +
                     ("; the scan was there already." if on_map else "; the scan was added there."))
        item.review = "confirmed"
        db.commit()
        return
    db.commit()  # the tag first: linking the run picks up the scans that carry it
    if f is not None and f.map_version_id is None and (p := auto_link(db, a)) is not None:
        db.refresh(item)
        item.outcome = "auto_linked"
        item.note = f"Linked the run to {_where(p)}, because your route lies on that map."
    else:
        item.outcome = "one"
    db.commit()


def match(db: Session, item: m.ImportItem) -> None:
    item.day = day_from_name(item.original_name)
    item.candidates = None
    if not item.day:
        item.outcome = "no_date"
        db.commit()
        return
    acts = runs_on(db, item.day)
    if len(acts) > 1:
        item.outcome, item.candidates = "several", [a.id for a in acts]
        db.commit()
        return
    assign(db, item, acts[0] if acts else None)


# --- processing -----------------------------------------------------------------------------

def process(db: Session, item: m.ImportItem) -> None:
    path = Path(item.path) if item.path else None
    if path is None or not path.is_file():
        item.status, item.error, item.path = "error", "The file is gone; upload it again.", None
        db.commit()
        return
    res = ingest_path(db, path, item.original_name, move=bool(item.owned))
    item = db.get(m.ImportItem, item.id)  # ingest commits or rolls back the session
    if item is None:
        return  # the task was deleted meanwhile
    item.processed_at = utcnow()
    if item.owned and res.status != "error":
        path.unlink(missing_ok=True)
        item.path = None
    elif item.owned and not path.exists():
        item.path = None  # moved into the library and removed again: nothing left to retry
    if res.status == "error" or res.file is None:
        item.status, item.error = "error", res.error or "Not processed"
        db.commit()
        return
    item.status, item.error, item.file_id = ("duplicate" if res.status == "duplicate" else "done"), None, res.file.id
    db.commit()
    db.refresh(item)
    if item.task.match_by_date:
        match(db, item)


def process_next(session_factory) -> bool:
    """Process the oldest waiting item. False when there was none."""
    with session_factory() as db:
        item = db.scalars(select(m.ImportItem).where(m.ImportItem.status == "queued")
                          .order_by(m.ImportItem.id).limit(1)).first()
        if item is None:
            return False
        item.status = "processing"
        db.commit()
        item_id = item.id
        try:
            process(db, item)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the queue
            log.exception("Import item %s failed", item_id)
            db.rollback()
            if (item := db.get(m.ImportItem, item_id)) is not None:
                item.status, item.error = "error", f"{type(exc).__name__}: {exc}"
                db.commit()
    return True


def process_all(session_factory) -> int:
    n = 0
    while process_next(session_factory):
        n += 1
    return n


# --- adding files ---------------------------------------------------------------------------

def supported(name: str) -> bool:
    return Path(name).suffix.lower() in processing.SUPPORTED_EXTENSIONS


def add_upload(db: Session, task: m.ImportTask, stream: BinaryIO, name: str) -> m.ImportItem:
    """Store an uploaded file until the worker gets to it."""
    name = Path(name).name or "upload"
    item = m.ImportItem(task_id=task.id, original_name=name, owned=1)
    if not supported(name):
        item.status, item.error = "error", "Not a PDF or an image"
    else:
        folder = config.STAGING_DIR / str(task.id)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        with dest.open("wb") as out:
            shutil.copyfileobj(stream, out)
        item.path, item.size_bytes = str(dest), dest.stat().st_size
    db.add(item)
    db.commit()
    return item


def import_root() -> Path:
    return config.IMPORT_DIR.resolve()


def folders() -> list[dict]:
    """Folders in the server's import folder that hold PDFs or images (two levels deep)."""
    root = import_root()
    if not root.is_dir():
        return []
    out = []
    for d in [root, *sorted(p for p in root.glob("*") if p.is_dir()), *sorted(p for p in root.glob("*/*") if p.is_dir())]:
        n = sum(1 for p in d.rglob("*") if p.is_file() and supported(p.name))
        if n:
            out.append({"path": d.relative_to(root).as_posix() if d != root else "", "files": n})
    return out


def add_folder(db: Session, task: m.ImportTask, rel: str) -> int:
    """Queue every PDF and image in a folder of the server's import folder (read in place)."""
    root = import_root()
    folder = (root / rel).resolve()
    if folder != root and root not in folder.parents:
        raise HTTPException(422, "That folder is outside the import folder")
    if not folder.is_dir():
        raise HTTPException(404, "No such folder")
    queued = {i.path for i in task.items}
    n = 0
    for p in sorted(folder.rglob("*")):
        if p.is_file() and supported(p.name) and not p.name.startswith(".") and str(p) not in queued:
            db.add(m.ImportItem(task_id=task.id, original_name=p.name, path=str(p), owned=0,
                                size_bytes=p.stat().st_size))
            n += 1
    db.commit()
    return n


def discard(item: m.ImportItem) -> None:
    """Remove the waiting copy of an item that is deleted."""
    if item.owned and item.path:
        Path(item.path).unlink(missing_ok=True)


# --- review ---------------------------------------------------------------------------------

def group(item: m.ImportItem, linked: bool) -> str:
    """Where the item stands, for the review list."""
    if item.status in ("queued", "processing"):
        return "waiting"
    if item.status == "error":
        return "error"
    if item.review == "confirmed":
        return "done"
    if item.review == "set_aside":
        return "aside"
    if item.outcome == "several" and item.activity_id is None:
        return "choose"
    on_map = item.file is not None and item.file.map_version_id is not None
    if on_map or linked:
        return "check"
    return "link" if item.activity_id else "file"


# --- the worker -----------------------------------------------------------------------------

_wake = threading.Event()


def wake() -> None:
    _wake.set()


def _loop(session_factory) -> None:
    with session_factory() as db:  # a restart interrupted these: start them again
        for item in db.scalars(select(m.ImportItem).where(m.ImportItem.status == "processing")):
            item.status = "queued"
        db.commit()
    while True:
        _wake.clear()
        try:
            process_all(session_factory)
        except Exception:  # noqa: BLE001 - keep the thread alive
            log.exception("Import worker")
        _wake.wait(60)


def start_worker(session_factory) -> threading.Thread | None:
    if not config.IMPORT_WORKER:
        return None
    t = threading.Thread(target=_loop, args=(session_factory,), name="import-worker", daemon=True)
    t.start()
    return t
