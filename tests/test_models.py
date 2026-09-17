from datetime import date

from app.models import Booking, Cabin


def _booking(db, check_in, check_out, cabin_name="Santiago"):
    cabin = Cabin(name=cabin_name)
    db.add(cabin)
    db.flush()
    booking = Booking(external_id="X1", cabin_id=cabin.id, check_in=check_in, check_out=check_out)
    db.add(booking)
    db.commit()
    return booking


def test_effective_cabin_defaults_to_synced_cabin(db_session):
    booking = _booking(db_session, date(2026, 9, 1), date(2026, 9, 3))
    assert booking.effective_cabin.name == "Santiago"


def test_effective_cabin_uses_override_when_set(db_session):
    booking = _booking(db_session, date(2026, 9, 1), date(2026, 9, 3))
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    booking.cabin_override_id = olivia.id
    db_session.commit()
    assert booking.effective_cabin.name == "Olivia"
    assert booking.cabin.name == "Santiago"  # the synced value is preserved


def test_effective_check_out_defaults_to_synced_check_out(db_session):
    booking = _booking(db_session, date(2026, 9, 1), date(2026, 9, 5))
    assert booking.effective_check_out == date(2026, 9, 5)
    assert booking.nights == 4


def test_effective_check_out_uses_override_when_set(db_session):
    booking = _booking(db_session, date(2026, 9, 1), date(2026, 9, 5))
    booking.check_out_override = date(2026, 9, 3)
    db_session.commit()
    assert booking.effective_check_out == date(2026, 9, 3)
    assert booking.nights == 2
    assert booking.check_out == date(2026, 9, 5)  # the synced value is preserved


def test_skip_landowner_fees_false_by_default():
    booking = Booking(status="completed")
    assert booking.skip_landowner_fees is False


def test_skip_landowner_fees_true_for_manual_no_show_override():
    booking = Booking(status="completed", skip_cleaning_fee=True)
    assert booking.skip_landowner_fees is True


def test_skip_landowner_fees_true_for_cancelled_status():
    booking = Booking(status="cancelled")
    assert booking.skip_landowner_fees is True


def test_skip_landowner_fees_false_for_pending_payment_status():
    booking = Booking(status="pending_payment")
    assert booking.skip_landowner_fees is False
