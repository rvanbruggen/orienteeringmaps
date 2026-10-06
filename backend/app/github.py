"""Publish the public site to GitHub Pages.

The site is pushed with git (one commit per publish) from a checkout in
data/publish/repo, so only new and changed files are uploaded. The GitHub
REST API is used to check the token and repository and to switch on Pages.

The token comes from OMAPS_GITHUB_TOKEN: a fine-grained token limited to the
site repository, with "Contents" and "Pages" set to read and write. It is
passed to git in environment variables, never written to disk.
"""
import base64
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone

import httpx

from . import config, db, publish
from . import models as m

log = logging.getLogger(__name__)
_lock = threading.Lock()


class PublishError(Exception):
    pass


def _api(method: str, path: str, **kw) -> httpx.Response:
    if not config.GITHUB_TOKEN:
        raise PublishError("No GitHub token: set OMAPS_GITHUB_TOKEN in .env and restart the container.")
    headers = {"Authorization": f"Bearer {config.GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "orienteeringmaps"}
    try:
        return httpx.request(method, config.GITHUB_API + path, headers=headers, timeout=30, **kw)
    except httpx.HTTPError as exc:
        raise PublishError(f"GitHub unreachable: {exc}") from exc


def status(settings: dict) -> dict:
    """What we know about the token, the repository and its Pages site."""
    out = {"token": bool(config.GITHUB_TOKEN), "git": bool(shutil.which("git"))}
    if not config.GITHUB_TOKEN:
        return out
    r = _api("GET", "/user")
    if r.status_code == 401:
        return out | {"error": "The GitHub token is not valid (expired or revoked)."}
    if r.status_code != 200:
        return out | {"error": f"GitHub said {r.status_code}: {r.text[:200]}"}
    login = r.json()["login"]
    out["login"] = login
    full = publish.repo_full_name(settings, login)
    out["repo"] = full
    if not full:
        return out | {"error": "No repository set."}
    r = _api("GET", f"/repos/{full}")
    if r.status_code == 404:
        return out | {"repo_exists": False,
                      "error": f"Repository {full} not found, or the token has no access to it."}
    info = r.json()
    perms = info.get("permissions") or {}
    out |= {"repo_exists": True, "private": info.get("private"), "can_push": perms.get("push", True),
            "html_url": info.get("html_url")}
    r = _api("GET", f"/repos/{full}/pages")
    out["pages"] = r.json() if r.status_code == 200 else None
    out["site_url"] = publish.site_url(settings, login)
    return out


def _git_env() -> dict:
    basic = base64.b64encode(f"x-access-token:{config.GITHUB_TOKEN}".encode()).decode()
    return os.environ | {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{config.GITHUB_GIT}/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def _git(repo_dir, *args, check=True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=repo_dir, env=_git_env(), capture_output=True, text=True, timeout=1800)
    if check and res.returncode != 0:
        raise PublishError(f"git {args[0]} failed: {(res.stderr or res.stdout).strip()[:500]}")
    return res


def _checkout(repo_dir, full: str, branch: str, say) -> None:
    """Bring the local checkout to the current state of the remote branch (or an empty branch)."""
    remote = f"{config.GITHUB_GIT}/{full}.git"
    if (repo_dir / ".git").exists():
        current = _git(repo_dir, "config", "--get", "remote.origin.url", check=False).stdout.strip()
        if current != remote:
            shutil.rmtree(repo_dir)  # another repository: start over
    if not (repo_dir / ".git").exists():
        repo_dir.mkdir(parents=True, exist_ok=True)
        _git(repo_dir, "init", "-q")
        _git(repo_dir, "remote", "add", "origin", remote)
    say(f"Fetching {full} ({branch})…")
    res = _git(repo_dir, "fetch", "-q", "--depth=1", "origin", branch, check=False)
    if res.returncode == 0:
        _git(repo_dir, "checkout", "-q", "-f", "-B", branch, "FETCH_HEAD")
    elif "couldn't find remote ref" in res.stderr:  # empty repository, or a new branch
        say(f"Branch {branch} does not exist yet: starting it.")
        shutil.rmtree(repo_dir)
        repo_dir.mkdir(parents=True)
        _git(repo_dir, "init", "-q")
        _git(repo_dir, "remote", "add", "origin", remote)
        _git(repo_dir, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    else:
        raise PublishError(f"Cannot fetch {full}: {res.stderr.strip()[:300]}")


def _ensure_pages(full: str, branch: str, say) -> bool:
    """Make sure GitHub Pages serves the branch. Returns False if it is (still) off."""
    r = _api("GET", f"/repos/{full}/pages")
    if r.status_code == 200:
        return True
    r = _api("POST", f"/repos/{full}/pages", json={"source": {"branch": branch, "path": "/"}})
    if r.status_code in (201, 409):
        say("Switched on GitHub Pages for the repository.")
        return True
    hint = " (the token has no Pages write permission)" if r.status_code == 403 else ""
    say(f"GitHub Pages is not switched on yet{hint}, so the site is NOT live. Do it once by hand: "
        f"https://github.com/{full}/settings/pages → Deploy from a branch → {branch} / (root) → Save.")
    return False


def run(run_id: int) -> None:
    """Build and push the site. Runs in a background thread; progress goes to the PublishRun row."""
    with db.SessionLocal() as session:
        pr = session.get(m.PublishRun, run_id)
        lines: list[str] = []

        def say(msg: str) -> None:
            log.info("publish: %s", msg)
            lines.append(msg)
            pr.log = "\n".join(lines)
            session.commit()

        try:
            if not shutil.which("git"):
                raise PublishError("git is not installed.")
            settings = publish.get_settings(session)
            st = status(settings)
            if st.get("error"):
                raise PublishError(st["error"])
            if st.get("private"):
                say("Note: the repository is private. GitHub Pages on a free account needs a public repository.")
            if not st.get("can_push"):
                raise PublishError(f"The token cannot write to {st['repo']}: give it Contents read and write.")
            if settings.get("github_login") != st["login"]:
                settings = publish.save_settings(session, {"github_login": st["login"]})
            full, branch = st["repo"], settings["github_branch"] or "main"
            url = publish.site_url(settings, st["login"])
            pr.repo = full
            say(f"Building the site for {url}…")
            site = publish.build_site(session, settings, url)
            say(f"{len(site.data['maps'])} maps, {len(site.files)} files, {site.size / 1e6:.1f} MB.")

            repo_dir = config.PUBLISH_DIR / "repo"
            _checkout(repo_dir, full, branch, say)
            diff = publish.sync_dir(repo_dir, site.files)
            pr.summary = {k: diff[k] for k in ("added", "changed", "removed", "bytes")} | {
                "maps": len(site.data["maps"]), "url": url, "counts": site.counts}
            _git(repo_dir, "add", "-A")
            if _git(repo_dir, "diff", "--cached", "--quiet", check=False).returncode == 0:
                say("Nothing changed since the last publish.")
                pr.status = "unchanged"
            else:
                msg = (f"Publish {len(site.data['maps'])} maps: {diff['added']} added, "
                       f"{diff['changed']} changed, {diff['removed']} removed")
                _git(repo_dir, "-c", "user.name=Orienteering Maps",
                     "-c", f"user.email={st['login']}@users.noreply.github.com", "commit", "-q", "-m", msg)
                say(f"Uploading {diff['bytes'] / 1e6:.1f} MB to GitHub…")
                _git(repo_dir, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
                pr.commit_sha = _git(repo_dir, "rev-parse", "HEAD").stdout.strip()
                say(f"Pushed {pr.commit_sha[:7]}: {msg}.")
                pr.status = "done"
            if _ensure_pages(full, branch, say):
                say(f"Live in a minute or two at {url}")
        except Exception as exc:  # noqa: BLE001 - every failure must end up in the run log
            log.exception("publish failed")
            pr.status = "error"
            lines.append(f"Error: {exc}")
            pr.log = "\n".join(lines)
        finally:
            pr.finished_at = datetime.now(timezone.utc)
            session.commit()
            _lock.release()


def start(session) -> m.PublishRun:
    if not _lock.acquire(blocking=False):
        raise PublishError("A publish is already running.")
    try:
        pr = m.PublishRun(status="running", log="Starting…")
        session.add(pr)
        session.commit()
        threading.Thread(target=run, args=(pr.id,), daemon=True, name=f"publish-{pr.id}").start()
        return pr
    except Exception:
        _lock.release()
        raise
