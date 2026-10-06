"""KMZ (Google Earth) and GeoJSON export of placed maps.

Each placed page becomes a GroundOverlay with a gx:LatLonQuad, which Google
Earth (web, desktop and mobile) drapes exactly over its four corners, so
rotated and perspective fits survive. Pages with an outline get a PNG with
everything outside the outline transparent.
"""
import io
import zipfile
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

from . import processing, services
from . import models as m

MAX_PX = 4096  # Google Earth handles larger, but this keeps files small and fast


def _image_bytes(page: m.Page) -> tuple[bytes, str]:
    with Image.open(processing.derived_path(page.image_name)) as im:
        im = im.convert("RGB")
        k = min(1.0, MAX_PX / max(im.size))
        if k < 1:
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        buf = io.BytesIO()
        clip = page.georef.clip
        if clip and len(clip) >= 3:
            sx, sy = im.width / page.width, im.height / page.height
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).polygon([(x * sx, y * sy) for x, y in clip], fill=255)
            im.putalpha(mask)
            # Orienteering maps use few colours: a 256-colour palette keeps them crisp at ~1/4 the size.
            im.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(buf, "PNG", optimize=True)
            return buf.getvalue(), "png"
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue(), "jpg"


def _coord(lat: float, lon: float) -> str:
    return f"{lon:.7f},{lat:.7f}"


def _centroid(points: list[list[float]]) -> tuple[float, float]:
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fmt_date(d: str) -> str:
    y, *rest = d.split("-")
    if not rest:
        return y
    month = MONTHS[int(rest[0]) - 1]
    return f"{int(rest[1])} {month} {y}" if len(rest) > 1 else f"{month} {y}"


def fmt_scale(n: int | None) -> str | None:
    return f"1:{n:,}".replace(",", " ") if n else None


def _description(mp: m.Map, summary: dict) -> str:
    parts = [mp.location, summary.get("club_name"), fmt_scale(summary.get("scale")),
             f"survey {fmt_date(summary['last_survey'])}" if summary.get("last_survey") else None,
             f"last event {fmt_date(summary['last_event'])}" if summary.get("last_event") else None]
    return " · ".join(p for p in parts if p)


def build_kmz(title: str, items: list[tuple[m.Map, list[m.Page]]]) -> bytes:
    """items: (map, placed pages to include). Maps without pages but with a location become pins."""
    buf = io.BytesIO()
    folders = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for mp, pages in items:
            summary = services.map_summary(mp)
            desc = escape(_description(mp, summary))
            parts = [f"<Folder><name>{escape(mp.name)}</name><description>{desc}</description>"]
            for page in pages:
                data, ext = _image_bytes(page)
                href = f"files/{mp.id}-{page.id}.{ext}"
                z.writestr(href, data, compress_type=zipfile.ZIP_STORED)
                tl, tr, br, bl = page.georef.corners
                label = page.file.original_name + (f" p{page.page_no}" if page.file.page_count > 1 else "")
                parts.append(
                    f"<GroundOverlay><name>{escape(label)}</name><Icon><href>{href}</href></Icon>"
                    f"<gx:LatLonQuad><coordinates>{_coord(*bl)} {_coord(*br)} {_coord(*tr)} {_coord(*tl)}"
                    f"</coordinates></gx:LatLonQuad></GroundOverlay>")
            if pages:
                lat, lon = _centroid(services.footprint(pages[0]))
            elif mp.lat is not None:
                lat, lon = mp.lat, mp.lon
            else:
                continue
            parts.append(f"<Placemark><name>{escape(mp.name)}</name><description>{desc}</description>"
                         f"<Point><coordinates>{_coord(lat, lon)}</coordinates></Point></Placemark>")
            parts.append("</Folder>")
            folders.append("".join(parts))
        kml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">'
               f"<Document><name>{escape(title)}</name>{''.join(folders)}</Document></kml>")
        z.writestr("doc.kml", kml)
    return buf.getvalue()


def build_geojson(maps: list[m.Map]) -> dict:
    features = []
    for mp in maps:
        summary = services.map_summary(mp)
        props = {k: summary.get(k) for k in ("id", "name", "location", "map_type", "club_name", "scale",
                                             "contour_interval", "last_survey", "last_event", "tags")}
        if summary["footprint"]:
            ring = [[lon, lat] for lat, lon in summary["footprint"]]
            ring.append(ring[0])
            geom = {"type": "Polygon", "coordinates": [ring]}
        elif mp.lat is not None:
            geom = {"type": "Point", "coordinates": [mp.lon, mp.lat]}
        else:
            continue
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}

