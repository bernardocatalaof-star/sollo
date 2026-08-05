"""Pulls booking rows from Google Sheets (read-only) and upserts them into the DB.

Three interchangeable source modes, picked via settings.sheets_source_mode:
  - local_csv:       reads a CSV file from disk (handy for testing, no Google setup needed)
  - csv_url:         fetches a Sheet published to the web as CSV (File > Share > Publish to web)
  - service_account: reads via the Sheets API using a Google service account

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


def fetch_rows() -> list[dict]:
    mode = settings.sheets_source_mode
    if mode == "local_csv":
        return _fetch_rows_local_csv()
    if mode == "csv_url":
        return _fetch_rows_csv_url()
    if mode == "service_account":
        return _fetch_rows_service_account()
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
    rows = fetch_rows()

    for row in rows:
        if not _row_is_billable(row):
            # A booking that was previously synced as billable (e.g. "completed")
            # can later flip to a non-billable state (cancelled, refunded, ...).
            # Remove any such stale record so it stops counting towards revenue.
            # Uses session.delete() rather than a bulk .delete() so the
            # cascade="all, delete-orphan" on Booking.flags actually fires.
            external_id = _row_external_id(row)
            stale = db.query(Booking).filter(Booking.external_id == external_id).first()
            if stale:
                db.delete(stale)
                result.removed += 1
            result.skipped += 1
            continue

        try:
            external_id = _row_external_id(row)
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

    db.commit()
    return result
