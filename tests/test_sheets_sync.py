from datetime import date

from app.models import Booking, Cabin
from app.sheets_sync import _parse_date
from app.sheets_sync import sync_bookings


def test_parse_date_handles_iso_format_without_swapping_month_and_day():
    assert _parse_date("2026-08-01") == date(2026, 8, 1)


def test_parse_date_handles_european_day_first_format():
    assert _parse_date("05/08/2026") == date(2026, 8, 5)


def test_sync_creates_bookings_and_cabins_from_local_csv(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    result = sync_bookings(db_session)

    assert result.created == 6
    assert result.skipped == 0
    assert db_session.query(Cabin).count() == 3
    assert db_session.query(Booking).count() == 6


def test_sync_is_idempotent_on_second_run(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    sync_bookings(db_session)
    result = sync_bookings(db_session)

    assert result.created == 0
    assert result.updated == 6
    assert db_session.query(Booking).count() == 6


def test_holiday_stay_gets_holiday_cleaning_rate_after_sync(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")
    sync_bookings(db_session)

    from app.fees import calculate_booking_fees

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1005").first()
    fees = calculate_booking_fees(booking)
    assert fees.is_holiday_cleaning is True
    assert fees.cleaning_fee == 40.0
