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
    ("bookings", "cabin_override_id", "INTEGER"),
    ("bookings", "check_out_override", "DATE"),
    ("bookings", "skip_cleaning_fee", "BOOLEAN DEFAULT FALSE"),
    ("bookings", "override_note", "VARCHAR(300) DEFAULT ''"),
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


def run_data_fixes(engine: Engine) -> None:
    """One-off data corrections, safe to run on every startup. Most fixes are
    idempotent purely by their WHERE clause (it naturally matches nothing once
    applied); a fix whose target field a user might legitimately reset back to
    its "unfixed" value afterwards instead tracks completion via a Settings
    marker, so it only ever applies once."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "expenses" in table_names:
        with engine.begin() as conn:
            # Madalena's cost was originally logged under "Other" before the
            # dedicated "Staff" category existed.
            conn.execute(
                text(
                    "UPDATE expenses SET category = 'staff' "
                    "WHERE category = 'other' AND lower(description) LIKE '%madalena%'"
                )
            )

    if "bookings" in table_names and "cabins" in table_names and "settings" in table_names:
        with engine.begin() as conn:
            # Booking 9MW-6KRD's Sheet "products" cell recorded an incomplete edit
            # history ("Olivia,Santiago (2 nights)") missing the final change back
            # to Olivia, so the last-comma-segment parsing rule picked up Santiago.
            # This is a one-off Sheet data issue, not a parser bug -- correct it via
            # an override that survives re-syncs. Tracked with a Settings marker
            # (rather than "WHERE cabin_override_id IS NULL") so that manually
            # clearing the override later doesn't cause it to silently come back.
            already_applied = conn.execute(
                text("SELECT value FROM settings WHERE key = 'data_fix_9mw_6krd_cabin'")
            ).scalar()
            if not already_applied:
                conn.execute(
                    text(
                        "UPDATE bookings SET cabin_override_id = "
                        "(SELECT id FROM cabins WHERE name = 'Olivia') "
                        "WHERE external_id = '9MW-6KRD' "
                        "AND EXISTS (SELECT 1 FROM cabins WHERE name = 'Olivia')"
                    )
                )
                conn.execute(text("INSERT INTO settings (key, value) VALUES ('data_fix_9mw_6krd_cabin', '1')"))
