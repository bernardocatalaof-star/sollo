from datetime import date

from app.models import Booking, Cabin
from app.routers.bookings import clear_booking_override, query_bookings, set_booking_override


def _make_booking(db, external_id, check_in, check_out, booked_at=None):
    cabin = db.query(Cabin).filter(Cabin.name == "Cabin 1").first()
    if cabin is None:
        cabin = Cabin(name="Cabin 1")
        db.add(cabin)
        db.flush()
    booking = Booking(
        external_id=external_id,
        cabin_id=cabin.id,
        guest_name="Guest",
        check_in=check_in,
        check_out=check_out,
        booked_at=booked_at,
        total_price=100.0,
        status="completed",
    )
    db.add(booking)
    db.commit()
    return booking


def test_query_bookings_defaults_to_check_in_desc(db_session):
    _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 3))
    _make_booking(db_session, "B", date(2026, 8, 10), date(2026, 8, 12))

    bookings, sort, order = query_bookings(db_session)

    assert sort == "check_in"
    assert order == "desc"
    assert [b.external_id for b in bookings] == ["B", "A"]


def test_query_bookings_sorts_by_check_out_ascending(db_session):
    _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 12))
    _make_booking(db_session, "B", date(2026, 8, 10), date(2026, 8, 3))

    bookings, sort, order = query_bookings(db_session, sort="check_out", order="asc")

    assert sort == "check_out"
    assert order == "asc"
    assert [b.external_id for b in bookings] == ["B", "A"]


def test_query_bookings_sorts_by_booked_at(db_session):
    _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 3), booked_at=date(2026, 7, 20))
    _make_booking(db_session, "B", date(2026, 8, 10), date(2026, 8, 12), booked_at=date(2026, 7, 5))

    bookings, sort, order = query_bookings(db_session, sort="booked_at", order="asc")

    assert sort == "booked_at"
    assert order == "asc"
    assert [b.external_id for b in bookings] == ["B", "A"]


def test_query_bookings_rejects_unknown_sort_column(db_session):
    _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 3))

    _, sort, order = query_bookings(db_session, sort="total_price", order="asc")

    assert sort == "check_in"
    assert order == "asc"


def test_query_bookings_filters_by_check_in_range(db_session):
    _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 3))
    _make_booking(db_session, "B", date(2026, 8, 10), date(2026, 8, 12))
    _make_booking(db_session, "C", date(2026, 8, 20), date(2026, 8, 22))

    bookings, _, _ = query_bookings(
        db_session, check_in_from=date(2026, 8, 5), check_in_to=date(2026, 8, 15)
    )

    assert [b.external_id for b in bookings] == ["B"]


def test_query_bookings_filters_by_check_out_range(db_session):
    _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 3))
    _make_booking(db_session, "B", date(2026, 8, 10), date(2026, 8, 12))

    bookings, _, _ = query_bookings(
        db_session, check_out_from=date(2026, 8, 4), check_out_to=date(2026, 8, 30)
    )

    assert [b.external_id for b in bookings] == ["B"]


def test_set_booking_override_saves_cabin_checkout_and_note(db_session):
    booking = _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 5))
    other_cabin = Cabin(name="Cabin 2")
    db_session.add(other_cabin)
    db_session.flush()

    set_booking_override(
        booking.id,
        cabin_override_id=str(other_cabin.id),
        check_out_override="2026-08-03",
        skip_cleaning_fee="1",
        override_note="left early",
        db=db_session,
    )

    db_session.refresh(booking)
    assert booking.cabin_override_id == other_cabin.id
    assert booking.check_out_override == date(2026, 8, 3)
    assert booking.skip_cleaning_fee is True
    assert booking.override_note == "left early"


def test_set_booking_override_with_blank_fields_clears_overrides(db_session):
    booking = _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 5))
    booking.check_out_override = date(2026, 8, 3)
    booking.skip_cleaning_fee = True
    db_session.commit()

    set_booking_override(
        booking.id,
        cabin_override_id="",
        check_out_override="",
        skip_cleaning_fee="",
        override_note="",
        db=db_session,
    )

    db_session.refresh(booking)
    assert booking.cabin_override_id is None
    assert booking.check_out_override is None
    assert booking.skip_cleaning_fee is False


def test_clear_booking_override_resets_all_fields(db_session):
    booking = _make_booking(db_session, "A", date(2026, 8, 1), date(2026, 8, 5))
    other_cabin = Cabin(name="Cabin 2")
    db_session.add(other_cabin)
    db_session.flush()
    booking.cabin_override_id = other_cabin.id
    booking.check_out_override = date(2026, 8, 3)
    booking.skip_cleaning_fee = True
    booking.override_note = "left early"
    db_session.commit()

    clear_booking_override(booking.id, db=db_session)

    db_session.refresh(booking)
    assert booking.cabin_override_id is None
    assert booking.check_out_override is None
    assert booking.skip_cleaning_fee is False
    assert booking.override_note == ""
