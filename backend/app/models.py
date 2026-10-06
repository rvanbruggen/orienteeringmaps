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

    file: Mapped[File] = relationship(back_populates="pages")
