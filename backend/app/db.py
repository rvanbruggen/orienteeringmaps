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
