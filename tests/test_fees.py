from datetime import date

from app.fees import calculate_booking_fees, is_public_holiday
from app.models import Booking, Cabin


def _booking(check_in: date, check_out: date) -> Booking:
    booking = Booking(cabin=Cabin(name="Cabin 1"), check_in=check_in, check_out=check_out)
    return booking


def test_nights_occupied_excludes_checkout_day():
    booking = _booking(date(2026, 8, 1), date(2026, 8, 4))
    fees = calculate_booking_fees(booking)
    assert fees.nights == 3


def test_overnight_fee_is_per_night_rate():
    booking = _booking(date(2026, 8, 1), date(2026, 8, 4))
    fees = calculate_booking_fees(booking)
    assert fees.overnight_fee == round(3 * 19.8, 2)


def test_standard_cleaning_fee_on_non_holiday():
    # 2026-08-04 is not a Portuguese public holiday.
    booking = _booking(date(2026, 8, 1), date(2026, 8, 4))
    fees = calculate_booking_fees(booking)
    assert fees.cleaning_fee == 33.0
    assert fees.is_holiday_cleaning is False


def test_holiday_cleaning_fee_on_portuguese_public_holiday():
    # 2026-08-15 is "Assunção de Nossa Senhora" (Assumption Day), a PT public holiday.
    assert is_public_holiday(date(2026, 8, 15)) is True
    booking = _booking(date(2026, 8, 14), date(2026, 8, 15))
    fees = calculate_booking_fees(booking)
    assert fees.cleaning_fee == 40.0
    assert fees.is_holiday_cleaning is True


def test_total_owed_combines_overnight_and_cleaning():
    booking = _booking(date(2026, 8, 1), date(2026, 8, 4))
    fees = calculate_booking_fees(booking)
    assert fees.total_owed == round(fees.overnight_fee + fees.cleaning_fee, 2)


def test_zero_night_stay_has_no_overnight_fee():
    booking = _booking(date(2026, 8, 1), date(2026, 8, 1))
    fees = calculate_booking_fees(booking)
    assert fees.nights == 0
    assert fees.overnight_fee == 0.0
