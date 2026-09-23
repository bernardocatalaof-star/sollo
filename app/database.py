import os
import secrets
from datetime import datetime

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
    ("bookings", "email", "VARCHAR(200)"),
    ("bookings", "cabin_override_id", "INTEGER"),
    ("bookings", "check_out_override", "DATE"),
    ("bookings", "skip_cleaning_fee", "BOOLEAN DEFAULT FALSE"),
    ("bookings", "override_note", "VARCHAR(300) DEFAULT ''"),
    ("cabins", "guide_token", "VARCHAR(32) DEFAULT ''"),
    ("guidebook_sections", "title_en", "VARCHAR(120) DEFAULT ''"),
    ("guidebook_sections", "body_en", "TEXT"),
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


def backfill_cabin_guide_tokens(engine: Engine) -> None:
    """Every cabin needs a guide_token to have a working /guide link -- assigns
    one to any cabin that doesn't have it yet (a fresh column from the schema
    migration above, or a cabin created before this feature existed). Each
    token is generated individually since a plain ALTER TABLE default can't
    produce a distinct random value per row."""
    inspector = inspect(engine)
    if "cabins" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id FROM cabins WHERE guide_token IS NULL OR guide_token = ''")).fetchall()
        for (cabin_id,) in rows:
            conn.execute(
                text("UPDATE cabins SET guide_token = :token WHERE id = :id"),
                {"token": secrets.token_urlsafe(9), "id": cabin_id},
            )


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

    if "bookings" in table_names and "cabins" in table_names:
        with engine.begin() as conn:
            # A deprecated Sheet product, "Olivia weekend (NOT IN USE!)", used to
            # slip past the cabin-name parser untouched and create a brand new
            # phantom "Olivia weekend" cabin -- fixed in the parser itself, but
            # any such cabin already created needs its bookings folded back into
            # the real "Olivia" cabin. This is naturally idempotent: once the
            # phantom cabin is deleted below, the WHERE clauses match nothing.
            conn.execute(
                text(
                    "UPDATE bookings SET cabin_id = (SELECT id FROM cabins WHERE lower(name) = 'olivia') "
                    "WHERE cabin_id = (SELECT id FROM cabins WHERE lower(name) = 'olivia weekend') "
                    "AND EXISTS (SELECT 1 FROM cabins WHERE lower(name) = 'olivia weekend') "
                    "AND EXISTS (SELECT 1 FROM cabins WHERE lower(name) = 'olivia')"
                )
            )
            conn.execute(
                text(
                    "UPDATE bookings SET cabin_override_id = (SELECT id FROM cabins WHERE lower(name) = 'olivia') "
                    "WHERE cabin_override_id = (SELECT id FROM cabins WHERE lower(name) = 'olivia weekend') "
                    "AND EXISTS (SELECT 1 FROM cabins WHERE lower(name) = 'olivia weekend') "
                    "AND EXISTS (SELECT 1 FROM cabins WHERE lower(name) = 'olivia')"
                )
            )
            conn.execute(text("DELETE FROM cabins WHERE lower(name) = 'olivia weekend'"))


# Info the owner gave directly (pasted in chat, not scraped from anywhere --
# the linked Mailchimp emails, the Notion FAQ page, and the Canva manuals
# were all unreachable from here, blocked by this environment's network
# policy) -- seeded once as extra guidebook sections per cabin. Each entry
# is tracked via its own Settings marker so it only runs once; a later
# manual edit or deletion by the owner is never overwritten or reinstated.
_CABIN_EXTRA_SECTIONS = {
    "Olivia": [
        {
            "key": "sim",
            "icon": "📱",
            "title": "Cartão SIM da cabana",
            "title_en": "Cabin SIM card",
            "body": "Telemóvel da cabana: **912 673 846** (Vodafone)\nCódigo PIN: **0878**\nCódigo PUK: **47319946**",
            "body_en": "Cabin phone: **912 673 846** (Vodafone)\nPIN code: **0878**\nPUK code: **47319946**",
        },
        {
            "key": "links",
            "icon": "🔗",
            "title": "Recursos úteis",
            "title_en": "Useful links",
            "body": (
                "Manual completo da cabana:\n"
                "https://www.canva.com/design/DAGUTqx5X14/JAjG6-WK6RxbgDDiMblYUA/view\n\n"
                "Perguntas frequentes:\n"
                "https://app.notion.com/p/Perguntas-e-problemas-2961c45f6969804cbd85dfebf77689a5"
            ),
            "body_en": (
                "Full cabin manual:\n"
                "https://www.canva.com/design/DAGUTqx5X14/JAjG6-WK6RxbgDDiMblYUA/view\n\n"
                "Frequently asked questions:\n"
                "https://app.notion.com/p/Perguntas-e-problemas-2961c45f6969804cbd85dfebf77689a5"
            ),
        },
    ],
    "Santiago": [
        {
            "key": "sim",
            "icon": "📱",
            "title": "Cartão SIM da cabana",
            "title_en": "Cabin SIM card",
            "body": "Telemóvel da cabana: **917 631 865** (Vodafone)\nCódigo PIN: **1338**\nCódigo PUK: **28534642**",
            "body_en": "Cabin phone: **917 631 865** (Vodafone)\nPIN code: **1338**\nPUK code: **28534642**",
        },
        {
            "key": "links",
            "icon": "🔗",
            "title": "Recursos úteis",
            "title_en": "Useful links",
            "body": (
                "Manual completo da cabana:\n"
                "https://www.canva.com/design/DAG18Qbqzo8/t9EBjr5A5EjACZRDUxLn5A/view\n\n"
                "Perguntas frequentes:\n"
                "https://app.notion.com/p/Perguntas-e-problemas-2961c45f6969804cbd85dfebf77689a5"
            ),
            "body_en": (
                "Full cabin manual:\n"
                "https://www.canva.com/design/DAG18Qbqzo8/t9EBjr5A5EjACZRDUxLn5A/view\n\n"
                "Frequently asked questions:\n"
                "https://app.notion.com/p/Perguntas-e-problemas-2961c45f6969804cbd85dfebf77689a5"
            ),
        },
    ],
}


def seed_cabin_extra_sections(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if not {"cabins", "guidebook_sections", "settings"}.issubset(table_names):
        return

    with engine.begin() as conn:
        for cabin_name, entries in _CABIN_EXTRA_SECTIONS.items():
            cabin_id = conn.execute(text("SELECT id FROM cabins WHERE name = :n"), {"n": cabin_name}).scalar()
            if not cabin_id:
                continue
            for entry in entries:
                marker = f"guidebook_seeded_{entry['key']}_{cabin_name.lower()}"
                already = conn.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": marker}).scalar()
                if already:
                    continue
                max_position = conn.execute(
                    text("SELECT MAX(position) FROM guidebook_sections WHERE cabin_id = :c"), {"c": cabin_id}
                ).scalar()
                now = datetime.utcnow()
                conn.execute(
                    text(
                        "INSERT INTO guidebook_sections "
                        "(cabin_id, icon, title, title_en, body, body_en, position, created_at, updated_at) "
                        "VALUES (:cabin_id, :icon, :title, :title_en, :body, :body_en, :position, :now, :now)"
                    ),
                    {
                        "cabin_id": cabin_id,
                        "icon": entry["icon"],
                        "title": entry["title"],
                        "title_en": entry["title_en"],
                        "body": entry["body"],
                        "body_en": entry["body_en"],
                        "position": (max_position + 1) if max_position is not None else 0,
                        "now": now,
                    },
                )
                conn.execute(text("INSERT INTO settings (key, value) VALUES (:k, '1')"), {"k": marker})
