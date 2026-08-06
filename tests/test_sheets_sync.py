from datetime import date

from app.models import Booking, Cabin
from app.sheets_sync import _extract_cabin_name, _parse_date, sync_bookings


def test_parse_date_handles_iso_format_without_swapping_month_and_day():
    assert _parse_date("2026-08-01") == date(2026, 8, 1)


def test_parse_date_handles_iso_datetime_with_time_component():
    assert _parse_date("2026-08-01T14:30:00Z") == date(2026, 8, 1)


def test_parse_date_handles_european_day_first_format():
    assert _parse_date("05/08/2026") == date(2026, 8, 5)


def test_extract_cabin_name_from_plain_text():
    assert _extract_cabin_name("Cabin 1") == "Cabin 1"


def test_extract_cabin_name_strips_quantity_suffix():
    assert _extract_cabin_name("Cabin 1 x1") == "Cabin 1"


def test_extract_cabin_name_from_json_list():
    assert _extract_cabin_name('[{"name": "Cabin 2", "qty": 1}]') == "Cabin 2"


def test_extract_cabin_name_uses_last_entry_of_edit_history_with_night_count():
    assert _extract_cabin_name("Santiago (2 nights),Santiago (Friday - Monday)") == "Santiago"


def test_extract_cabin_name_uses_last_entry_when_cabin_selection_changed():
    assert _extract_cabin_name("Olivia,Santiago (2 nights)") == "Santiago"


def test_sync_creates_bookings_and_cabins_from_local_csv(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    result = sync_bookings(db_session)

    assert result.created == 6
    assert result.skipped == 1  # the cancelled row
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


def test_sync_removes_booking_that_became_non_billable(db_session, monkeypatch, tmp_path):
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,net_paid\n"
    row_completed = "R-9,completed,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,100.00\n"
    row_cancelled = "R-9,cancelled,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,0.00\n"

    csv_path.write_text(header + row_completed)
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))
    sync_bookings(db_session)
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 1

    csv_path.write_text(header + row_cancelled)
    result = sync_bookings(db_session)

    assert result.removed == 1
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 0


def test_holiday_stay_gets_holiday_cleaning_rate_after_sync(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")
    sync_bookings(db_session)

    from app.fees import calculate_booking_fees

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1005").first()
    fees = calculate_booking_fees(booking)
    assert fees.is_holiday_cleaning is True
    assert fees.cleaning_fee == 40.0
