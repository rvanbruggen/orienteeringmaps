"""Request and response shapes for the JSON API."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

PARTIAL_DATE = r"^\d{4}(-\d{2}(-\d{2})?)?$"

MAP_TYPES = ["forest", "park", "sprint", "urban", "school", "permanent", "mtbo", "ski", "other"]
FILE_KINDS = ["map", "course", "blank", "control_descriptions", "result_card", "manual", "other"]
EVENT_TYPES = ["race", "training", "permanent", "school", "championship", "relay", "other"]
DISCIPLINES = ["sprint", "middle", "long", "relay", "score", "night", "ultra", "knock-out", "other"]
PUBLISH_LEVELS = ["private", "outline", "overlay", "full"]
STANDARDS = ["ISOM 2017-2", "ISOM 2000", "ISSprOM 2019-2", "ISSOM 2007", "ISMTBOM", "ISSkiOM", "other"]


def _blank_to_none(v):
    return None if isinstance(v, str) and not v.strip() else v


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return _blank_to_none(v)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------- clubs --

class ClubIn(_In):
    name: str | None = None
    short_name: str | None = None
    federation: str | None = None
    website: str | None = None
    notes: str | None = None


class ClubOut(_Out):
    id: int
    name: str
    short_name: str | None
    federation: str | None
    website: str | None
    notes: str | None
    map_count: int = 0


# ------------------------------------------------------------------- files --

class GeorefSummary(BaseModel):
    method: str
    corners: list[list[float]]
    clip: list[list[float]] | None
    rms_m: float | None
    scale: float | None
    rotation_deg: float | None
    point_count: int
    updated_at: datetime


class PageOut(_Out):
    id: int
    page_no: int
    width: int
    height: int
    dpi: float | None = None
    image_url: str
    thumb_url: str
    georef: GeorefSummary | None = None


class FileOut(_Out):
    id: int
    map_version_id: int | None
    map_id: int | None = None
    map_name: str | None = None
    kind: str
    original_name: str
    format: str
    size_bytes: int
    page_count: int
    text_source: str | None
    exif_lat: float | None
    exif_lon: float | None
    suggestions: dict
    notes: str | None
    source: str | None = None
    created_at: datetime
    original_url: str
    thumb_url: str | None
    pages: list[PageOut] = []


class FileUpdate(_In):
    map_version_id: int | None = None
    kind: str | None = None
    notes: str | None = None


class SimilarFile(BaseModel):
    file_id: int
    original_name: str
    distance: int
    map_id: int | None
    map_name: str | None


class UploadResult(BaseModel):
    original_name: str
    status: str  # created | duplicate | error
    error: str | None = None
    file: FileOut | None = None
    similar: list[SimilarFile] = []
    candidate_maps: list[dict] = []


# ----------------------------------------------------------------- courses --

class CourseIn(_In):
    name: str | None = None
    length_km: float | None = Field(None, ge=0)
    climb_m: int | None = Field(None, ge=0)
    scale: int | None = Field(None, ge=100)
    controls: int | None = Field(None, ge=0)
    file_id: int | None = None
    page_no: int | None = Field(None, ge=1)
    notes: str | None = None


class CourseOut(_Out):
    id: int
    event_id: int
    name: str
    length_km: float | None
    climb_m: int | None
    scale: int | None
    controls: int | None
    file_id: int | None
    page_no: int | None
    notes: str | None
    control_coords: list[list[float]] | None = None  # start, controls, finish as [lat, lon]
    thumb_url: str | None = None


# ------------------------------------------------------------------ events --

class EventIn(_In):
    name: str | None = None
    date: str | None = Field(None, pattern=PARTIAL_DATE)
    end_date: str | None = Field(None, pattern=PARTIAL_DATE)
    event_type: str | None = None
    discipline: str | None = None
    organiser_club_id: int | None = None
    results_url: str | None = None
    notes: str | None = None


class EventOut(_Out):
    id: int
    map_version_id: int
    name: str
    date: str | None
    end_date: str | None
    event_type: str | None
    discipline: str | None
    organiser_club_id: int | None
    organiser_name: str | None = None
    results_url: str | None
    notes: str | None
    courses: list[CourseOut] = []
    participations: list[dict] = []  # your runs of this event (never published)


class EventListItem(BaseModel):
    id: int
    name: str
    date: str | None
    end_date: str | None
    event_type: str | None
    discipline: str | None
    organiser_name: str | None
    results_url: str | None
    course_count: int
    course_names: list[str]
    map_id: int
    map_name: str
    map_location: str | None
    version_label: str | None
    survey_date: str | None
    run_dates: list[str] = []  # days you ran this event


class ControlsIn(_In):
    """Start, controls and finish in running order, as [lat, lon]; an empty list clears them."""
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=100)

    @field_validator("points")
    @classmethod
    def _in_range(cls, v):
        if any(not (-90 <= lat <= 90 and -180 <= lon <= 180) for lat, lon in v):
            raise ValueError("latitude/longitude out of range")
        return v


class RouteAdjust(BaseModel):
    dx: float = Field(0, ge=-500, le=500)  # metres east
    dy: float = Field(0, ge=-500, le=500)  # metres north
    rot: float = Field(0, ge=-45, le=45)  # degrees clockwise, around the route's middle


class ParticipationUpdate(_In):
    route_adjust: RouteAdjust | None = None


class CoursesFromFile(_In):
    file_id: int
    skip_first_page: bool = False


# ---------------------------------------------------------------- versions --

class VersionIn(_In):
    label: str | None = None
    survey_date: str | None = Field(None, pattern=PARTIAL_DATE)
    cartographer: str | None = None
    scale: int | None = Field(None, ge=100)
    contour_interval: float | None = Field(None, ge=0)
    standard: str | None = None
    notes: str | None = None


class VersionOut(_Out):
    id: int
    map_id: int
    label: str | None
    survey_date: str | None
    cartographer: str | None
    scale: int | None
    contour_interval: float | None
    standard: str | None
    notes: str | None
    events: list[EventOut] = []
    files: list[FileOut] = []


# -------------------------------------------------------------------- maps --

class MapIn(_In):
    name: str | None = None
    location: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    map_type: str | None = None
    club_id: int | None = None
    tags: list[str] | None = None
    notes: str | None = None
    needs_review: bool | None = None
    publish_level: str | None = Field(None, pattern="^(private|outline|overlay|full)$")
    public_note: str | None = None


class MapBulkUpdate(_In):
    """Change several maps at once. Only the fields that are sent are changed;
    send club_id or map_type as null to clear them."""
    ids: list[int] = Field(min_length=1)
    club_id: int | None = None
    map_type: str | None = None
    publish_level: str | None = Field(None, pattern="^(private|outline|overlay|full)$")
    needs_review: bool | None = None
    add_tags: list[str] = []
    remove_tags: list[str] = []


class InitialCourse(_In):
    name: str
    file_id: int | None = None
    page_no: int | None = None
    length_km: float | None = None
    scale: int | None = None


class MapCreate(MapIn):
    """Create a map, optionally with a first version, files and an event with courses."""
    version: VersionIn | None = None
    file_ids: list[int] = []
    event: EventIn | None = None
    courses: list[InitialCourse] = []


class MapSummary(BaseModel):
    id: int
    name: str
    location: str | None
    lat: float | None
    lon: float | None
    map_type: str | None
    club_id: int | None
    club_name: str | None
    tags: list[str]
    needs_review: bool
    publish_level: str = "private"
    scale: int | None
    contour_interval: float | None
    last_survey: str | None
    last_event: str | None
    version_count: int
    event_count: int
    course_count: int
    file_count: int
    placed_count: int = 0
    footprint: list[list[float]] | None = None  # [[lat, lon]] outline of the main placed page
    overlay: dict | None = None  # main placed page: {page_id, image_url, width, height, corners, clip}
    thumb_url: str | None
    cover_file_id: int | None = None  # the file shown as the map's picture
    updated_at: datetime


class MapCover(_In):
    file_id: int | None = None  # None: back to the automatic choice


class MapDetail(MapSummary):
    cover_chosen: bool = False  # the picture was chosen by you, not picked automatically
    notes: str | None
    public_note: str | None = None
    created_at: datetime
    versions: list[VersionOut]


# ---------------------------------------------------------- georeferencing --

class ControlPoint(BaseModel):
    x: float
    y: float
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)


class FitRequest(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    dpi: float | None = None
    method: str = "auto"
    points: list[ControlPoint]


class GeorefSave(BaseModel):
    method: str = "auto"
    points: list[ControlPoint]
    clip: list[list[float]] | None = None
    also_page_ids: list[int] = []  # same-layout pages that get the same placement


class GeorefOut(BaseModel):
    requested_method: str
    method: str
    points: list[ControlPoint]
    clip: list[list[float]] | None
    corners: list[list[float]]
    rms_m: float | None
    scale: float | None
    rotation_deg: float | None
    metres_per_px: float | None
    updated_at: datetime


class GeorefContext(BaseModel):
    page: PageOut
    file_id: int
    file_name: str
    file_format: str
    page_count: int
    map_id: int | None
    map_name: str | None
    map_lat: float | None
    map_lon: float | None
    map_location: str | None
    stated_scale: int | None
    exif_lat: float | None
    exif_lon: float | None
    same_layout_pages: list[PageOut]  # other pages of this file with identical size
    other_placed: list[dict]  # other placed pages of this map, for reference
    runs: list[dict] = []  # your runs with a GPS track on this map (or the run a Strava photo came from)
    georef: GeorefOut | None
