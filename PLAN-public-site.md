# Public map site on GitHub Pages: proposed plan

Status: **built in v0.5.0** (P1–P3). Decisions in §8.

## 1. Goal

A public, read-only website for orienteering friends:

- Browse the map collection on a map of Flanders.
- Open a map and see it **placed on the aerial photo**, with the same opacity slider as the management app.
- See each map's versions, events and courses.
- **Search and filter** maps and events by name, place, club, type, scale and year.
- Static files only, hosted on **GitHub Pages**. No server, no login, no database.

The management app stays private on the LAN. It becomes the place where you decide **what** is public and press **Publish**.

## 2. What we can reuse

Most of the hard parts already exist and work in the browser:

| Already built | Use on the public site |
|---|---|
| `frontend/src/lib/warp.js`: draws a placed page as one image with a CSS `matrix3d`, from 4 corners and an optional outline | The overlay works unchanged on a static site. It needs only the image URL, its size, the corners and the outline. **No tile server and no GDAL are needed.** |
| `frontend/src/lib/basemaps.js`: Digitaal Vlaanderen aerial photo and GRB, Esri, OSM | Same layers. They are public tile services that the browser loads directly. |
| `ExplorerMap.svelte`, `OverlayMap.svelte`, `Events.svelte`, `format.js` | Reused with a `readonly` option that hides admin links such as "Adjust placement". |
| Hash routing (`#/map/12`) | Works on GitHub Pages as is: deep links need no 404 tricks. |
| `kml.py` / GeoJSON export | Optional download buttons on the public site. |
| Footprints and summaries in `services.py` | The export reuses them, so the public site shows the same numbers as the app. |

The main new pieces are an **export step** (database → JSON + images) and a **small second frontend** that reads that JSON instead of `/api`.

## 3. Architecture

```
 Management app (LAN, Docker)                      GitHub Pages (public)
 ┌─────────────────────────────┐   publish    ┌──────────────────────────────┐
 │ SQLite + data/derived/      │ ───────────► │ index.html + assets/ (viewer)│
 │ "Public" toggle per map     │  export +    │ data/site.json  (metadata)   │
 │ Publish page: preview, diff │  git push    │ img/<hash>.webp (overlays)   │
 └─────────────────────────────┘              │ thumb/<hash>.webp            │
                                              └──────────────────────────────┘
```

### 3a. Export (backend)

A new `app/publish.py`, run as `python -m app.cli publish <out-dir>` (and later from a button):

- **`site.json`**: one file with clubs, maps, versions, events and courses. It includes **only public fields** from an allow-list, so new private fields never leak by accident. It also has per map the footprint, centroid and, for each placed page, `{image, width, height, corners, clip}`. At hundreds of maps this is well under 1 MB gzipped, so the browser loads it once and searches it in memory.
- **Images**: for each placed page, a WebP downscaled to a set maximum size (for example 2000 px on the long side, about 300–600 KB), plus a thumbnail. Files are **named by content hash**, so a re-publish only uploads what changed and browsers can cache images for a long time.
  - Today's rendered pages are about 2000×2900 px and about 1 MB.
- **Course pages** (multi-page PDFs with one course per page) are exported as images too, if that map allows it (§5).
- **Original PDFs are not published** by default (§5).
- The export writes a small `manifest.json` (file → hash). The Publish page then shows "3 new maps, 1 changed, 0 removed, +2.1 MB" before anything goes out.

### 3b. Public viewer (frontend)

A second Vite entry point in the same `frontend/` project (`site.html` → `src/site/`), so the code stays shared:

| Page | Content |
|---|---|
| **Home / Explorer** | A big map with every public map as an outline or pin, and a side list of the maps in view. At the top: a **search box** (name, place, club, cartographer, event name; ignores accents and case) and filters (type, club, scale, survey year, has events). Zoomed in, the map images are drawn on the aerial photo, like the explorer in the app. |
| **Map page** | Overlay with opacity and base-layer switcher. Facts (scale, contours, survey date, cartographer, club). Timeline of versions → events → courses. Course images in a lightbox. Nearby maps. Credit line. |
| **Events** | Every event by year, with search, like the app's Events page. Links to results. |
| **About** | Who you are, what this is, copyright and credits, how to ask for a map to be removed. |

- The app also uses Svelte 5 and Leaflet, and only adds Leaflet and Svelte to the bundle.
- **Search:** for a few hundred maps, a simple accent-insensitive filter over a precomputed text field is instant. A library such as MiniSearch is only worth adding for fuzzy matching ("Brielmersen" → "Brielmeersen"). It is about 7 KB, so it can come later.
- Phone-friendly from the start: friends will open links from WhatsApp.

### 3c. Hosting and deploy

- **A separate public repo**, for example `rvanbruggen/orienteeringmaps-site`, served by GitHub Pages. Keeping the images out of this code repo keeps its history small, and the code repo stays free of map images.
- **Where publishing runs:** the data lives on the Docker host. The Docker image builds the viewer as well as the app. `cli publish` writes the export to `data/site-export/`. A short `publish.sh` on the host (or the Mac) syncs that into a checkout of the site repo, commits and pushes. Pages redeploys in about a minute.
- **Later:** a **Publish button** in the app that pushes directly, using a GitHub fine-grained token that can only write to the site repo. That saves the SSH step, but it puts a credential in the container, so it is a separate step.
- **GitHub Pages limits** are no problem at this size:
  - About 1 GB per site and 100 MB per file.
  - A soft limit of 100 GB/month bandwidth.
  - At about 0.5 MB per map, 500 maps is about 250 MB.
- An optional custom domain (for example `kaarten.example.be`) is one CNAME file.

## 4. Changes in the management app

- **Data model:** `Map.public` (off by default), plus optional `public_note` (text to show publicly, separate from your private notes) and `publish_level` (see §5).
- **Map page:** a "Public" switch with a preview link.
- **Library:** a "Published" column and filter, and bulk select → publish/unpublish.
- **Publish page:**
  - A checklist of warnings: public maps without a placement, without a club, or with "needs review".
  - The diff against the last publish, and a **local preview** of the public site (the app serves the export at `/site-preview/`).
  - A button to publish.

## 5. Things to get right before going public

1. **Map copyright.** Orienteering maps belong to the clubs and cartographers who made them, and many clubs don't want high-resolution copies of competition areas online. Areas used for an upcoming championship are sometimes embargoed. Proposal:
   - **Opt-in per map.** Nothing is public unless you switch it on.
   - Per map, a **publish level**:
     - *Outline only*: footprint and details, no image.
     - *Overlay*: reduced-resolution image on the aerial photo.
     - *Full*: also course pages, maybe the original PDF.
   - Permanent courses such as HITTA and Mapico are already public, so *Full* is fine for them.
   - A credit line on every map ("© club, drawn by cartographer"), and a removal contact on the About page.
   - It may be worth a quick word with the clubs involved for anything beyond permanent courses.
2. **Privacy.** Private `notes` never go out (allow-list). Keep LAN addresses and personal data out of the site repo, as for this repo.
3. **Base map terms.**
   - Digitaal Vlaanderen is open data, with attribution.
   - OSM tiles are fine for low traffic, with attribution.
   - Esri World Imagery's terms for public sites are less clear. Proposal: Flemish aerial photo as default, OSM second, and Esri only for maps outside Flanders.
4. **Search engines.** Choose between `noindex` (only people with the link find it) and indexable (friends can google it).

## 6. Optional extras (later)

1. **"Where am I" on the overlay:** the phone's GPS dot on the placed map. Very handy for HITTA/Mapico permanent courses in the field. It is only a few lines with Leaflet's `locate()`, because the site is HTTPS.
2. Per map: download KMZ (Google Earth) / GeoJSON.
3. Share previews: an Open Graph image per map, so a WhatsApp link shows a thumbnail. This needs a small static HTML page per map, which the export can generate.
4. Dutch / English toggle.
5. "Recently added" list and an RSS/Atom feed.

## 7. Phases

| Phase | Scope | Result |
|---|---|---|
| **P1: Export** | `Map.public` + publish level, `publish.py` with allow-listed JSON, downscaled hashed images, manifest; CLI command; tests that no private field leaks | `cli publish` produces a folder |
| **P2: Viewer** | `site.html` entry; Explorer with search and filters; map page with overlay; events; about; `readonly` mode for shared components; mobile layout | The folder opens as a working site (`vite preview`) |
| **P3: Deploy** | Site repo + GitHub Pages; `publish.sh`; Publish page in the app with diff and local preview | Public URL you can share |
| **P4: Extras** | Pick from §6 | — |

P1 and P2 can be tried entirely offline before anything is public.

## 8. Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | What to publish | Opt-in per map, with a publish level: private / outline / overlay / full |
| 2 | Resolution | Full-resolution images; PDF/original downloads at level *full* |
| 3 | Address | Repository `orienteeringmaps-public` → `https://<account>.github.io/orienteeringmaps-public/`; repository, branch and address can be changed on the Publish page |
| 4 | Language | English |
| 5 | Search engines | Indexable: a static HTML page per map, a sitemap and `robots.txt` |
| 6 | Publish trigger | In-app **Publish now** button; pushes with git using a fine-grained token in `OMAPS_GITHUB_TOKEN` |

### How it was built

- `backend/app/publish.py`: the export. Allow-listed JSON, images by content hash, a page per map, sitemap, robots.txt, and CNAME for a custom domain.
- `backend/app/github.py`: the publish run in a background thread. git fetch → sync → commit → push from `data/publish/repo`, then Pages is switched on through the API.
- `frontend/src/site/`: the viewer, built separately with `vite.site.config.js` into `frontend/dist-site/`. It reuses `ExplorerMap`, `OverlayMap`, `Lightbox`, `warp.js` and `basemaps.js`.
- The app's **Publish** page shows the preview (served at `/site-preview/`), pending changes, warnings, the GitHub status, settings and history.
