# orienteeringmaps

A personal library for orienteering maps: upload PDFs and images, record each map's versions (survey dates), events and courses, place maps on top of aerial photos, and find maps again in a table. A map-based search comes next; see [PLAN.md](PLAN.md).

## Features (v0.2)

- **Upload** PDFs and images (PNG, JPG, TIFF, WebP, HEIC). Originals are stored unchanged, pages are rendered, and duplicates are detected: exact copies by hash, look-alikes by perceptual hash.
- **Pre-filled details**: scale, contour interval, survey date, cartographer, club and course length are read from the PDF text, or from OCR for images. GPS coordinates are read from phone photos.
- **Data model**: Map → Versions (survey dates, scale, contours) → Events (race dates) → Courses (each pointing at a file, or at one page of a multi-page PDF).
- **Library**: sortable and filterable table or card view, CSV export.
- **Inbox** for files not yet attached to a map.
- **Bulk import** of a folder. Course pairs like `…-Kort.pdf` / `…-Lang.pdf` are grouped into one map.
- **Export everything**: a zip with all metadata as JSON plus every original file.
- **Place maps on the world** (v0.2): click matching points on the orienteering map and on aerial imagery (Digitaal Vlaanderen orthophoto, GRB, Esri satellite, OpenStreetMap), side by side.
  - Fits a true-to-scale, affine or perspective transform, with the error per point in metres, the implied scale checked against the printed one, and the map's rotation.
  - After two points, a predicted marker shows where the next point should go.
  - An outline hides the legend and margins in the overlay.
  - Multi-page PDFs with the same layout (one course per page) are placed in one go.
  - Each map page shows the placed overlay with an opacity slider.

## Run with Docker

```bash
cp .env.example .env        # optional: port, login password
docker compose up -d --build
```

The app listens on port 8420. All state lives in `./data` on the host:

| Path | What | Back up? |
|---|---|---|
| `data/orienteeringmaps.db` | SQLite database (WAL mode) | yes — use `sqlite3 … ".backup …"` |
| `data/originals/` | uploaded files, named by SHA-256 | yes |
| `data/derived/` | rendered pages and thumbnails | no — rebuild with `rerender` |

### Bulk import

Copy a folder of maps into `./import` on the host, then:

```bash
docker compose exec orienteeringmaps python -m app.cli import /import
```

Add `--no-group` to leave everything in the inbox instead of creating maps. Maps created this way are flagged "needs review".

To rebuild rendered pages after changing render settings:

```bash
docker compose exec orienteeringmaps python -m app.cli rerender
```

### Deploying an update

```bash
ssh <user>@<docker-host> 'cd ~/orienteeringmaps && git pull --ff-only && docker compose up -d --build'
```

## Development

The backend is Python 3.12 with FastAPI, SQLAlchemy and PyMuPDF. The frontend is Svelte 5 with Vite.

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --port 8420 --reload   # API on :8420, data in ../data
.venv/bin/python -m pytest

cd frontend && npm install && npm run dev               # UI on :5173, proxies /api to :8420
```

For OCR during local development, install Tesseract: `brew install tesseract tesseract-lang`.

## License

The code is under the [MIT License](LICENSE). The map files you store in the app belong to their respective clubs and mappers. They are kept out of this repository.
