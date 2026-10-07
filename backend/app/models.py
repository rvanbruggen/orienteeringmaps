"""Database models.

Map ─< MapVersion ─< Event ─< Course
             └─< File ─< Page

A File (PDF or image) belongs to a MapVersion, or to nobody yet (the inbox).
A Course can point at a File, and at a page within it (multi-page PDFs).

Dates of surveys and events are stored as partial ISO strings: "2021",
"2021-05" or "2021-05-14", because old maps often only state a month or year.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Float, ForeignKey, Integer, String, Text, DateTime,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Club(Base):
    __tablename__ = "clubs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    short_name: Mapped[str | None] = mapped_column(String(50))
    federation: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)


class Map(Base):
    __tablename__ = "maps"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))  # nearest village / town / city
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    map_type: Mapped[str | None] = mapped_column(String(40))
    club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="SET NULL"))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[int] = mapped_column(Integer, default=0)  # set by bulk import
    # What the public site shows: private | outline | overlay | full (see publish.py).
    publish_level: Mapped[str] = mapped_column(String(10), default="private", server_default="private")
    public_note: Mapped[str | None] = mapped_column(Text)  # shown on the public site instead of notes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    club: Mapped[Club | None] = relationship()
    versions: Mapped[list["MapVersion"]] = relationship(
        back_populates="map", cascade="all, delete-orphan", order_by="MapVersion.survey_date"
    )


class MapVersion(Base):
    __tablename__ = "map_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("maps.id", ondelete="CASCADE"), index=True)
    label: Mapped[str | None] = mapped_column(String(100))
    survey_date: Mapped[str | None] = mapped_column(String(10))
    cartographer: Mapped[str | None] = mapped_column(String(200))
    scale: Mapped[int | None] = mapped_column(Integer)  # denominator: 10000 for 1:10 000
    contour_interval: Mapped[float | None] = mapped_column(Float)  # metres
    standard: Mapped[str | None] = mapped_column(String(40))  # ISOM 2017-2, ISSprOM 2019-2, ...
    notes: Mapped[str | None] = mapped_column(Text)

    map: Mapped[Map] = relationship(back_populates="versions")
    events: Mapped[list["Event"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="Event.date"
    )
    files: Mapped[list["File"]] = relationship(back_populates="version", order_by="File.id")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    map_version_id: Mapped[int] = mapped_column(ForeignKey("map_versions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))  # permanent courses run for a period
    event_type: Mapped[str | None] = mapped_column(String(40))
    discipline: Mapped[str | None] = mapped_column(String(40))
    organiser_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="SET NULL"))
    results_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    version: Mapped[MapVersion] = relationship(back_populates="events")
    organiser: Mapped[Club | None] = relationship()
    courses: Mapped[list["Course"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="Course.id"
    )


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    length_km: Mapped[float | None] = mapped_column(Float)
    climb_m: Mapped[int | None] = mapped_column(Integer)
    scale: Mapped[int | None] = mapped_column(Integer)  # print scale, if it differs from the version's
    controls: Mapped[int | None] = mapped_column(Integer)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    page_no: Mapped[int | None] = mapped_column(Integer)  # 1-based
    notes: Mapped[str | None] = mapped_column(Text)

    event: Mapped[Event] = relationship(back_populates="courses")
    file: Mapped["File | None"] = relationship()


class File(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(primary_key=True)
    map_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("map_versions.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="map")
    original_name: Mapped[str] = mapped_column(String(500))
    stored_name: Mapped[str] = mapped_column(String(200))  # relative to ORIGINALS_DIR
    format: Mapped[str] = mapped_column(String(10))  # pdf, png, jpg, tif, webp, heic
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    phash: Mapped[str | None] = mapped_column(String(32))
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    text_source: Mapped[str | None] = mapped_column(String(10))  # pdf | ocr
    exif_lat: Mapped[float | None] = mapped_column(Float)
    exif_lon: Mapped[float | None] = mapped_column(Float)
    suggestions: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    version: Mapped[MapVersion | None] = relationship(back_populates="files")
    pages: Mapped[list["Page"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="Page.page_no"
    )


class Page(Base):
    __tablename__ = "pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)  # 1-based
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    image_name: Mapped[str] = mapped_column(String(200))  # relative to DERIVED_DIR
    thumb_name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str | None] = mapped_column(Text)
    dpi: Mapped[float | None] = mapped_column(Float)  # pixels per inch of paper, if known

    file: Mapped[File] = relationship(back_populates="pages")
    georef: Mapped["Georeference | None"] = relationship(
        back_populates="page", cascade="all, delete-orphan", uselist=False
    )


class Georeference(Base):
    """Where a page image lies on the world, fitted from control points."""
    __tablename__ = "georeferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), unique=True)
    requested_method: Mapped[str] = mapped_column(String(20))  # what the user chose (may be "auto")
    method: Mapped[str] = mapped_column(String(20))  # what was fitted
    points: Mapped[list] = mapped_column(JSON)  # [{x, y, lat, lon}]
    clip: Mapped[list | None] = mapped_column(JSON)  # [[x, y], ...] image pixels, or None
    matrix: Mapped[list] = mapped_column(JSON)  # 3x3, image px -> Web Mercator metres
    corners: Mapped[list] = mapped_column(JSON)  # [[lat, lon]] TL, TR, BR, BL
    rms_m: Mapped[float | None] = mapped_column(Float)
    scale: Mapped[float | None] = mapped_column(Float)
    rotation_deg: Mapped[float | None] = mapped_column(Float)
    metres_per_px: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    page: Mapped[Page] = relationship(back_populates="georef")


class Setting(Base):
    """Small key/value store for app settings (public site configuration)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | list | str | None] = mapped_column(JSON)


class PublishRun(Base):
    """One push of the public site to GitHub."""
    __tablename__ = "publish_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | unchanged | error
    repo: Mapped[str | None] = mapped_column(String(200))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[dict | None] = mapped_column(JSON)
    log: Mapped[str | None] = mapped_column(Text)


class StravaActivity(Base):
    """One activity imported from Strava (summary only; GPS points come later, per race).

    Strava's terms allow showing this data only to the athlete it belongs to,
    so nothing here ever goes on the public site.
    """
    __tablename__ = "strava_activities"
    id: Mapped[int] = mapped_column(primary_key=True)  # Strava's activity id
    name: Mapped[str] = mapped_column(String(300))
    sport_type: Mapped[str | None] = mapped_column(String(40))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)  # UTC
    start_local: Mapped[str | None] = mapped_column(String(19))  # "2026-10-04T10:34:22", local time
    distance_m: Mapped[float | None] = mapped_column(Float)
    moving_time_s: Mapped[int | None] = mapped_column(Integer)
    elapsed_time_s: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    workout_type: Mapped[int | None] = mapped_column(Integer)  # 1 = race (runs)
    commute: Mapped[int] = mapped_column(Integer, default=0)
    private: Mapped[int] = mapped_column(Integer, default=0)
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lon: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[list | None] = mapped_column(JSON)  # [min_lat, min_lon, max_lat, max_lon] of the route
    polyline: Mapped[str | None] = mapped_column(Text)  # Strava's simplified route (encoded polyline)
    orienteering: Mapped[int] = mapped_column(Integer, default=0)
    orienteering_manual: Mapped[int] = mapped_column(Integer, default=0)  # set by you: sync won't change it
    raw: Mapped[dict | None] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
