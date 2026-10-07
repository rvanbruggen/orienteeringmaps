# Orienteering Map Manager — Proposed Plan

Status: **Phase 6 built (v0.10.3)**: Strava import, linking runs to maps and events, photos from Strava, your route on the map, replay and leg splits (§10). Version compare and live GPS are not on the roadmap for now.

## 0. Decisions so far

| # | Topic | Decision |
|---|---|---|
| 1 | Hosting | Docker container (docker compose) on the home Linux Mint box, LAN access, port 8420 |
| 2 | Base maps | Free layers (OSM, satellite, Flemish orthophoto) + KMZ export for Google Earth/My Maps. No Google API key. |
| 3 | Modelling | Map → Versions (survey dates) → Events (race dates) → Courses (per event). Kort/Lang = two courses. |
| 4 | File storage | Option C: bind-mounted `data/` folder on the host + the existing nightly restic backup (§8) |
| 5 | OCAD/KMZ | None available, so all maps are placed manually with the editor |
| 6 | Race history | Strava import is back on the roadmap as Phase 6 (§10). Garmin is not. |
| 7 | File types | Besides PDF, maps often come as **PNG/JPG** (see §1b) |

## 1. What the source files tell us

I looked at the 32 PDFs in `map-sources/`. Some findings change the design:

| Finding | Impact on design |
|---|---|
| **None of the PDFs are georeferenced** (no GeoPDF tags). | We need a georeferencing tool where you click matching points. |
| **The maps are rotated**: they're printed to magnetic north, and the paper isn't square to the grid. | A plain "drag 4 corners" overlay isn't accurate enough. We need a transform fitted to control points (details in §4). |
| **Some PDFs have many pages**: *Mapico Brielmeersen* has 28 and *Moerkensheide* has 46. Each page is the same base map with a different course. *HandleidingMapicoGuldenKamer* is a 10-page manual. | One PDF ≠ one map. A file has pages, and pages can share one georeference. |
| **Many maps come as Kort/Lang pairs** (HITTA): two courses printed on the same base map. | Several files/courses can belong to one map version. |
| **Most PDFs have readable text**: "Schaal 1/5.000", "Hoogtelijnen 2m", "KAART Mei 2021", "TEKENING Jeremy Genar". | We can **pre-fill metadata automatically** on upload. You confirm or correct it. |
| The OCAD export (Boggle) has its text as outlines, so it has no readable text. | Auto-extraction is a suggestion only. Manual entry is always possible. |

## 1b. Image files (PNG / JPG) as well as PDFs

Maps will also arrive as images: club exports, screenshots, scans, phone photos. The app treats an image as a one-page "file", so everything downstream works the same: versions, courses, placing it on the map, and the overlay. The differences:

| Topic | PDF | PNG / JPG (also TIFF, WebP, HEIC from an iPhone) |
|---|---|---|
| Rendering | Rendered to PNG at ~250 dpi | Original used directly; a display copy is made if it's very large |
| Pre-filled details | Read from the PDF text | Optional **OCR** (Tesseract) to find "Schaal 1/…", "Hoogtelijnen …", dates. Less reliable, so always confirm. |
| Starting location | — | Phone photos often have **GPS in the EXIF data**, which centres the editor on the right spot |
| Placing on the map | Flat and true to scale: 2–3 points are enough | Scans and screenshots behave like PDFs. **Phone photos of a paper map** have perspective distortion (the map was photographed at an angle), so these need a **perspective fit with 4+ points**. A "straighten photo" step (click the 4 paper corners) helps a lot before placing it. |
| Scale check | Paper size is known, so the stated scale can be verified | Resolution is unknown, so the check only compares point distances |
| Duplicate detection | Exact file hash | Exact hash plus a "looks similar" check (perceptual hash), because the same map often arrives as both PDF and JPG, or re-saved |

The original file is always kept unchanged; rotated, straightened or downscaled copies are derived from it.

## 2. Architecture (recommendation)

Keep it simple, local-first, and easy to back up:

- **Backend:** Python + FastAPI. Python has the best PDF and geo tooling: PyMuPDF for rendering and text, numpy for transform fitting.
- **Database:** SQLite (one file). Uploaded PDFs and rendered page images go in a `data/` folder.
- **Frontend:** a small SPA (Svelte or Vue, or plain htmx if you prefer minimal). Map views use **Leaflet** or **MapLibre**.
- **Deployment:** one Docker image (FastAPI serves the API and the built frontend), started with `docker compose` on the Mint box. The SQLite DB and all files are on a mounted volume (`/data`), so the container can be rebuilt without losing anything. Exposed on the LAN on a fixed port (port 8420). Optional simple login, in case the box is ever reachable from outside the LAN.
- **Deploying updates:** build locally or on the box from git (`git pull && docker compose up -d --build`). A small `deploy.sh` script can do this over SSH.

### Base maps ("Google Maps or other public maps")
Showing Google Maps tiles requires a Google Maps JS API key with billing enabled, and Google's terms restrict mixing their tiles into other map libraries. Proposal:
- Default layers: **OpenStreetMap**, **Esri World Imagery (satellite)**, and, since everything here is in Flanders, the **Digitaal Vlaanderen orthophoto + GRB WMTS**. These are free, very detailed, and ideal for picking control points.
- Optional **Google Maps / Satellite layer** if you add an API key.
- **Export to KMZ** (GroundOverlay). This opens directly in Google Earth and can be imported into Google My Maps, so the map really does appear "on Google".

## 3. Data model

```
Club            (name, short name, federation, website)
Map             (name, nearest town/municipality, centroid lat/lon, map type
                 [forest / park / sprint / urban / permanent course e.g. HITTA/Mapico],
                 owning club, tags, notes)
 └─ MapVersion  (survey date, cartographer, scale e.g. 1:5000, contour interval,
                 mapping standard [ISOM 2017 / ISSprOM 2019 / ...], notes)
     ├─ File    (original PDF or image, format, sha256 + perceptual hash, page count,
     │           kind: blank map / course / control descriptions / manual / other)
     │   └─ Page (rendered/derived high-res image, thumbnail, → Georeference;
     │            an image file has exactly one page)
     ├─ Georeference (control points, fitted transform, RMS error,
     │                clip polygon to hide legend/margins)
     └─ Event   (date, name, organiser club, type [race / training / permanent course / school],
         │       discipline [sprint/middle/long/...], links: results, Livelox, RouteGadget)
         └─ Course (name e.g. "Kort 2km" / "Lang" / "H21E", length, climb, #controls,
                    → File/Page with the printed course)
                    [v2: my participation — time, position, GPS track from Strava/Garmin]
```

Example: *HITTA Leuven* = 1 Map → 1 Version (1:5 000, 2 m) → 1 Event ("HITTA permanent route") → 2 Courses (Kort, Lang), each with its own PDF. *Mapico Brielmeersen* = 1 Map → Version (May 2021, 1:3 000) → Event → 28 Courses, each pointing to one page of the same PDF.

Files can hang off a Version (blank map, manual) or off a Course (course print).

Notes:
- **Scale and contour interval are on the version, not on the map.** A resurvey often changes them, e.g. 1:10 000 becomes 1:7 500. The table view shows values from the latest version.
- **"Last survey" and "last event"** are calculated from the version and event lists, so the full history is kept automatically.
- One georeference per version can be reused by every page or file with the same layout. You georeference Mapico Brielmeersen once and all 28 course pages line up.

## 4. Georeferencing: how the overlay works

Your idea is right. Here's how to make it work well:

1. On upload, each PDF page is rendered to a high-resolution PNG (~200–300 dpi). Image files are used as-is, after an optional rotate/crop/straighten step.
2. **Side-by-side editor:** the orienteering map is on the left and satellite/ortho imagery on the right. Click a feature on the left (path junction, building corner, fence corner), then the same spot on the right. Repeat.
3. The fitting method depends on how many point pairs you have:
   - **2 points:** a similarity transform (shift + rotation + scale). This is usable already, because orienteering maps are drawn to true scale.
   - **3 or more points:** an **affine least-squares fit**. This also absorbs small print and scan distortions.
   - **4 or more points: a perspective fit**, needed for phone photos taken at an angle.
   - 6 or more points (optional): a polynomial fit, for old or hand-drawn maps or crumpled scans.
4. Live feedback after each point:
   - **Per-point residual in metres:** a badly placed point shows up immediately.
   - **Implied scale check:** for example, "the points imply 1:4 980, the map says 1:5 000 ✓". This is a free sanity check.
   - The overlay preview updates as you add points.
5. **Clip polygon:** optionally draw the outline of the map area, so the legend, title block and white margins don't cover the base map.
6. Display uses an **opacity slider** and a toggle between the base layers. The transform is stored, so it is computed once and reused.

Typical effort: 4–6 well-spread points, about 2 minutes per map.

## 5. User interface

1. **Library (table view):** sortable and filterable columns for name, location, club, scale, contour interval, last survey, last event, number of versions, number of events, and whether it is georeferenced. Free-text search, CSV export.
2. **Explorer (map view):** all maps on one map. Each map shows as its footprint outline once georeferenced, or a pin before that. Filters match the table, and the two views stay in sync. Click a map for a preview card. Zoom in to see the actual overlays.
3. **Map detail page:** PDF viewer with pages, metadata, a timeline of versions and events, the overlay map, and download buttons for the original PDF, PNG and KMZ.
4. **Upload / add:** drag-and-drop PDFs or images (also straight from your phone's camera or photo library). Then:
   - Duplicate check.
   - Metadata pre-filled from the PDF text or from OCR on images.
   - Choose "new map" or "new version / additional file of an existing map". Nearby existing maps are suggested.
5. **Georeference editor** as described in §4.

## 6. Extra features worth considering

Ordered by my guess at value for you:

1. **Bulk import** of the existing `map-sources/` folder, with auto-extracted metadata ready to review.
2. **Version compare:** swipe or fade between two georeferenced versions of the same map to see what changed after a resurvey.
3. **Personal history (v2):** record which events you ran and your result, and import the **GPS track** from Strava / Garmin Connect (or GPX upload), drawn on top of the map overlay. The data model already leaves room for this.
4. **Coverage & insights:**
   - A heatmap of mapped areas.
   - "Maps I haven't run in X years".
   - "Surveys older than N years".
   - Maps per club, events per year.
5. **Overlap detection:** "these 3 maps cover the same park". Useful when one area has a sprint map and a forest map.
6. **In the field (PWA on your phone):** open a map and see your live GPS position on the overlay. Great for permanent courses like HITTA/Mapico.
7. **Exports:** KMZ (Google Earth / My Maps), GeoTIFF (QGIS/OCAD), a JSON/CSV backup of all metadata.
8. **Imports:** if you have OCAD files or OCAD's own KMZ exports, these are often already georeferenced and can skip the manual step.

## 7. Phased delivery

| Phase | Scope | Result |
|---|---|---|
| **1. Foundation** ✅ v0.1.0 | Project skeleton, Docker setup, DB schema, PDF + image upload, rendering, text extraction (OCR for images), metadata forms, table view, bulk import of `map-sources/` | All 32 PDFs browsable with metadata |
| **2. Georeferencing** ✅ v0.2.0 | Side-by-side control-point editor, similarity/affine/perspective fitting + residuals, clip polygon, overlay display with opacity. *A separate "straighten photo" step turned out unnecessary: the perspective fit places angled phone photos directly.* | Maps shown on the satellite base map |
| **3. Explorer & history** ✅ v0.3.0 | Map-based search, versions and events timeline, KMZ export | Full find-and-browse experience |
| **4. Extras** ✅ v0.4.0 | Coverage & insights page (§6 item 4). Version compare and PWA/live GPS were dropped from the roadmap (nearby/overlapping maps already shipped in v0.3). | Insights page |
| **5. Public site** ✅ v0.5.0 | Static site on GitHub Pages with per-map publish levels (see PLAN-public-site.md) | Public map explorer |
| **6. Strava** 🚧 | Import your Strava activities, link races to maps and events, and draw your route on the map (§10) | Personal race history with routes |

Docker deployment to the Mint box is part of Phase 1, so every phase can be used on the real server straight away.

## 8. Where do the PDFs live? (open decision)

The key point: **uploads happen through the web UI on the Mint box**. Whatever we choose has to work with files arriving on the server, not on your Mac.

| Option | Pros | Cons |
|---|---|---|
| **A. PDFs committed to git** | Simple; versioned; GitHub is your backup | Server would have to `git commit/push` on every upload (credentials on the box, merge conflicts). Binary files bloat the repo forever, even after deletion. Rendered PNGs are 5–20× larger than the PDFs. If the repo is ever public, you'd be republishing club maps. |
| **B. Git LFS** | Repo stays small; still versioned | Same "server must push" problem. GitHub free LFS quota is 1 GB storage + 1 GB/month bandwidth. Extra tooling to install. |
| **C. Docker volume on the Mint box + scheduled backup** *(recommended)* | Matches how the app works: uploads land in `/data` right away. Repo stays code-only. No credentials needed on the box. Rendered images can always be regenerated. | You need a backup job; otherwise a disk failure loses everything. |
| **D. Object storage (S3 / Backblaze B2 / MinIO)** | Off-site by design | Overkill for a personal LAN app; more moving parts and a monthly cost. |

**Recommendation: C**, with:
- `data/` and `map-sources/` in `.gitignore`. `map-sources/` is used once for the bulk import.
- A nightly backup of `/data`: SQLite `.backup` + original PDFs (PNGs are skipped because they can be rebuilt). Target: another disk, a NAS, or off-site with `restic`/`rclone` to e.g. Backblaze B2 or Google Drive.
- An **"Export everything"** button: a zip with all metadata as JSON + original PDFs. This makes you independent of the app itself.

## 9. Questions for you

Remaining open points (1–6 from round 1 are answered in §0):

1. ~~**File storage**~~ — answered: option C, covered by the existing Docker backup job.
2. **Extras from §6:** which ones for v1?
3. **Frontend preference:** any preference (Svelte, Vue, React, minimal htmx)? Otherwise I'll pick Svelte.
4. **Mint box:** is Docker + docker compose already installed, and do you have SSH access from this Mac? Is there a port preference?

## 10. Strava (Phase 6)

Your Strava runs can help in three ways:
1. **Placing a map:** a run on the map's terrain shows where it is, and the route helps you find matching points.
2. **Race history:** which races you ran, on which map, with your time and distance.
3. **Route overlay:** your GPS route drawn on the placed map, like Livelox.

### What the data looks like

A sample of 100 activities (Jun–Oct 2026) had 11 orienteering races. They are easy to recognise: "Orienteering" or a series name in the title, sport type `TrailRun` or `Run`, and often the Strava *Race* workout type. Walks to and from the start are logged separately and must be left out. The GPS is in "smart recording" mode, about one point every 4 s. That's enough for the route, but switching the watch to 1-second recording for races gives Livelox-like detail.

### Strava API: what it takes

- **A free API app** registered at strava.com/settings/api. No subscription is needed. It gives a client ID and a client secret, which go in `.env` on the Docker host (`OMAPS_STRAVA_CLIENT_ID`, `OMAPS_STRAVA_CLIENT_SECRET`).
- **Authorisation (OAuth):** you click "Connect with Strava" once. Strava sends your browser back to the app, which stores a refresh token in the database and renews short-lived access tokens itself. The "Authorization Callback Domain" of the Strava app must be the host name you use to open the app (for example `192.168.1.20`, or `localhost` for development). The redirect goes through your browser, so the LAN-only box works.
- **Scope:** `activity:read_all`, so private activities are imported too.
- **No webhooks:** they need a public URL. A **Sync** button (later perhaps a nightly sync) is enough.
- **Rate limits** (around 100–200 requests per 15 minutes, 1000–2000 per day) are no issue: the activity list comes 200 at a time, and the GPS points are fetched once per race.
- **Terms:** the API agreement says a user's Strava data may only be shown *to that user*. So **Strava data never goes on the public site**: the publish step doesn't read it. A route for the public site would have to come from a GPX file you export yourself.
- **Disconnect** removes the tokens, tells Strava to revoke access, and deletes the imported activities.

### Steps

| Step | Scope |
|---|---|
| **6.1 Connect and import** ✅ v0.6.0 | Strava settings in `.env`, OAuth connect/disconnect, sync of the activity list (incremental, 200 per request), a `strava_activities` table (summary, route outline, start and bounding box), orienteering detection, and a **Runs** page to browse, filter and hide activities. |
| **6.2 Link races** ✅ v0.7.0 | Suggest the map: the route lies on a placed map, or passes near the location of a map that isn't placed; a map named in the activity's name ranks first. Suggest the event: same day (also a date in the event's name, like "20261004 Grobbendonk"), or a permanent or multi-day event open that day. The link dialog picks or creates the map (at the middle of the route, marked "needs review"), event and course, and records your result: official time, position, number of runners, notes. Results are kept in a `participations` table apart from the Strava data, so they survive a disconnect. Shown on the map page, the Events page ("Only events I ran") and Insights (your runs per year). Walks to the start and back are no longer counted as orienteering. |
| **6.2b Photos from Strava** ✅ v0.8.0 | The photos on an activity (often the map scan and the result card) are fetched from Strava and shown in the link dialog. Ticked photos go through the normal upload process (duplicate check, OCR, rendering) and are attached to the event's map version; a course map becomes the file of your course. Without GPS in the photo, the middle of the route is kept as its location, so placing it starts in the right spot. Strava serves photos at up to 2048 px on the long side: enough to place and read the map. Files keep `source = "strava"`, and the Publish page warns when such a file would go public (Strava's terms), suggesting you upload your own copy instead. OCR on folded, angled photos finds little, so details are still typed by hand. Since v0.10.0 the type of an imported photo can be changed in the link dialog; the course's file follows (a course map photo of the run becomes the course's file, also when the course is chosen after the import), and a photo left in the inbox goes back to the run's map. |
| **6.3 Route overlay** ✅ v0.9.0 | The full GPS track (Strava streams: position, time, distance, altitude) is fetched once per run when first shown, and kept. The map page's overlay gets a route picker (your runs on this map, newest first) and two views: **On the map** (route on the aerial photo with the placed map) and **Map only** (the map image as printed with the route drawn through the inverse placement, like Livelox). The route is coloured by pace against your typical pace on that run (the median per metre covered, since watches record points unevenly), with start and finish markers. The placing editor shows your route in pink on the aerial photo, and on the map image once there is a fit, so you can see whether the placement is right. A photo imported from Strava remembers its run, so its route shows even before the photo is on a map. |
| **6.4 Livelox extras** ✅ v0.10.0 | **Replay**: time slider, play/pause at 5–120×, a runner dot with a one-minute trail over the faded route. **Adjust route**: shift (1–20 m steps) and turn (0.5°) the route to fix a GPS offset against the map; saved per run (`participations.route_adjust`) and used everywhere the route is drawn or split. **Controls**: click the start, controls and finish on the placed map (either view), drag to move; stored per course in world coordinates (`courses.control_coords`), so every run of that course shares them. **Leg splits**: a control counts as visited at the closest point of the first pass within 30 m after the previous control (closest point overall, marked "?", if the route never comes that close); per leg the split, total time, distance run vs. straight line (extra %) and pace; the slowest leg in bold; click a leg to highlight it and jump the replay there. Not handled yet: running past a later control early, which counts as visiting it. |

