"""Command line tools.

    python -m app.cli import <dir> [--no-group]
        Ingest every PDF/image in <dir>. Unless --no-group is given, files that
        look like courses on the same map (e.g. "...-Kort.pdf" / "...-Lang.pdf")
        are combined into one map with one version, one event and a course per
        file. Created maps are flagged "needs review".

    python -m app.cli rerender
        Rebuild all page images and thumbnails from the stored originals.
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select

from . import db, processing
from . import models as m
from .ingest import ingest_path
from .services import find_club_by_name
from .suggest import group_key


def _most_common(values, prefer_larger=False):
    values = [v for v in values if v is not None]
    if not values:
        return None
    counts = Counter(values)
    best = max(counts.values())
    tied = [v for v, c in counts.items() if c == best]
    return max(tied) if prefer_larger else tied[0]


def _club(session, name: str) -> m.Club:
    club = find_club_by_name(session, name)
    if club is None:
        club = m.Club(name=name, short_name=name if name.isupper() and len(name) <= 8 else None)
        session.add(club)
        session.flush()
    return club


def _create_map_from_group(session, files: list[m.File]) -> m.Map:
    sugg = [f.suggestions or {} for f in files]
    name = sugg[0].get("name") or Path(files[0].original_name).stem
    locations = [s.get("location") for s in sugg if s.get("location")]
    location = next((loc for loc in locations if loc != name), locations[0] if locations else None)
    tags = sorted({t for s in sugg for t in s.get("tags", [])})
    clubs = [c for s in sugg for c in s.get("clubs", [])]

    mp = m.Map(name=name, location=location, map_type=_most_common([s.get("map_type") for s in sugg]),
               tags=tags, needs_review=1,
               club_id=_club(session, clubs[0]).id if clubs else None)
    version = m.MapVersion(
        label=_most_common([s.get("label") for s in sugg]),
        scale=_most_common([s.get("scale") for s in sugg], prefer_larger=True),
        contour_interval=_most_common([s.get("contour_interval") for s in sugg]),
        survey_date=_most_common([s.get("survey_date") for s in sugg]),
        cartographer=_most_common([s.get("cartographer") for s in sugg]),
    )
    mp.versions.append(version)
    session.add(mp)
    session.flush()

    course_files = [(f, s["course"]) for f, s in zip(files, sugg) if s.get("course")]
    if course_files:
        series = next((t for t in tags if t != "Oriëntatieparcours"), None)
        ev = m.Event(map_version_id=version.id, name=f"{series} {name}" if series else name,
                     event_type="permanent" if mp.map_type == "permanent" else None,
                     organiser_club_id=mp.club_id)
        for f, c in course_files:
            course_scale = c.get("scale") if c.get("scale") != version.scale else None
            ev.courses.append(m.Course(name=c["name"], length_km=c.get("length_km"), scale=course_scale,
                                       file_id=f.id))
            f.kind = "course"
        session.add(ev)
    for f in files:
        f.map_version_id = version.id
    return mp


def cmd_import(args) -> int:
    root = Path(args.dir)
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in processing.SUPPORTED_EXTENSIONS)
    if not paths:
        print(f"No PDF or image files found in {root}")
        return 1
    created: list[int] = []
    with db.SessionLocal() as session:
        for p in paths:
            res = ingest_path(session, p, p.name)
            extra = f" ({res.error})" if res.error else ""
            print(f"  {res.status:9} {p.name}{extra}")
            if res.status == "created" and res.file:
                created.append(res.file.id)

        if args.group and created:
            groups: dict[str, list[m.File]] = defaultdict(list)
            for f in session.scalars(select(m.File).where(m.File.id.in_(created)).order_by(m.File.original_name)):
                if f.kind == "manual":
                    continue  # manuals stay in the inbox until you attach them
                groups[group_key(f.original_name)].append(f)
            for files in groups.values():
                mp = _create_map_from_group(session, files)
                print(f"  map      {mp.name}: {len(files)} file(s)")
            session.commit()
    print(f"Imported {len(created)} new file(s) from {len(paths)} found.")
    return 0


def cmd_rerender(_args) -> int:
    with db.SessionLocal() as session:
        for f in session.scalars(select(m.File)):
            processing.delete_derived(f.sha256)
            pf = processing.render_pages(f.stored_name, f.format, f.sha256, ocr=False)
            by_no = {p.page_no: p for p in pf.pages}
            for page in f.pages:
                if (r := by_no.get(page.page_no)):
                    page.image_name, page.thumb_name, page.width, page.height = (
                        r.image_name, r.thumb_name, r.width, r.height)
            print(f"  rendered {f.original_name}")
        session.commit()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import", help="bulk import a folder of PDFs/images")
    p_imp.add_argument("dir")
    p_imp.add_argument("--no-group", dest="group", action="store_false",
                       help="leave all files in the inbox instead of creating maps")
    p_imp.set_defaults(func=cmd_import)
    sub.add_parser("rerender", help="rebuild page images from the originals").set_defaults(func=cmd_rerender)
    args = parser.parse_args(argv)
    db.init_db()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
