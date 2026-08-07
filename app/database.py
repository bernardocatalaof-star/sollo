import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def _normalize_database_url(url: str) -> str:
    """Accepts the plain connection string a host like Neon/Render hands you as-is --
    no manual editing required to add the +psycopg driver suffix."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


database_url = _normalize_database_url(settings.database_url)

db_path = database_url.replace("sqlite:///", "")
if db_path.startswith("./"):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    # Hosted Postgres providers (e.g. Neon) close idle connections server-side.
    # Without pre-ping, the pool can hand out a dead connection and the first
    # query on it fails with "SSL connection has been closed unexpectedly" --
    # pre-ping tests each connection and transparently reconnects if it's stale.
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Base.metadata.create_all() only creates tables that don't exist yet -- it never
# alters an existing table for a column added later in a model. Tracking each such
# addition here keeps a hosted DB (which persists across deploys, unlike a local
# SQLite file recreated from a fresh clone) in sync without pulling in a full
# migration framework for a single-developer app this size.
_COLUMN_MIGRATIONS = [
    ("bookings", "booked_at", "DATE"),
    ("bookings", "phone", "VARCHAR(60)"),
]


def run_schema_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    for table, column, col_type in _COLUMN_MIGRATIONS:
        if table not in inspector.get_table_names():
            continue  # fresh DB -- create_all() already added it via the model
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
