"""SQLite engine, sessions and schema migrations."""
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base

engine = None
SessionLocal: sessionmaker | None = None

# Schema migrations, applied in order on top of the initial create_all.
# Each entry moves PRAGMA user_version from its index to index + 1.
# Never edit an entry once released; append a new one instead.
MIGRATIONS: list[str] = [
    "",  # 0 -> 1: initial schema (created by create_all)
    # 1 -> 2 (v0.2.0): georeferencing
    """
    ALTER TABLE pages ADD COLUMN dpi FLOAT;
    CREATE TABLE georeferences (
        id INTEGER NOT NULL PRIMARY KEY,
        page_id INTEGER NOT NULL UNIQUE REFERENCES pages (id) ON DELETE CASCADE,
        requested_method VARCHAR(20) NOT NULL,
        method VARCHAR(20) NOT NULL,
        points JSON NOT NULL,
        clip JSON,
        matrix JSON NOT NULL,
        corners JSON NOT NULL,
        rms_m FLOAT,
        scale FLOAT,
        rotation_deg FLOAT,
        metres_per_px FLOAT,
        updated_at DATETIME NOT NULL
    )
    """,
    # 2 -> 3 (v0.5.0): public site
    """
    ALTER TABLE maps ADD COLUMN publish_level VARCHAR(10) NOT NULL DEFAULT 'private';
    ALTER TABLE maps ADD COLUMN public_note TEXT;
    CREATE TABLE settings (
        key VARCHAR(60) NOT NULL PRIMARY KEY,
        value JSON
    );
    CREATE TABLE publish_runs (
        id INTEGER NOT NULL PRIMARY KEY,
        started_at DATETIME NOT NULL,
        finished_at DATETIME,
        status VARCHAR(20) NOT NULL,
        repo VARCHAR(200),
        commit_sha VARCHAR(40),
        summary JSON,
        log TEXT
    )
    """,
    # 3 -> 4 (v0.6.0): Strava activities
    """
    CREATE TABLE strava_activities (
        id INTEGER NOT NULL PRIMARY KEY,
        name VARCHAR(300) NOT NULL,
        sport_type VARCHAR(40),
        start_date DATETIME NOT NULL,
        start_local VARCHAR(19),
        distance_m FLOAT,
        moving_time_s INTEGER,
        elapsed_time_s INTEGER,
        elevation_gain_m FLOAT,
        workout_type INTEGER,
        commute INTEGER NOT NULL,
        private INTEGER NOT NULL,
        start_lat FLOAT,
        start_lon FLOAT,
        bbox JSON,
        polyline TEXT,
        orienteering INTEGER NOT NULL,
        orienteering_manual INTEGER NOT NULL,
        raw JSON,
        synced_at DATETIME NOT NULL
    );
    CREATE INDEX ix_strava_activities_start_date ON strava_activities (start_date)
    """,
    # 4 -> 5 (v0.7.0): your runs of events
    """
    CREATE TABLE participations (
        id INTEGER NOT NULL PRIMARY KEY,
        event_id INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
        course_id INTEGER REFERENCES courses (id) ON DELETE SET NULL,
        strava_activity_id INTEGER UNIQUE REFERENCES strava_activities (id) ON DELETE SET NULL,
        date VARCHAR(10),
        result_time_s INTEGER,
        position INTEGER,
        competitors INTEGER,
        notes TEXT,
        created_at DATETIME NOT NULL
    );
    CREATE INDEX ix_participations_event_id ON participations (event_id)
    """,
    # 5 -> 6 (v0.8.0): photos imported from Strava
    """
    ALTER TABLE files ADD COLUMN source VARCHAR(20);
    ALTER TABLE files ADD COLUMN source_id VARCHAR(100);
    CREATE INDEX ix_files_source_id ON files (source_id)
    """,
    # 6 -> 7 (v0.9.0): GPS tracks of runs
    """
    ALTER TABLE strava_activities ADD COLUMN streams JSON
    """,
    # 7 -> 8 (v0.10.0): control positions and route corrections
    """
    ALTER TABLE courses ADD COLUMN control_coords JSON;
    ALTER TABLE participations ADD COLUMN route_adjust JSON
    """,
    # 8 -> 9 (v0.10.1): the map's picture, chosen by you
    """
    ALTER TABLE maps ADD COLUMN cover_file_id INTEGER
    """,
    # 9 -> 10 (v0.11.0): races from the O'Punch calendar
    """
    ALTER TABLE events ADD COLUMN opunch_id INTEGER;
    CREATE INDEX ix_events_opunch_id ON events (opunch_id);
    CREATE TABLE opunch_events (
        id INTEGER NOT NULL PRIMARY KEY,
        name VARCHAR(300) NOT NULL,
        date VARCHAR(10) NOT NULL,
        end_date VARCHAR(10),
        start VARCHAR(16),
        "end" VARCHAR(16),
        lat FLOAT,
        lon FLOAT,
        venue VARCHAR(300),
        town VARCHAR(200),
        location TEXT,
        description TEXT,
        url VARCHAR(300) NOT NULL,
        club_code VARCHAR(40),
        club_name VARCHAR(200),
        level INTEGER,
        map_name VARCHAR(300),
        results_url VARCHAR(500),
        splits_url VARCHAR(500),
        registrations INTEGER,
        details_at DATETIME,
        source VARCHAR(10) NOT NULL,
        ran INTEGER NOT NULL,
        first_seen DATETIME NOT NULL,
        last_seen DATETIME NOT NULL
    );
    CREATE INDEX ix_opunch_events_date ON opunch_events (date)
    """,
    # 10 -> 11 (v0.12.0): import tasks
    """
    CREATE TABLE import_tasks (
        id INTEGER NOT NULL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        match_by_date INTEGER NOT NULL,
        created_at DATETIME NOT NULL
    );
    CREATE TABLE import_items (
        id INTEGER NOT NULL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES import_tasks (id) ON DELETE CASCADE,
        original_name VARCHAR(500) NOT NULL,
        path VARCHAR(1000),
        owned INTEGER NOT NULL,
        size_bytes INTEGER,
        status VARCHAR(20) NOT NULL,
        error TEXT,
        file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
        day VARCHAR(10),
        outcome VARCHAR(20),
        activity_id INTEGER REFERENCES strava_activities (id) ON DELETE SET NULL,
        candidates JSON,
        note TEXT,
        review VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL,
        processed_at DATETIME
    );
    CREATE INDEX ix_import_items_task_id ON import_items (task_id)
    """,
]


def _set_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def init_db(db_url: str | None = None) -> None:
    global engine, SessionLocal
    config.ensure_dirs()
    engine = create_engine(db_url or f"sqlite:///{config.DB_PATH}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _set_pragmas)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with engine.begin() as conn:
        current = conn.execute(text("PRAGMA user_version")).scalar() or 0
        if current == 0:
            # Fresh database: the models already describe the latest schema.
            Base.metadata.create_all(conn)
            current = len(MIGRATIONS)
        for target in range(current, len(MIGRATIONS)):
            for stmt in filter(None, (s.strip() for s in MIGRATIONS[target].split(";"))):
                conn.execute(text(stmt))
            current = target + 1
        conn.execute(text(f"PRAGMA user_version={current}"))


def get_session() -> Iterator[Session]:
    assert SessionLocal is not None, "init_db() not called"
    with SessionLocal() as session:
        yield session
