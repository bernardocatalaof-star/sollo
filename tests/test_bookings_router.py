from datetime import date

from app.models import Booking, Cabin
from app.routers.bookings import query_bookings


def _make_booking(db, external_id, check_in, check_out):
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
