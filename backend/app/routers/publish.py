"""Public site: settings, local preview and publishing to GitHub Pages."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import config, github, publish
from .. import models as m
from ..db import get_session

router = APIRouter(tags=["publish"])

PREVIEW_BASE = "/site-preview/"


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_title: str | None = None
    site_description: str | None = None
    author: str | None = None
    contact: str | None = None
    about: str | None = None
    github_repo: str | None = None
    github_branch: str | None = None
    site_url: str | None = None


def _run_out(r: m.PublishRun) -> dict:
    return {"id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at,
            "repo": r.repo, "commit_sha": r.commit_sha, "summary": r.summary, "log": r.log}


@router.get("/api/publish/settings")
def get_settings(db: Session = Depends(get_session)):
    st = publish.get_settings(db)
    return {"settings": st, "token": bool(config.GITHUB_TOKEN), "site_url": publish.site_url(st),
            "repo": publish.repo_full_name(st)}


@router.put("/api/publish/settings")
def put_settings(data: SettingsIn, db: Session = Depends(get_session)):
    values = {k: (v or "") for k, v in data.model_dump(exclude_unset=True).items()}
    if values.get("site_url") and not values["site_url"].startswith(("https://", "http://")):
        raise HTTPException(422, "The site address must start with https://")
    return {"settings": publish.save_settings(db, values)}


@router.get("/api/publish/github")
def github_status(db: Session = Depends(get_session)):
    """Check the token and repository on GitHub (slow: a few API calls)."""
    st = publish.get_settings(db)
    try:
        out = github.status(st)
    except github.PublishError as exc:
        return {"token": bool(config.GITHUB_TOKEN), "error": str(exc)}
    if out.get("login") and out["login"] != st.get("github_login"):
        publish.save_settings(db, {"github_login": out["login"]})
    return out


@router.post("/api/publish/preview")
def preview(db: Session = Depends(get_session)):
    """Build the site into data/publish/preview (served at /site-preview/) and compare it with the last publish."""
    st = publish.get_settings(db)
    url = publish.site_url(st) or "https://example.github.io/site/"
    try:
        local = publish.build_site(db, st, "http://localhost" + PREVIEW_BASE, base=PREVIEW_BASE)
        public = publish.build_site(db, st, url)
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc))
    publish.sync_dir(config.PUBLISH_DIR / "preview", local.files)
    repo_dir = config.PUBLISH_DIR / "repo"
    pending = publish.sync_dir(repo_dir, public.files, dry_run=True) if (repo_dir / ".git").exists() else None
    return {"url": url, "maps": len(public.data["maps"]), "counts": public.counts, "files": len(public.files),
            "size": public.size, "warnings": public.warnings, "pending": pending}


@router.post("/api/publish", status_code=202)
def start_publish(db: Session = Depends(get_session)):
    try:
        return _run_out(github.start(db))
    except github.PublishError as exc:
        raise HTTPException(409, str(exc))


@router.get("/api/publish/runs")
def runs(db: Session = Depends(get_session)):
    # A run still "running" without a worker (container restarted mid-publish) never finishes.
    if not github._lock.locked():
        db.execute(update(m.PublishRun).where(m.PublishRun.status == "running")
                   .values(status="error", finished_at=datetime.now(timezone.utc)))
        db.commit()
    return [_run_out(r) for r in db.scalars(select(m.PublishRun).order_by(m.PublishRun.id.desc()).limit(10))]


@router.get("/api/publish/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_session)):
    r = db.get(m.PublishRun, run_id)
    if r is None:
        raise HTTPException(404, "Not found")
    return _run_out(r)


@router.get("/site-preview/{path:path}", include_in_schema=False)
def site_preview(path: str):
    root = (config.PUBLISH_DIR / "preview").resolve()
    target = (root / path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(404)
    if target.is_dir():
        target = target / "index.html"
    if target.is_file():
        return FileResponse(target, headers={"Cache-Control": "no-cache"})
    if (root / "404.html").is_file():
        return FileResponse(root / "404.html", status_code=404, headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "No preview yet: build one on the Publish page.")
