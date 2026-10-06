"""Turning an uploaded PDF or image into stored originals, page images and text.

Originals are stored byte-for-byte under ORIGINALS_DIR, named by their
SHA-256. Everything under DERIVED_DIR (page renders, thumbnails) can be
rebuilt from the originals with `render_pages()`.
"""
import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
import imagehash
from PIL import ExifTags, Image, ImageOps

from . import config

log = logging.getLogger(__name__)

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # pragma: no cover - HEIC support is optional
    pass

Image.MAX_IMAGE_PIXELS = 300_000_000  # large scans are legitimate here

IMAGE_FORMATS = {
    ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".tif": "tif", ".tiff": "tif",
    ".webp": "webp", ".heic": "heic", ".heif": "heic", ".gif": "gif", ".bmp": "bmp",
}
SUPPORTED_EXTENSIONS = {".pdf", *IMAGE_FORMATS}


class UnsupportedFile(ValueError):
    pass


@dataclass
class RenderedPage:
    page_no: int
    width: int
    height: int
    image_name: str
    thumb_name: str
    text: str | None


@dataclass
class ProcessedFile:
    sha256: str
    format: str
    stored_name: str
    size_bytes: int
    page_count: int
    pages: list[RenderedPage] = field(default_factory=list)
    text: str | None = None
    text_source: str | None = None
    phash: str | None = None
    exif_lat: float | None = None
    exif_lon: float | None = None


def detect_format(filename: str, head: bytes) -> str:
    if head.startswith(b"%PDF"):
        return "pdf"
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_FORMATS:
        return IMAGE_FORMATS[ext]
    raise UnsupportedFile(f"Unsupported file type: {filename}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def original_path(stored_name: str) -> Path:
    return config.ORIGINALS_DIR / stored_name


def derived_path(name: str) -> Path:
    return config.DERIVED_DIR / name


def store_original(tmp_path: Path, filename: str) -> tuple[str, str, str, int]:
    """Move an upload into ORIGINALS_DIR. Returns (sha256, format, stored_name, size)."""
    with tmp_path.open("rb") as f:
        head = f.read(8)
    fmt = detect_format(filename, head)
    digest = sha256_of(tmp_path)
    stored_name = f"{digest[:2]}/{digest}.{fmt}"
    dest = original_path(stored_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.move(str(tmp_path), dest)
    return digest, fmt, stored_name, dest.stat().st_size


# ---------------------------------------------------------------- rendering --

def _save_page_images(img: Image.Image, digest: str, page_no: int) -> tuple[str, str, int, int]:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    if max(img.size) > config.MAX_IMAGE_PX:
        img = img.copy()
        img.thumbnail((config.MAX_IMAGE_PX, config.MAX_IMAGE_PX), Image.LANCZOS)
    base = f"{digest[:2]}/{digest}"
    image_name = f"{base}/p{page_no}.webp"
    thumb_name = f"{base}/p{page_no}.thumb.webp"
    derived_path(image_name).parent.mkdir(parents=True, exist_ok=True)
    img.save(derived_path(image_name), "WEBP", quality=92, method=4)
    thumb = img.copy()
    thumb.thumbnail((config.THUMB_PX, config.THUMB_PX), Image.LANCZOS)
    thumb.save(derived_path(thumb_name), "WEBP", quality=85)
    return image_name, thumb_name, img.width, img.height


def _ocr(img: Image.Image) -> str | None:
    if not shutil.which("tesseract"):
        return None
    try:
        import pytesseract
        langs = config.OCR_LANGS
        available = set(pytesseract.get_languages(config=""))
        langs = "+".join(l for l in langs.split("+") if l in available) or "eng"
        small = img.convert("L")
        if max(small.size) > 4000:
            small.thumbnail((4000, 4000), Image.LANCZOS)
        return pytesseract.image_to_string(small, lang=langs, timeout=120) or None
    except Exception as exc:  # OCR is best effort
        log.warning("OCR failed: %s", exc)
        return None


def _exif_gps(img: Image.Image) -> tuple[float | None, float | None]:
    try:
        gps = img.getexif().get_ifd(ExifTags.IFD.GPSInfo)
        if not gps or 2 not in gps or 4 not in gps:
            return None, None

        def to_deg(v) -> float:
            d, m, s = (float(x) for x in v)
            return d + m / 60 + s / 3600

        lat, lon = to_deg(gps[2]), to_deg(gps[4])
        if gps.get(1) == "S":
            lat = -lat
        if gps.get(3) == "W":
            lon = -lon
        return round(lat, 7), round(lon, 7)
    except Exception:
        return None, None


def render_pages(stored_name: str, fmt: str, digest: str, *, ocr: bool = True) -> ProcessedFile:
    """Render page images and extract text for a stored original."""
    src = original_path(stored_name)
    result = ProcessedFile(sha256=digest, format=fmt, stored_name=stored_name,
                           size_bytes=src.stat().st_size, page_count=1)
    first_img: Image.Image | None = None

    if fmt == "pdf":
        with fitz.open(src) as doc:
            result.page_count = doc.page_count
            texts = []
            zoom = config.PDF_DPI / 72
            for i, page in enumerate(doc, start=1):
                # Cap the zoom so very large pages stay within MAX_IMAGE_PX.
                longest_pt = max(page.rect.width, page.rect.height)
                z = min(zoom, config.MAX_IMAGE_PX / longest_pt)
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                if i == 1:
                    first_img = img
                text = page.get_text().strip() or None
                texts.append(text or "")
                names = _save_page_images(img, digest, i)
                result.pages.append(RenderedPage(i, names[2], names[3], names[0], names[1], text))
            joined = "\n".join(texts).strip()
            if joined:
                result.text, result.text_source = joined[:200_000], "pdf"
            elif ocr and first_img is not None:
                # Text drawn as outlines (e.g. some OCAD exports): fall back to OCR.
                if t := _ocr(first_img):
                    result.text, result.text_source = t, "ocr"
                    result.pages[0].text = t
    else:
        with Image.open(src) as raw:
            result.exif_lat, result.exif_lon = _exif_gps(raw)
            img = ImageOps.exif_transpose(raw)
            img.load()
        first_img = img
        text = _ocr(img) if ocr else None
        names = _save_page_images(img, digest, 1)
        result.pages.append(RenderedPage(1, names[2], names[3], names[0], names[1], text))
        if text:
            result.text, result.text_source = text, "ocr"

    if first_img is not None:
        result.phash = str(imagehash.phash(first_img))
    return result


def delete_derived(digest: str) -> None:
    shutil.rmtree(derived_path(f"{digest[:2]}/{digest}"), ignore_errors=True)


def delete_original(stored_name: str) -> None:
    original_path(stored_name).unlink(missing_ok=True)


def phash_distance(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)
