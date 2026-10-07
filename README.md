# orienteeringmaps

A personal library for orienteering maps: upload PDFs and images, record each map's versions (survey dates), events and courses, place maps on top of aerial photos, and find maps again in a table or on a map. See [PLAN.md](PLAN.md) for the roadmap.

## Features (v0.10.3)

- **Upload** PDFs and images (PNG, JPG, TIFF, WebP, HEIC). Originals are stored unchanged, pages are rendered, and duplicates are detected: exact copies by hash, look-alikes by perceptual hash.
- **Pre-filled details**: scale, contour interval, survey date, cartographer, club and course length are read from the PDF text, or from OCR for images. GPS coordinates are read from phone photos.
- **Data model**: Map → Versions (survey dates, scale, contours) → Events (race dates) → Courses (each pointing at a file, or at one page of a multi-page PDF). A map printed at two scales (say 1:5 000 / 2 m and 1:10 000 / 2.5 m) is one map with two versions; an event can be moved to another version from its Edit form, and the link dialog lets you pick the version for a new event.
- **Library**: sortable and filterable table or card view, CSV export. Tick several maps (shift-click selects a range) to set their club, type or public-site level in one go, add or remove a tag, or mark them reviewed.
- **Inbox** for files not yet attached to a map.
- **Bulk import** of a folder. Course pairs like `…-Kort.pdf` / `…-Lang.pdf` are grouped into one map.
- **Export everything**: a zip with all metadata as JSON plus every original file.
- **Place maps on the world** (v0.2): click matching points on the orienteering map and on aerial imagery (Digitaal Vlaanderen orthophoto, GRB, Esri satellite, OpenStreetMap), side by side.
  - Fits a true-to-scale, affine or perspective transform, with the error per point in metres, the implied scale checked against the printed one, and the map's rotation.
  - After two points, a predicted marker shows where the next point should go.
  - An outline hides the legend and margins in the overlay.
  - Multi-page PDFs with the same layout (one course per page) are placed in one go.
  - Each map page shows the placed overlay with an opacity slider.
- **Explorer map** (v0.3): the library's Map view shows every map as its outline (placed) or a pin (location only), using the same filters as the table. A side list shows the maps in view. Zoomed in, the map images are drawn on top.
- **Events** page: every event on every map, grouped by year, with search and filters.
- **Nearby maps** on each map page, with overlapping maps flagged.
- **Map picture**: a map file is shown first, then a course print, then anything else (result cards last). Choose another one with "Use as map picture" on the map page.
- **Insights** (v0.4):
  - Totals: maps, placed share, mapped area, events, courses, clubs, oldest survey.
  - A coverage map coloured by survey age.
  - Charts of events per year and maps by survey age, club, scale and type, each with a table view.
  - Lists of surveys older than N years and maps without an event in N years.
  - A tidy-up checklist: needs review, not placed, no location, no survey date, no club, inbox.
- **Google Earth export**: a KMZ per map or for the whole library. Rotated and perspective placements are kept, and the outline becomes transparency. Also a GeoJSON export of all outlines for QGIS or uMap.
- **Public site** (v0.5): publish a chosen part of the library as a static website on GitHub Pages.
  - Per map, choose what goes out:
    - *Private*: not on the site (the default).
    - *Outline*: details, events and location only.
    - *Overlay*: also the main map image on the aerial photo.
    - *Full*: also every page, course print and the original files to download.
  - The site has a map explorer with search and filters, a page per map with the overlay and opacity slider, an events list and an About page.
  - Every map has its own page, plus a sitemap, so search engines can find them.
  - Each map page has a "Request removal" link that opens a pre-filled GitHub issue on the site repository.
  - The **Publish** page shows what will change and lets you open a local preview. It pushes to GitHub with one click.
- **Runs** (v0.6–0.10): connect your Strava account and import your activities.
  - Orienteering runs are picked out from their names (not the walk to the start and back), and you can tick or untick any activity yourself.
  - Each run is matched to the map your route lies on, and to the event on that day. **Link…** confirms the map, event and course, or creates them, and records your official time and position.
  - Photos you attached to the run on Strava, such as the map scan and the result card, can be added to the map from the same dialog: no separate upload needed. Strava keeps photos at up to 2048 pixels, enough to place the map. Picked the wrong type? Change it in the same dialog later: a course map becomes the file of the run's course, and a photo that was left in the Inbox goes back to the map.
  - Your runs show on the map page, on the Events page ("Only events I ran") and on Insights.
  - **Your route on the map**: on a placed map, pick one of your runs to draw its GPS route, coloured by pace. View it on the aerial photo, or on the map image as printed ("Map only", like Livelox). The placing editor shows your route as a guide, and draws it on the map once it is fitted, so you can check the placement.
  - **Replay** your run with a time slider, **adjust** the route when the GPS is a few metres off, and click the **controls** of the course once to get your **split times per leg**: time, distance run against the straight line, and pace.
  - Strava data stays in the app and never goes on the public site. Drawing your route on the map comes next (see [PLAN.md](PLAN.md) §10).

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
| `data/publish/` | public site preview and the checkout that is pushed | no — rebuilt at the next publish |

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

### Public site on GitHub Pages

1. On GitHub, create a **public**, empty repository, for example `orienteeringmaps-public`.
2. Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new):
   - Repository access: **only** that repository.
   - Permissions: **Contents** set to "Read and write", and **Pages** set to "Read and write".
3. Add it to `.env` on the Docker host as `OMAPS_GITHUB_TOKEN=github_pat_…`, then run `docker compose up -d`.
4. Open **Publish** in the app:
   - Check the repository name and the site title.
   - Set maps to Outline, Overlay or Full.
   - Press **Publish now**.

GitHub Pages is switched on at the first publish. The site appears at `https://<account>.github.io/<repository>/`. For a custom domain, set the site address on the Publish page and configure the domain in the repository's Pages settings.

### Strava

1. On [strava.com/settings/api](https://www.strava.com/settings/api), create an API application. Any name and website will do.
2. Set its **Authorization Callback Domain** to the host name you open the app with, for example `192.168.1.20`. Leave out `http://` and the port. If Strava doesn't accept an IP address, use a name such as `omaps.lan` and add it to the hosts file of the computer you browse from.
3. Add the Client ID and Client Secret to `.env` on the Docker host as `OMAPS_STRAVA_CLIENT_ID` and `OMAPS_STRAVA_CLIENT_SECRET`, then run `docker compose up -d`.
4. Open **Runs** in the app, press **Connect with Strava** and approve. The first sync imports your activity history.

**Disconnect** on the Runs page revokes the app's access and deletes the imported activities.

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
