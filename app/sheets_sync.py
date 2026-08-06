"""Pulls booking rows from Google Sheets (read-only) and upserts them into the DB.

Four interchangeable source modes, picked via settings.sheets_source_mode:
  - local_csv:       reads a CSV file from disk (handy for testing, no Google setup needed)
  - csv_url:         fetches a Sheet published to the web as CSV (File > Share > Publish to web)
  - service_account: reads via the Sheets API using a Google service account
  - oauth_user:      reads via the Sheets API authenticated as a real Google user
                      (use this if your GCP org blocks service account key creation)

Switching modes or adjusting the column mapping is purely a .env change -- no code changes.
"""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import requests
from dateutil import parser as dateutil_parser
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Booking, Cabin


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)


def _fetch_rows_local_csv() -> list[dict]:
    with open(settings.sheets_local_csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _fetch_rows_csv_url() -> list[dict]:
    resp = requests.get(settings.sheets_csv_url, timeout=30)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def _fetch_rows_service_account() -> list[dict]:
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(settings.google_service_account_json, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(settings.google_sheet_id)
    worksheet = sheet.worksheet(settings.google_sheet_worksheet)
    return worksheet.get_all_records()


_OAUTH_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
OAUTH_TOKEN_SETTING_KEY = "google_oauth_token"


class GoogleNotConnectedError(RuntimeError):
    """Raised when oauth_user mode is selected but no Google account is linked yet."""


def _load_oauth_client_config() -> dict:
    raw = settings.google_oauth_client_secret_json.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    with open(raw, encoding="utf-8") as f:
        return json.load(f)


def build_oauth_flow(redirect_uri: str | None = None):
    """Builds the web OAuth flow used by the /auth/google routes.

    Uses a plain "Web application" OAuth client (not a service account, not a
    desktop client) so the whole login happens as a browser redirect -- no local
    server, no terminal, works identically whether the app runs on your laptop
    or a hosting platform. Not affected by org policies like
    iam.disableServiceAccountKeyCreation, since no service account key exists here.
    """
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        _load_oauth_client_config(),
        scopes=_OAUTH_SCOPES,
        redirect_uri=redirect_uri or settings.google_oauth_redirect_uri,
    )


def oauth_is_connected(db: Session) -> bool:
    from app.settings_store import get_setting

    return get_setting(db, OAUTH_TOKEN_SETTING_KEY) is not None


def _get_oauth_credentials(db: Session):
    import google.auth.transport.requests
    from google.oauth2.credentials import Credentials as UserCredentials

    from app.settings_store import get_setting, set_setting

    token_json = get_setting(db, OAUTH_TOKEN_SETTING_KEY)
    if not token_json:
        raise GoogleNotConnectedError(
            "No Google account connected yet -- visit /auth/google to connect one."
        )

    creds = UserCredentials.from_authorized_user_info(json.loads(token_json), _OAUTH_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
            set_setting(db, OAUTH_TOKEN_SETTING_KEY, creds.to_json())
        else:
            raise GoogleNotConnectedError(
                "Google account connection expired -- visit /auth/google to reconnect it."
            )

    return creds


def _fetch_rows_oauth_user(db: Session) -> list[dict]:
    import gspread

    creds = _get_oauth_credentials(db)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(settings.google_sheet_id)
    worksheet = sheet.worksheet(settings.google_sheet_worksheet)
    return worksheet.get_all_records()


def fetch_rows(db: Session) -> list[dict]:
    mode = settings.sheets_source_mode
    if mode == "local_csv":
        return _fetch_rows_local_csv()
    if mode == "csv_url":
        return _fetch_rows_csv_url()
    if mode == "service_account":
        return _fetch_rows_service_account()
    if mode == "oauth_user":
        return _fetch_rows_oauth_user(db)
    raise ValueError(f"Unknown SHEETS_SOURCE_MODE: {mode!r}")


def _parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # Unambiguous ISO date/datetime (e.g. "2026-08-01" or "2026-08-01T14:00:00Z") --
    # checked first, using just the date prefix, so it can't be misread as
    # day-first by the dayfirst fallback below.
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    # European-style dates (e.g. 05/08/2026 = 5 August) are day-first, not month-first.
    return dateutil_parser.parse(text, dayfirst=True).date()


def _parse_price(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("€", "").replace(",", ".").strip()
    return float(cleaned) if cleaned else 0.0


def _row_external_id(row: dict) -> str:
    raw = row.get(settings.col_external_id, "")
    if raw:
        return str(raw).strip()
    # Fall back to a stable hash of the identifying fields so rows without
    # an explicit reservation ID still dedupe correctly on repeat syncs.
    basis = "|".join(
        str(row.get(col, ""))
        for col in (settings.col_cabin, settings.col_check_in, settings.col_check_out)
    )
    return "auto-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _resolve_guest_name(row: dict) -> str:
    if settings.col_guest_name:
        name = str(row.get(settings.col_guest_name, "")).strip()
        if name:
            return name
    first = str(row.get(settings.col_customer_first_name, "")).strip()
    last = str(row.get(settings.col_customer_last_name, "")).strip()
    return " ".join(part for part in (first, last) if part)


def _extract_cabin_name(raw) -> str:
    """Pulls a cabin/unit name out of a `products`/`variants`-style column.

    Handles a plain name ("Cabin 1"), a JSON list/dict from platforms that export
    the product line items as structured data, and trims trailing quantity
    annotations like " x1" or " (Qty: 1)".

    Plain-text values may also be a comma-separated edit history where earlier
    entries are stale prior selections and only the LAST one is the current cabin
    -- e.g. "Olivia,Santiago (2 nights)" means the booking is for Santiago, not
    Olivia. Trailing parenthetical annotations on that last entry, like
    "(2 nights)" or "(Friday - Monday)", are duration/date metadata, not part of
    the cabin name, and are stripped too.
    """
    text = str(raw or "").strip()
    if not text:
        return "Unassigned"

    if text[0] in "[{":
        try:
            data = json.loads(text)
            if isinstance(data, list) and data:
                first = data[0]
                text = first.get("name", str(first)) if isinstance(first, dict) else str(first)
            elif isinstance(data, dict):
                text = str(data.get("name", text))
        except json.JSONDecodeError:
            pass
    else:
        text = text.split(",")[-1].strip()

    text = re.sub(r"\s*\([^()]*\)\s*$", "", text).strip()
    text = re.sub(r"\s*[\(\[]?\s*x\s*\d+\s*[\)\]]?\s*$", "", text, flags=re.IGNORECASE).strip()
    return text or "Unassigned"


def _row_is_billable(row: dict) -> bool:
    status = str(row.get(settings.col_status, "")).strip().lower()
    return status in settings.billable_states_set


def _get_or_create_cabin(db: Session, name: str) -> Cabin:
    name = (name or "Unassigned").strip() or "Unassigned"
    cabin = db.query(Cabin).filter(Cabin.name == name).first()
    if cabin is None:
        cabin = Cabin(name=name)
        db.add(cabin)
        db.flush()
    return cabin


def sync_bookings(db: Session) -> SyncResult:
    result = SyncResult()
    rows = fetch_rows(db)
    seen_external_ids: set[str] = set()

    for row in rows:
        external_id = _row_external_id(row)
        seen_external_ids.add(external_id)

        if not _row_is_billable(row):
            # A booking that was previously synced as billable (e.g. "completed")
            # can later flip to a non-billable state (cancelled, refunded, ...).
            # Remove any such stale record so it stops counting towards revenue.
            # Uses session.delete() rather than a bulk .delete() so the
            # cascade="all, delete-orphan" on Booking.flags actually fires.
            stale = db.query(Booking).filter(Booking.external_id == external_id).first()
            if stale:
                db.delete(stale)
                result.removed += 1
            result.skipped += 1
            continue

        try:
            check_in = _parse_date(row[settings.col_check_in])
            check_out = _parse_date(row[settings.col_check_out])
        except (KeyError, ValueError, OverflowError) as exc:
            result.errors.append(f"Skipped row {row!r}: {exc}")
            result.skipped += 1
            continue

        cabin = _get_or_create_cabin(db, _extract_cabin_name(row.get(settings.col_cabin, "")))

        existing = db.query(Booking).filter(Booking.external_id == external_id).first()
        values = dict(
            cabin_id=cabin.id,
            guest_name=_resolve_guest_name(row),
            check_in=check_in,
            check_out=check_out,
            total_price=_parse_price(row.get(settings.col_total_price)),
            booking_source=str(row.get(settings.col_booking_source, "")).strip(),
            status=str(row.get(settings.col_status, "")).strip(),
            synced_at=datetime.utcnow(),
        )

        if existing:
            for key, val in values.items():
                setattr(existing, key, val)
            result.updated += 1
        else:
            db.add(Booking(external_id=external_id, **values))
            result.created += 1

    # A row can also disappear from the Sheet entirely (deleted outright, not just
    # marked cancelled) -- the loop above never sees it, so without this it would
    # stay in the DB forever, quietly inflating revenue/occupancy. Only run this
    # when the fetch actually returned rows, so a transient empty/failed fetch
    # can't wipe out every booking.
    if rows:
        orphaned = db.query(Booking).filter(~Booking.external_id.in_(seen_external_ids)).all()
        for stale in orphaned:
            db.delete(stale)
            result.removed += 1

    # Cabins can become orphaned (e.g. a booking's cabin got reassigned after a
    # products-column parsing fix, or a cabin name changed upstream) -- prune
    # them so they don't inflate the occupancy denominator with empty rows.
    db.flush()
    for cabin in db.query(Cabin).filter(~Cabin.bookings.any()).all():
        db.delete(cabin)

    db.commit()
    return result
