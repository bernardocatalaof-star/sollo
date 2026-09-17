from datetime import date

from app.models import Booking, Cabin
from app.sheets_sync import (
    _extract_cabin_name,
    _parse_date,
    _parse_optional_date,
    _resolve_total_price,
    sync_bookings,
)


def test_parse_date_handles_iso_format_without_swapping_month_and_day():
    assert _parse_date("2026-08-01") == date(2026, 8, 1)


def test_parse_date_handles_iso_datetime_with_time_component():
    assert _parse_date("2026-08-01T14:30:00Z") == date(2026, 8, 1)


def test_parse_date_handles_european_day_first_format():
    assert _parse_date("05/08/2026") == date(2026, 8, 5)


def test_parse_optional_date_returns_none_for_missing_value():
    assert _parse_optional_date(None) is None
    assert _parse_optional_date("") is None


def test_parse_optional_date_returns_none_for_unparseable_value_instead_of_raising():
    assert _parse_optional_date("not a date") is None


def test_parse_optional_date_parses_a_valid_date():
    assert _parse_optional_date("2026-07-15") == date(2026, 7, 15)


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


def test_extract_cabin_name_normalizes_a_deprecated_rate_plan_suffix():
    # A deprecated Sheet product ("Olivia weekend") used to create a brand new
    # phantom "Olivia weekend" cabin instead of resolving to the real Olivia.
    assert _extract_cabin_name("Olivia weekend (NOT IN USE!)") == "Olivia"
    assert _extract_cabin_name("Santiago weekend") == "Santiago"


def test_extract_cabin_name_leaves_unrelated_names_untouched():
    # Only known real cabin names get this treatment -- anything else (a test
    # fixture, or a genuinely different cabin added later) passes through as-is.
    assert _extract_cabin_name("Cabin 1 weekend") == "Cabin 1 weekend"


def test_resolve_total_price_uses_total_column_for_completed():
    row = {"total": "320.00", "received": "100.00", "net_paid": "0.00"}
    assert _resolve_total_price(row, "completed") == 320.0


def test_resolve_total_price_uses_received_column_for_pending_payment():
    row = {"total": "320.00", "received": "100.00", "net_paid": "0.00"}
    assert _resolve_total_price(row, "pending_payment") == 100.0


def test_resolve_total_price_uses_net_paid_column_for_cancelled():
    row = {"total": "320.00", "received": "50.00", "net_paid": "50.00"}
    assert _resolve_total_price(row, "cancelled") == 50.0


def test_sync_creates_bookings_and_cabins_from_local_csv(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    result = sync_bookings(db_session)

    # "cancelled" is synced too now (for its NET_PAID revenue), so all 7 rows land.
    assert result.created == 7
    assert result.skipped == 0
    assert db_session.query(Cabin).count() == 3
    assert db_session.query(Booking).count() == 7


def test_sync_is_idempotent_on_second_run(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    sync_bookings(db_session)
    result = sync_bookings(db_session)

    assert result.created == 0
    assert result.updated == 7
    assert db_session.query(Booking).count() == 7


def test_sync_stores_booked_at_from_sheet(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    sync_bookings(db_session)

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1001").first()
    assert booking.booked_at == date(2026, 7, 15)


def test_sync_stores_customer_phone_from_sheet(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")

    sync_bookings(db_session)

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1001").first()
    assert booking.phone == "+351912345001"


def test_sync_leaves_phone_blank_when_column_missing(db_session, monkeypatch, tmp_path):
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,net_paid\n"
    row = "R-9,completed,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,100.00\n"
    csv_path.write_text(header + row)

    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))
    sync_bookings(db_session)

    booking = db_session.query(Booking).filter(Booking.external_id == "R-9").first()
    assert booking.phone == ""


def test_sync_leaves_booked_at_blank_when_column_missing_or_unparseable(db_session, monkeypatch, tmp_path):
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,net_paid\n"
    row = "R-9,completed,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,100.00\n"
    csv_path.write_text(header + row)

    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))
    sync_bookings(db_session)

    booking = db_session.query(Booking).filter(Booking.external_id == "R-9").first()
    assert booking.booked_at is None


def test_sync_removes_booking_that_became_non_billable(db_session, monkeypatch, tmp_path):
    # "declined" (unlike "cancelled") isn't in billable_states at all -- it
    # should disappear from the DB entirely, not just lose its landowner fees.
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,total,received,net_paid\n"
    row_completed = "R-9,completed,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,100.00,100.00,100.00\n"
    row_declined = "R-9,declined,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,0.00,0.00,0.00\n"

    csv_path.write_text(header + row_completed)
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))
    sync_bookings(db_session)
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 1

    csv_path.write_text(header + row_declined)
    result = sync_bookings(db_session)

    assert result.removed == 1
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 0


def test_sync_removes_booking_whose_row_was_deleted_entirely_from_sheet(db_session, monkeypatch, tmp_path):
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,net_paid\n"
    row = "R-9,completed,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,100.00\n"

    csv_path.write_text(header + row)
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))
    sync_bookings(db_session)
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 1

    other_row = "R-10,completed,John,Roe,Cabin 1,2026-08-05,2026-08-07,80.00\n"
    csv_path.write_text(header + other_row)
    result = sync_bookings(db_session)

    assert result.removed == 1
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 0
    assert db_session.query(Booking).filter(Booking.external_id == "R-10").count() == 1


def test_sync_does_not_wipe_bookings_when_fetch_returns_no_rows(db_session, monkeypatch, tmp_path):
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,net_paid\n"
    row = "R-9,completed,Jane,Doe,Cabin 1,2026-08-01,2026-08-03,100.00\n"

    csv_path.write_text(header + row)
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))
    sync_bookings(db_session)

    csv_path.write_text(header)  # header only -- simulates an empty/failed fetch
    result = sync_bookings(db_session)

    assert result.removed == 0
    assert db_session.query(Booking).filter(Booking.external_id == "R-9").count() == 1


def test_sync_never_overwrites_manual_billing_corrections(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")
    sync_bookings(db_session)

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1001").first()
    other_cabin = Cabin(name="Corrected Cabin")
    db_session.add(other_cabin)
    db_session.flush()
    booking.cabin_override_id = other_cabin.id
    booking.check_out_override = date(2026, 7, 1)
    booking.skip_cleaning_fee = True
    booking.override_note = "guest left early"
    db_session.commit()

    sync_bookings(db_session)

    db_session.refresh(booking)
    assert booking.cabin_override_id == other_cabin.id
    assert booking.check_out_override == date(2026, 7, 1)
    assert booking.skip_cleaning_fee is True
    assert booking.override_note == "guest left early"


def test_holiday_stay_gets_holiday_cleaning_rate_after_sync(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")
    sync_bookings(db_session)

    from app.fees import calculate_booking_fees

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1005").first()
    fees = calculate_booking_fees(booking)
    assert fees.is_holiday_cleaning is True
    assert fees.cleaning_fee == 40.0


def test_sync_syncs_a_cancelled_booking_with_net_paid_revenue_and_no_landowner_fees(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", "data/sample_bookings.csv")
    sync_bookings(db_session)

    from app.fees import calculate_booking_fees

    # R-1007 in the sample CSV is "cancelled": total=150.00, received=0.00, net_paid=0.00.
    booking = db_session.query(Booking).filter(Booking.external_id == "R-1007").first()
    assert booking is not None
    assert booking.total_price == 0.0  # NET_PAID, not the original TOTAL
    assert booking.skip_landowner_fees is True

    fees = calculate_booking_fees(booking)
    assert fees.overnight_fee == 0.0
    assert fees.cleaning_fee == 0.0


def test_sync_syncs_a_pending_payment_booking_with_received_revenue_and_normal_fees(db_session, monkeypatch, tmp_path):
    csv_path = tmp_path / "bookings.csv"
    header = "reference,state,customer_first_name,customer_last_name,products,start_on,end_on,total,received,net_paid\n"
    row = "R-20,pending_payment,Ana,Costa,Cabin 1,2026-08-01,2026-08-04,300.00,150.00,0.00\n"
    csv_path.write_text(header + row)
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "local_csv")
    monkeypatch.setattr("app.sheets_sync.settings.sheets_local_csv_path", str(csv_path))

    sync_bookings(db_session)

    from app.fees import calculate_booking_fees

    booking = db_session.query(Booking).filter(Booking.external_id == "R-20").first()
    assert booking is not None
    assert booking.total_price == 150.0  # RECEIVED, not the full TOTAL
    assert booking.skip_landowner_fees is False  # still a normal, billable stay

    fees = calculate_booking_fees(booking)
    assert fees.nights == 3
    assert fees.overnight_fee == round(3 * 19.8, 2)
