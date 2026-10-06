"""Public site export: a static website of the maps you chose to publish.

Every map has a publish level:

    private  not on the public site (the default)
    outline  details, events and courses, and where the map is (outline or pin); no images
    overlay  + the main map image, placed on the aerial photo when the map is placed
    full     + every page of every file (course prints too) and the original files to download

`build_site` turns the database into a dict {site path: bytes | Path}: the
viewer (frontend/dist-site), one JSON file with all public data, the images,
the originals (level "full"), and one small HTML page per map so that search
engines can index every map. Only fields named here are exported, so private
notes and new columns never leak by accident.
"""
import filecmp
import hashlib
import html
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__, config, processing, services
from . import models as m
from .kml import fmt_date, fmt_scale

LEVELS = ("private", "outline", "overlay", "full")

DEFAULT_SETTINGS: dict = {
    "site_title": "Orienteering maps",
    "site_description": "A collection of orienteering maps, placed on aerial photos.",
    "author": "",
    "contact": "",
    "about": "",
    "github_repo": "orienteeringmaps-public",  # "name" (owner = token's account) or "owner/name"
    "github_branch": "main",
    "site_url": "",  # empty = https://<owner>.github.io/<repo>/
    "github_login": "",  # cached from the token, to work out the site URL offline
}


def get_settings(db: Session) -> dict:
    out = dict(DEFAULT_SETTINGS)
    for row in db.scalars(select(m.Setting).where(m.Setting.key.in_(list(DEFAULT_SETTINGS)))):
        if row.value is not None:
            out[row.key] = row.value
    return out


def save_settings(db: Session, values: dict) -> dict:
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        row = db.get(m.Setting, key) or m.Setting(key=key)
        row.value = value.strip() if isinstance(value, str) else value
        db.add(row)
    db.commit()
    return get_settings(db)


def repo_full_name(settings: dict, login: str | None = None) -> str | None:
    repo = (settings.get("github_repo") or "").strip().strip("/")
    if not repo:
        return None
    if "/" in repo:
        return repo
    login = login or settings.get("github_login")
    return f"{login}/{repo}" if login else None


def site_url(settings: dict, login: str | None = None) -> str | None:
    """The public address, always ending in '/'."""
    if settings.get("site_url"):
        url = settings["site_url"].strip()
        return url if url.endswith("/") else url + "/"
    full = repo_full_name(settings, login)
    if not full:
        return None
    owner, name = full.split("/", 1)
    host = f"{owner.lower()}.github.io"
    return f"https://{host}/" if name.lower() == host else f"https://{host}/{name}/"


# ------------------------------------------------------------------ helpers --

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "map"


def _safe_filename(name: str) -> str:
    stem = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.") or "file"


def _sort_key(date: str | None) -> str:
    return date or ""


def _clean(d: dict) -> dict:
    """Drop empty values to keep the JSON small."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


@dataclass
class Site:
    files: dict[str, bytes | Path] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    data: dict = field(default_factory=dict)

    def add(self, path: str, src: bytes | Path) -> bool:
        if isinstance(src, Path) and not src.is_file():
            return False
        self.files[path] = src
        return True

    @property
    def size(self) -> int:
        return sum(len(v) if isinstance(v, bytes) else v.stat().st_size for v in self.files.values())


# -------------------------------------------------------------------- data --

def _page(site: Site, p: m.Page) -> dict | None:
    img, thumb = f"media/{p.image_name}", f"media/{p.thumb_name}"
    if not site.add(img, processing.derived_path(p.image_name)):
        return None
    site.add(thumb, processing.derived_path(p.thumb_name))
    d = {"no": p.page_no, "w": p.width, "h": p.height, "img": img, "thumb": thumb}
    if p.georef is not None:
        d["place"] = _clean({"corners": p.georef.corners, "clip": p.georef.clip})
    return d


def _hero_page(mp: m.Map) -> m.Page | None:
    """The page that represents a map: its main placed page, else the first page of the newest map file."""
    page = services.primary_page(mp)
    if page is not None:
        return page
    for v in sorted(mp.versions, key=lambda v: (_sort_key(v.survey_date), v.id), reverse=True):
        for f in sorted(v.files, key=lambda f: (f.kind not in ("map", "blank"), f.id)):
            if f.kind != "manual" and f.pages:
                return f.pages[0]
    return None


def _file(site: Site, f: m.File) -> dict:
    url = f"files/{f.sha256[:12]}/{_safe_filename(f.original_name)}"
    if not site.add(url, processing.original_path(f.stored_name)):
        url = None
    pages = [d for p in f.pages if (d := _page(site, p))]
    return _clean({"key": f.sha256[:12], "kind": f.kind, "name": f.original_name, "format": f.format,
                   "size": f.size_bytes, "url": url, "pages": pages})


def _map(site: Site, mp: m.Map) -> dict:
    level = mp.publish_level
    summary = services.map_summary(mp)
    latest = services.latest_version(mp)
    rec = {
        "id": mp.id, "slug": f"{mp.id}-{slugify(mp.name)}", "name": mp.name, "location": mp.location,
        "lat": mp.lat, "lon": mp.lon, "type": mp.map_type,
        "club": mp.club.name if mp.club else None, "club_url": mp.club.website if mp.club else None,
        "tags": mp.tags or [], "note": mp.public_note, "level": level,
        "scale": summary["scale"], "contours": summary["contour_interval"],
        "survey": summary["last_survey"], "last_event": summary["last_event"],
        "cartographer": latest.cartographer if latest else None,
        "footprint": summary["footprint"],
    }
    if level in ("overlay", "full") and (hero := _hero_page(mp)) is not None:
        page = _page(site, hero)
        if page:
            rec["hero"] = page
            rec["thumb"] = page["thumb"]
    files_ok = level == "full"
    versions = []
    for v in sorted(mp.versions, key=lambda v: (_sort_key(v.survey_date), v.id), reverse=True):
        events = []
        for e in sorted(v.events, key=lambda e: (_sort_key(e.date), e.id), reverse=True):
            courses = [_clean({
                "name": c.name, "length_km": c.length_km, "climb_m": c.climb_m, "scale": c.scale,
                "controls": c.controls,
                "file": c.file.sha256[:12] if files_ok and c.file is not None else None,
                "page": (c.page_no or 1) if files_ok and c.file is not None else None,
            }) for c in e.courses]
            events.append(_clean({
                "name": e.name, "date": e.date, "end_date": e.end_date, "type": e.event_type,
                "discipline": e.discipline, "organiser": e.organiser.name if e.organiser else None,
                "results_url": e.results_url, "courses": courses,
            }))
        versions.append(_clean({
            "label": v.label, "survey": v.survey_date, "cartographer": v.cartographer, "scale": v.scale,
            "contours": v.contour_interval, "standard": v.standard, "events": events,
            "files": [_file(site, f) for f in v.files] if files_ok else [],
        }))
    rec["versions"] = versions
    # Course files may live on another version of the same map: make sure they're exported.
    if files_ok:
        known = {f["key"] for v in versions for f in v.get("files", [])}
        extra = {}
        for v in mp.versions:
            for e in v.events:
                for c in e.courses:
                    if c.file is not None and c.file.sha256[:12] not in known:
                        extra[c.file.sha256[:12]] = c.file
        if extra:
            rec["extra_files"] = [_file(site, f) for f in extra.values()]
    return _clean(rec) | {"versions": versions}


def _warnings(mp: m.Map, rec: dict) -> list[str]:
    out = []
    if mp.needs_review:
        out.append("still marked “needs review”")
    if mp.publish_level in ("overlay", "full") and "hero" not in rec:
        out.append("has no map image to show")
    if mp.publish_level in ("overlay", "full") and not rec.get("footprint"):
        out.append("is not placed on the aerial photo")
    if not rec.get("footprint") and mp.lat is None:
        out.append("has no location, so it is not on the map")
    if mp.club is None:
        out.append("has no club for the copyright credit")
    return out


# -------------------------------------------------------------------- html --

def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _facts(mp: dict) -> str:
    return " · ".join(x for x in [
        mp.get("location"), mp.get("club"), fmt_scale(mp.get("scale")),
        f"surveyed {fmt_date(mp['survey'])}" if mp.get("survey") else None,
    ] if x)


def _map_description(mp: dict) -> str:
    n_events = sum(len(v.get("events", [])) for v in mp["versions"])
    parts = [f"Orienteering map {mp['name']}"]
    if mp.get("location"):
        parts[0] += f" near {mp['location']}"
    if (f := _facts({**mp, "location": None})):
        parts.append(f)
    if n_events:
        parts.append(f"{n_events} event{'s' if n_events != 1 else ''}")
    return ". ".join(parts) + "."


def _map_body(mp: dict) -> str:
    rows = []
    for v in mp["versions"]:
        for e in v.get("events", []):
            courses = ", ".join(c["name"] for c in e.get("courses", []))
            rows.append(f"<li>{_esc(e['name'])}{' – ' + _esc(fmt_date(e.get('date'))) if e.get('date') else ''}"
                        f"{' (' + _esc(courses) + ')' if courses else ''}</li>")
    name = _esc(mp["name"])
    img = f'<img src="{_esc(mp["thumb"])}" alt="Map {name}">' if mp.get("thumb") else ""
    note = f"<p>{_esc(mp['note'])}</p>" if mp.get("note") else ""
    events = "<h2>Events</h2><ul>" + "".join(rows) + "</ul>" if rows else ""
    return (f'<article class="prerender"><p><a href="./">All maps</a></p><h1>{name}</h1>'
            f"<p>{_esc(_facts(mp))}</p>{note}{img}{events}</article>")


def _index_body(settings: dict, maps: list[dict]) -> str:
    items = "".join(f'<li><a href="map/{_esc(x["slug"])}/">{_esc(x["name"])}</a> {_esc(_facts(x))}</li>' for x in maps)
    return (f'<article class="prerender"><h1>{_esc(settings["site_title"])}</h1>'
            f'<p>{_esc(settings["site_description"])}</p><ul>{items}</ul>'
            f'<p><a href="events/">Events</a> · <a href="about/">About</a></p></article>')


def _render(template: str, *, base: str, url: str, title: str, description: str, data_path: str,
            body: str, image: str | None = None, noindex: bool = False) -> bytes:
    head = [
        f'<base href="{_esc(base)}">',
        f'<meta name="description" content="{_esc(description)}">',
        f'<meta name="omaps-data" content="{_esc(data_path)}">',
        '<link rel="icon" type="image/svg+xml" href="favicon.svg">',
        f'<meta property="og:title" content="{_esc(title)}">',
        f'<meta property="og:description" content="{_esc(description)}">',
        '<meta property="og:type" content="website">',
    ]
    if noindex:
        head.append('<meta name="robots" content="noindex">')
    else:
        head += [f'<link rel="canonical" href="{_esc(url)}">', f'<meta property="og:url" content="{_esc(url)}">']
    if image:
        head.append(f'<meta property="og:image" content="{_esc(image)}">')
    out = template.replace("<head>", "<head>\n    " + "\n    ".join(head), 1)
    out = re.sub(r"<title>.*?</title>", f"<title>{_esc(title)}</title>", out, count=1, flags=re.S)
    out = out.replace('<div id="app"></div>', f'<div id="app">{body}</div>', 1)
    return out.encode()


# -------------------------------------------------------------------- site --

def load_public_maps(db: Session) -> list[m.Map]:
    return db.scalars(select(m.Map).where(m.Map.publish_level != "private")
                      .options(*services.MAP_LOAD).order_by(m.Map.name)).all()


def build_site(db: Session, settings: dict, url: str, *, base: str | None = None) -> Site:
    """Everything the public site needs. `url` is the public address (ending in '/'),
    `base` the path the site is served under (defaults to the path of `url`)."""
    dist = config.SITE_DIST
    template_path = dist / "site.html"
    if not template_path.is_file():
        raise FileNotFoundError(f"Public site viewer not built: {template_path} is missing (run npm run build)")
    template = template_path.read_text()
    base = base or (urlparse(url).path or "/")
    site = Site()

    maps = []
    public = load_public_maps(db)
    # "Last updated" = the newest change to a public map, so an unchanged library gives identical files.
    updated = max((mp.updated_at for mp in public), default=None)
    for mp in public:
        rec = _map(site, mp)
        maps.append(rec)
        if (w := _warnings(mp, rec)):
            site.warnings.append({"map_id": mp.id, "name": mp.name, "level": mp.publish_level, "issues": w})
    site.counts = {lvl: sum(1 for x in maps if x["level"] == lvl) for lvl in LEVELS[1:]}

    site.data = {
        "site": _clean({
            "title": settings["site_title"], "description": settings["site_description"],
            "author": settings["author"], "contact": settings["contact"], "about": settings["about"],
            "url": url, "generated": updated.date().isoformat() if updated else None,
            # Removal requests go to the site repository's issues.
            "issues_url": f"https://github.com/{full}/issues" if (full := repo_full_name(settings)) else None,
            "app_version": __version__,
        }),
        "maps": maps,
    }
    data = json.dumps(site.data, ensure_ascii=False, separators=(",", ":")).encode()
    data_path = f"data/site-{hashlib.sha256(data).hexdigest()[:12]}.json"
    site.add(data_path, data)

    # The viewer itself.
    for f in (dist / "assets").rglob("*"):
        if f.is_file():
            site.add(f"assets/{f.relative_to(dist / 'assets').as_posix()}", f)
    site.add("favicon.svg", dist / "favicon.svg")
    site.add(".nojekyll", b"")

    title = settings["site_title"]
    common = dict(base=base, data_path=data_path)
    pages = {
        "": (title, settings["site_description"], _index_body(settings, maps)),
        "events/": (f"Events – {title}", f"Every event on the maps of {title}.",
                    '<article class="prerender"><h1>Events</h1><p><a href="./">All maps</a></p></article>'),
        "about/": (f"About – {title}", f"About {title}.",
                   f'<article class="prerender"><h1>About</h1><p>{_esc(settings["about"])}</p></article>'),
    }
    for path, (t, d, body) in pages.items():
        site.add(f"{path}index.html", _render(template, url=url + path, title=t, description=d, body=body, **common))
    for rec in maps:
        path = f"map/{rec['slug']}/"
        image = url + rec["thumb"] if rec.get("thumb") else None
        site.add(f"{path}index.html", _render(template, url=url + path, title=f"{rec['name']} – {title}",
                                              description=_map_description(rec), body=_map_body(rec),
                                              image=image, **common))
    site.add("404.html", _render(template, url=url, title=f"Not found – {title}", description=title,
                                 body="", noindex=True, **common))

    # Search engines.
    locs = ["", "events/", "about/"] + [f"map/{x['slug']}/" for x in maps]
    sitemap = "".join(f"<url><loc>{_esc(url + p)}</loc></url>" for p in locs)
    site.add("sitemap.xml", ('<?xml version="1.0" encoding="UTF-8"?>\n'
                             f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sitemap}</urlset>\n').encode())
    site.add("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {url}sitemap.xml\n".encode())
    host = urlparse(url).hostname or ""
    if host and not host.endswith("github.io") and host not in ("localhost", "127.0.0.1"):
        site.add("CNAME", f"{host}\n".encode())
    return site


# ------------------------------------------------------------- write / diff --

def _same(dest: Path, src: bytes | Path, path: str) -> bool:
    if not dest.is_file():
        return False
    if isinstance(src, bytes):
        return dest.stat().st_size == len(src) and dest.read_bytes() == src
    if dest.stat().st_size != src.stat().st_size:
        return False
    # Images and originals are named by content hash: same name + size = same file.
    return path.startswith(("media/", "files/", "assets/")) or filecmp.cmp(dest, src, shallow=False)


def sync_dir(target: Path, files: dict[str, bytes | Path], *, dry_run: bool = False, keep=(".git",)) -> dict:
    """Make `target` contain exactly `files`. Returns what changed (also for a dry run)."""
    added, changed, removed, bytes_new = [], [], [], 0
    for path, src in files.items():
        dest = target / path
        if _same(dest, src, path):
            continue
        (changed if dest.exists() else added).append(path)
        bytes_new += len(src) if isinstance(src, bytes) else src.stat().st_size
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(src, bytes):
                dest.write_bytes(src)
            else:
                shutil.copyfile(src, dest)
    if target.exists():
        for f in sorted(target.rglob("*")):
            rel = f.relative_to(target).as_posix()
            if rel.split("/")[0] in keep or not f.is_file() or rel in files:
                continue
            removed.append(rel)
            if not dry_run:
                f.unlink()
        if not dry_run:
            for d in sorted((p for p in target.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                if d.relative_to(target).parts[0] not in keep and not any(d.iterdir()):
                    d.rmdir()
    return {"added": len(added), "changed": len(changed), "removed": len(removed), "bytes": bytes_new,
            "paths": {"added": added[:50], "changed": changed[:50], "removed": removed[:50]}}
