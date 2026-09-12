"""Land (overnight) fee and cleaning fee calculations owed to the landowner.

Rules (per cabin, per stay):
  - overnight fee: settings.overnight_fee_per_night EUR x nights occupied
      nights occupied = (check_out - check_in) in days
  - cleaning fee: settings.cleaning_fee_standard EUR, charged once per stay at checkout,
      or settings.cleaning_fee_holiday EUR if the checkout date falls on a public holiday.
  - a booking marked as a no-show (Booking.skip_cleaning_fee) owes neither fee -- the
      cabin was never actually used, even though the booking wasn't cancelled/refunded
      and its revenue still counts (that's tracked on the booking itself, not here).

BookingFees here always reflects the WHOLE stay (used for the per-booking display on
the Bookings page). For the monthly landowner statement, app/analytics.py splits the
overnight fee across calendar months by nights actually slept in each one, while still
billing the cleaning fee entirely to the checkout month -- see its module docstring.
"""

from dataclasses import dataclass
from datetime import date

import holidays

from app.config import settings
from app.models import Booking

_holiday_cache: dict[int, holidays.HolidayBase] = {}


def _holidays_for_year(year: int) -> holidays.HolidayBase:
    if year not in _holiday_cache:
        _holiday_cache[year] = holidays.country_holidays(settings.holiday_country, years=year)
    return _holiday_cache[year]


def is_public_holiday(day: date) -> bool:
    return day in _holidays_for_year(day.year)


@dataclass
class BookingFees:
    nights: int
    overnight_fee: float
    cleaning_fee: float
    is_holiday_cleaning: bool

    @property
    def total_owed(self) -> float:
        return round(self.overnight_fee + self.cleaning_fee, 2)


def calculate_booking_fees(booking: Booking) -> BookingFees:
    nights = booking.nights

    if booking.skip_cleaning_fee:
        # No-show: the guest never used the cabin, so neither the cleaning fee
        # nor the land (overnight) fee is owed to the landowner -- only the
        # booking's own revenue still counts (handled separately, not here).
        return BookingFees(nights=nights, overnight_fee=0.0, cleaning_fee=0.0, is_holiday_cleaning=False)

    overnight_fee = round(nights * settings.overnight_fee_per_night, 2)
    holiday_cleaning = is_public_holiday(booking.effective_check_out)
    cleaning_fee = settings.cleaning_fee_holiday if holiday_cleaning else settings.cleaning_fee_standard

    return BookingFees(
        nights=nights,
        overnight_fee=overnight_fee,
        cleaning_fee=cleaning_fee,
        is_holiday_cleaning=holiday_cleaning,
    )
