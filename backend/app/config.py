"""Runtime configuration, read from environment variables."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("OMAPS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "orienteeringmaps.db"
# Original uploads: never modified, must be backed up.
ORIGINALS_DIR = DATA_DIR / "originals"
# Rendered pages and thumbnails: can always be regenerated from the originals.
DERIVED_DIR = DATA_DIR / "derived"

# Static frontend build (served by FastAPI in the Docker image).
FRONTEND_DIST = Path(os.environ.get("OMAPS_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))

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
    for d in (DATA_DIR, ORIGINALS_DIR, DERIVED_DIR):
        d.mkdir(parents=True, exist_ok=True)
