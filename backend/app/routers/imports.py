"""Import tasks (Imports page): upload a batch of scans, follow their processing, review them."""
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import imports, runs, services
from .. import models as m
from ..db import get_session
from .strava import _out as activity_out

router = APIRouter(prefix="/api/imports", tags=["imports"])


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    match_by_date: bool = True


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class FolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = ""


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: int | None = None


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review: str = Field(pattern="^(open|confirmed|set_aside)$")


def _task(db: Session, task_id: int) -> m.ImportTask:
    t = db.get(m.ImportTask, task_id)
    if t is None:
        raise HTTPException(404, "Import not found")
    return t


def _item(db: Session, item_id: int) -> m.ImportItem:
    i = db.get(m.ImportItem, item_id)
    if i is None:
        raise HTTPException(404, "Import item not found")
    return i


def _summary(t: m.ImportTask, links: dict) -> dict:
    groups = Counter(imports.group(i, i.activity_id in links) for i in t.items)
    total = len(t.items)
    waiting = groups["waiting"]
    to_review = sum(groups[g] for g in ("error", "choose", "check", "link", "file"))
    return {
        "id": t.id, "name": t.name, "match_by_date": bool(t.match_by_date), "created_at": t.created_at,
        "total": total, "processed": total - waiting, "groups": {g: groups[g] for g in imports.GROUPS},
        "to_review": to_review,
        "state": "processing" if waiting else "review" if to_review else "done",
    }


def _item_out(i: m.ImportItem, links: dict, acts: dict) -> dict:
    a = i.activity
    return {
        "id": i.id, "task_id": i.task_id, "original_name": i.original_name, "size_bytes": i.size_bytes,
        "status": i.status, "error": i.error, "day": i.day, "outcome": i.outcome, "note": i.note,
        "review": i.review, "group": imports.group(i, i.activity_id in links),
        "can_retry": i.status == "error" and bool(i.path),
        "file": services.file_out(i.file).model_dump(mode="json") if i.file else None,
        "activity": activity_out(a, links.get(a.id)) if a else None,
        "candidates": [activity_out(acts[c], links.get(c)) for c in i.candidates or [] if c in acts],
    }


def _task_out(db: Session, t: m.ImportTask) -> dict:
    links = runs.participations_by_activity(db)
    ids = {c for i in t.items for c in i.candidates or []}
    acts = {a.id: a for a in db.scalars(select(m.StravaActivity).where(m.StravaActivity.id.in_(ids)))} if ids else {}
    return _summary(t, links) | {"items": [_item_out(i, links, acts) for i in t.items]}


@router.get("")
def list_tasks(db: Session = Depends(get_session)):
    links = runs.participations_by_activity(db)
    tasks = db.scalars(select(m.ImportTask).options(selectinload(m.ImportTask.items).selectinload(m.ImportItem.file))
                       .order_by(m.ImportTask.id.desc())).all()
    return [_summary(t, links) for t in tasks]


@router.post("", status_code=201)
def create_task(data: TaskIn, db: Session = Depends(get_session)):
    t = m.ImportTask(name=(data.name or "").strip() or f"Import {date.today().isoformat()}",
                     match_by_date=int(data.match_by_date))
    db.add(t)
    db.commit()
    return _task_out(db, t)


@router.get("/folders")
def list_folders():
    """Folders with scans in the server's import folder (./import next to docker-compose.yml)."""
    return {"root": str(imports.import_root()), "folders": imports.folders()}


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_session)):
    return _task_out(db, _task(db, task_id))


@router.patch("/{task_id}")
def rename_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_session)):
    t = _task(db, task_id)
    t.name = data.name.strip()
    db.commit()
    return _summary(t, runs.participations_by_activity(db))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_session)):
    """Forget the import. Files already processed stay in the library."""
    t = _task(db, task_id)
    for i in t.items:
        imports.discard(i)
    db.delete(t)
    db.commit()


@router.post("/{task_id}/files")
def upload(task_id: int, files: list[UploadFile], db: Session = Depends(get_session)):
    """Store files for the worker; processing happens in the background."""
    t = _task(db, task_id)
    items = [imports.add_upload(db, t, uf.file, uf.filename or "upload") for uf in files]
    imports.wake()
    return [{"id": i.id, "original_name": i.original_name, "status": i.status, "error": i.error} for i in items]


@router.post("/{task_id}/folder")
def add_folder(task_id: int, data: FolderIn, db: Session = Depends(get_session)):
    n = imports.add_folder(db, _task(db, task_id), data.path)
    imports.wake()
    return {"added": n}


@router.put("/items/{item_id}/run")
def set_run(item_id: int, data: RunIn, db: Session = Depends(get_session)):
    """Choose the run of a scan (or none): filed with it like a match found by date."""
    i = _item(db, item_id)
    if i.status not in ("done", "duplicate"):
        raise HTTPException(409, "This file has not been processed yet")
    a = None
    if data.activity_id is not None:
        a = db.get(m.StravaActivity, data.activity_id)
        if a is None:
            raise HTTPException(404, "Activity not found")
    imports.assign(db, i, a)
    db.refresh(i)
    return _task_out(db, i.task)


@router.get("/items/{item_id}/runs")
def runs_near(item_id: int, around: str | None = None, days: int = 3, db: Session = Depends(get_session)):
    """Runs within a few days of the scan's date (or of `around`), to choose one by hand."""
    i = _item(db, item_id)
    day = around or i.day
    if not day:
        return []
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(422, "Give a date as YYYY-MM-DD")
    links = runs.participations_by_activity(db)
    return [activity_out(a, links.get(a.id)) for a in imports.runs_around(db, day, max(0, min(days, 31)))]


@router.put("/items/{item_id}/review")
def set_review(item_id: int, data: ReviewIn, db: Session = Depends(get_session)):
    i = _item(db, item_id)
    i.review = data.review
    db.commit()
    return _task_out(db, i.task)


@router.post("/items/{item_id}/retry")
def retry(item_id: int, db: Session = Depends(get_session)):
    i = _item(db, item_id)
    if i.status != "error" or not i.path:
        raise HTTPException(409, "Nothing to retry: upload the file again")
    i.status, i.error = "queued", None
    db.commit()
    imports.wake()
    return _task_out(db, i.task)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_session)):
    """Take a file out of the import. If it was processed, it stays in the library."""
    i = _item(db, item_id)
    if i.status == "processing":
        raise HTTPException(409, "This file is being processed; try again in a moment")
    imports.discard(i)
    db.delete(i)
    db.commit()
