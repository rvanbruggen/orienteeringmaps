"""Guess map metadata from a file name and the text found on the map.

Everything returned here is a *suggestion*: the UI pre-fills forms with it
and the user confirms. Text comes from the PDF text layer or from OCR, and
is mostly Dutch, with English and French fallbacks.
"""
import re

MONTHS = {
    # nl
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7,
    "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
    # en
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "august": 8,
    "october": 10,
    # fr
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # short forms
    "jan": 1, "feb": 2, "fév": 2, "mrt": 3, "mar": 3, "apr": 4, "avr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "okt": 10, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

# Known series of permanent courses: (filename/text pattern, tag, map type)
SERIES = [
    (re.compile(r"\bhitta\b", re.I), "HITTA", "permanent"),
    (re.compile(r"\bmapico\b", re.I), "Mapico", "permanent"),
    (re.compile(r"ori[eë]ntatie\s*parcours|orientatieparcours", re.I), "Oriëntatieparcours", "permanent"),
]

# Words in file names that say nothing about the map itself.
NOISE_WORDS = {
    "hitta", "routes", "route", "ov", "mapico", "kaart", "kaarten", "map", "maps", "carte",
    "baanlegging", "blanco", "orientatieparcours", "oriëntatieparcours", "pdf", "final", "def",
    "all", "print", "handleiding", "manual",
}
COURSE_WORDS = {"kort": "Kort", "lang": "Lang", "short": "Short", "long": "Long", "middel": "Middel"}
MANUAL_RE = re.compile(r"handleiding|manual|instructies|instructions|uitleg|mode d'emploi", re.I)

SCALE_KW_RE = re.compile(
    r"(?:schaal|scale|[ée]chelle|ma(?:ß|ss)stab)\s*[:.]?\s*1\s*[:/]\s*(\d{1,2}(?:[.\s ]?\d{3}))", re.I
)
SCALE_BARE_RE = re.compile(r"(?<![\d/])1\s*[:/]\s*(\d{1,2}[.\s ]?\d{3})(?![\d])")
CONTOUR_RE = re.compile(
    r"(?:hoogtelijnen|hoogtelijn|hoogte|equidistan\w*|[ée]quidistance|contours?(?:\s+interval)?|"
    r"contour\s+interval|courbes?|[äa]quidistanz)\s*[:.]?\s*(\d+(?:[.,]\d+)?)\s*(?:m\b|meter|metre|mètre)",
    re.I,
)
SURVEY_RE = re.compile(
    r"(?:kaart|kartering|terreinopname|survey(?:ed)?|map(?:ped)?|lev[ée]|relev[ée]|update|herziening|revisie)"
    r"[ \t]*[:.]?[ \t]*(?:(\d{1,2})[ \t/.-]+)?(?:([a-zéû]{3,10})\.?[ \t/.-]*|(\d{1,2})[/.-])?((?:19|20)\d{2})\b",
    re.I,
)
CARTO_RE = re.compile(
    r"(?i:tekening|getekend door|kartograaf|cartograaf|cartographer|drawn by|mapper|kartering|survey)"
    r"[ \t]*[:.]?[ \t]*((?:[A-ZÀ-Ý][\w'\-]+)(?:[ \t]+(?:van|de|der|den|le|la|[A-ZÀ-Ý][\w'\-]+)){1,3})",
)
CLUB_RE = re.compile(
    r"orienteering\s*clubs?\s+(.+?)\s+(?:is|zijn)\s+hier\s+actief", re.I | re.S
)
LOCATION_RE = re.compile(r"\b(?:door|in)\s+(?:het\s+|de\s+)?[\w\s'-]{0,40}?\bin\s+([A-Z][\w'-]+(?:[ -][A-Z][\w'-]+)?)\s*!")
LENGTH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*km\b", re.I)


def _int_scale(raw: str) -> int | None:
    n = int(re.sub(r"\D", "", raw))
    return n if 500 <= n <= 50000 else None


def find_scale(text: str) -> int | None:
    for rx in (SCALE_KW_RE, SCALE_BARE_RE):
        for m in rx.finditer(text):
            if (n := _int_scale(m.group(1))) is not None:
                return n
    return None


def find_contour(text: str) -> float | None:
    for m in CONTOUR_RE.finditer(text):
        v = float(m.group(1).replace(",", "."))
        if 0.5 <= v <= 25:
            return v
    return None


def find_survey_date(text: str) -> str | None:
    for m in SURVEY_RE.finditer(text):
        num1, month_word, num2, year = m.groups()
        day = month = None
        if month_word:
            month = MONTHS.get(month_word.lower())
            if not month:
                continue  # some other word between keyword and year
            day = num1
        elif num2:
            day, month = num1, int(num2)
        elif num1:
            month = int(num1)  # "03/2015"
        if month and not 1 <= month <= 12:
            continue
        if month and day and 1 <= int(day) <= 31:
            return f"{year}-{month:02d}-{int(day):02d}"
        if month:
            return f"{year}-{month:02d}"
        return year
    return None


def find_cartographer(text: str) -> str | None:
    m = CARTO_RE.search(text)
    return m.group(1).strip() if m else None


def find_clubs(text: str) -> list[str]:
    m = CLUB_RE.search(text)
    if not m:
        return []
    raw = re.sub(r"\s+", " ", m.group(1))
    return [c.strip() for c in re.split(r",|\s+en\s+|\s+and\s+|\s+et\s+|&", raw) if c.strip()]


def find_length_km(text: str) -> float | None:
    m = re.search(r"omloop is\s+(\d+(?:[.,]\d+)?)\s*km", text, re.I) or LENGTH_RE.search(text)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v if 0.3 <= v <= 60 else None


def parse_filename(filename: str) -> dict:
    """Split a file name into a map name, an optional course name and series tags."""
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename)
    tags, map_type = [], None
    for rx, tag, mtype in SERIES:
        if rx.search(stem):
            tags.append(tag)
            map_type = map_type or mtype
    # Split on separators and on CamelCase ("HandleidingMapicoGuldenKamer").
    spaced = re.sub(r"(?<=[a-zà-ÿ])(?=[A-Z][a-zà-ÿ])", " ", stem)
    words = [w for w in re.split(r"[\s_\-]+", spaced) if w]
    course = None
    if words and words[-1].lower() in COURSE_WORDS:
        course = COURSE_WORDS[words.pop().lower()]
    kept = [w for w in words if w.lower() not in NOISE_WORDS]
    # Drop trailing version-like tokens ("3.1", "v2") but keep them in a label.
    label = None
    while kept and re.fullmatch(r"v?\d+(?:\.\d+)*", kept[-1], re.I):
        label = kept.pop()
    name = " ".join(w if not w.isupper() or len(w) <= 3 else w.title() for w in kept) or stem
    return {"name": name, "course": course, "tags": tags, "map_type": map_type, "label": label}


def group_key(filename: str) -> str:
    """Files that share this key are probably courses printed on the same map."""
    p = parse_filename(filename)
    return re.sub(r"[^a-z0-9]", "", p["name"].lower())


def suggest(filename: str, text: str | None, page_count: int = 1) -> dict:
    text = text or ""
    fn = parse_filename(filename)
    out: dict = {
        "name": fn["name"],
        "tags": list(fn["tags"]),
        "map_type": fn["map_type"],
        "kind": "manual" if MANUAL_RE.search(filename) or MANUAL_RE.search(text[:300]) else "map",
    }
    for rx, tag, mtype in SERIES:
        if rx.search(text[:2000]) and tag not in out["tags"]:
            out["tags"].append(tag)
            out["map_type"] = out["map_type"] or mtype
    if fn["label"]:
        out["label"] = fn["label"]
    if (v := find_scale(text)) is not None:
        out["scale"] = v
    if (v := find_contour(text)) is not None:
        out["contour_interval"] = v
    if (v := find_survey_date(text)):
        out["survey_date"] = v
    if (v := find_cartographer(text)):
        out["cartographer"] = v
    if m := LOCATION_RE.search(text):
        out["location"] = m.group(1)
    elif "HITTA" in out["tags"]:
        out["location"] = fn["name"]
    if (v := find_clubs(text)):
        out["clubs"] = v
    if fn["course"]:
        out["course"] = {"name": fn["course"]}
        if "scale" in out:
            out["course"]["scale"] = out["scale"]
        if (v := find_length_km(text)) is not None:
            out["course"]["length_km"] = v
    if page_count > 1 and out["kind"] == "map":
        out["multi_page"] = True  # probably one course per page
    return out
