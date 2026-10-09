"""Runtime configuration, read from environment variables."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("OMAPS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "orienteeringmaps.db"
# Original uploads: never modified, must be backed up.
ORIGINALS_DIR = DATA_DIR / "originals"
# Rendered pages and thumbnails: can always be regenerated from the originals.
DERIVED_DIR = DATA_DIR / "derived"

# Import tasks: uploaded files wait here until the background worker has processed them.
STAGING_DIR = DATA_DIR / "staging"
# A folder on the server with scans to import (mounted read-only in Docker), offered on the Imports page.
IMPORT_DIR = Path(os.environ.get("OMAPS_IMPORT_DIR", "/import" if Path("/import").is_dir() else Path(__file__).resolve().parents[2] / "import"))
IMPORT_WORKER = os.environ.get("OMAPS_IMPORT_WORKER", "1") not in ("0", "false", "no", "")

# Static frontend build (served by FastAPI in the Docker image).
FRONTEND_DIST = Path(os.environ.get("OMAPS_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))

# Public site viewer build (frontend/dist-site), used as the template for publishing.
SITE_DIST = Path(os.environ.get("OMAPS_SITE_DIST", FRONTEND_DIST.parent / "dist-site"))
# Working area for the public site: local preview and the git checkout that is pushed.
PUBLISH_DIR = DATA_DIR / "publish"
# GitHub fine-grained token with Contents + Pages read/write on the public site repo only.
GITHUB_TOKEN = os.environ.get("OMAPS_GITHUB_TOKEN", "")
GITHUB_API = os.environ.get("OMAPS_GITHUB_API", "https://api.github.com")
GITHUB_GIT = os.environ.get("OMAPS_GITHUB_GIT", "https://github.com")

# Strava API app (strava.com/settings/api). Tokens are stored in the database after "Connect with Strava".
STRAVA_CLIENT_ID = os.environ.get("OMAPS_STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.environ.get("OMAPS_STRAVA_CLIENT_SECRET", "")
STRAVA_API = os.environ.get("OMAPS_STRAVA_API", "https://www.strava.com/api/v3")
STRAVA_OAUTH = os.environ.get("OMAPS_STRAVA_OAUTH", "https://www.strava.com/oauth")

# O'Punch, the Belgian orienteering calendar. Its public iCalendar feed is pulled once a day;
# a race's page is fetched only when asked (details) or by the one-off backfill command.
OPUNCH_FEED_URL = os.environ.get("OMAPS_OPUNCH_FEED_URL", "https://www.opunch.org/calendar/all")
OPUNCH_EVENT_URL = os.environ.get("OMAPS_OPUNCH_EVENT_URL", "https://www.opunch.org/in/event/{id}")
OPUNCH_AUTO_PULL = os.environ.get("OMAPS_OPUNCH_AUTO_PULL", "1") not in ("0", "false", "no", "")

# Optional HTTP basic auth. Empty = no auth (LAN use).
APP_USER = os.environ.get("OMAPS_USER", "rik")
APP_PASSWORD = os.environ.get("OMAPS_PASSWORD", "")

# Rendering
PDF_DPI = int(os.environ.get("OMAPS_PDF_DPI", "250"))
MAX_IMAGE_PX = int(os.environ.get("OMAPS_MAX_IMAGE_PX", "7000"))
THUMB_PX = 480
OCR_LANGS = os.environ.get("OMAPS_OCR_LANGS", "nld+eng+fra")

GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
GEOCODER_UA = "orienteeringmaps/1 (personal map library; github.com/rvanbruggen/orienteeringmaps)"


def ensure_dirs() -> None:
    for d in (DATA_DIR, ORIGINALS_DIR, DERIVED_DIR, STAGING_DIR):
        d.mkdir(parents=True, exist_ok=True)
