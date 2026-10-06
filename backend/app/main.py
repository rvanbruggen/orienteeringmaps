"""FastAPI application: JSON API, media files and the built Svelte frontend."""
import base64
import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, config, db
from .routers import clubs, files, maps, misc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

db.init_db()
app = FastAPI(title="Orienteering Maps", version=__version__)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional basic auth for everything except /healthz (set OMAPS_PASSWORD to enable)."""
    if config.APP_PASSWORD and request.url.path != "/healthz":
        ok = False
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, config.APP_USER) and secrets.compare_digest(pw, config.APP_PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Orienteering Maps"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


for r in (maps.router, files.router, clubs.router, misc.router):
    app.include_router(r)

config.ensure_dirs()
# Rendered pages are immutable (named by content hash), so they can be cached forever.
app.mount("/media", StaticFiles(directory=config.DERIVED_DIR), name="media")


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/media/") or path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (config.FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and config.FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(config.FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
