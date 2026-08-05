"""Monthly close-out: landowner payout + revenue/cost/occupancy/profit summary.

Attribution rules (kept simple and consistent with the fee rules):
  - A stay's revenue and landowner fees (land + cleaning) are booked entirely to the
    calendar month of its CHECK-OUT date -- that's when the cleaning charge fires and
    the stay is considered "closed".
  - Occupancy is computed differently: it counts nights that actually fall within the
    month for ANY overlapping stay (even one that checks out next month), so a
    month's occupancy rate reflects the calendar, not the billing bucket.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.fees import calculate_booking_fees
from app.models import Booking, Cabin, Expense


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    end = date(year, month, days_in_month)
    return start, end


def bookings_closing_in_month(db: Session, year: int, month: int) -> list[Booking]:
    start, end = _month_bounds(year, month)
    return (
        db.query(Booking)
        .filter(Booking.check_out >= start, Booking.check_out <= end)
        .order_by(Booking.check_out)
        .all()
    )


@dataclass
class CabinOwed:
    cabin_name: str
    nights: int = 0
    cleanings: int = 0
    overnight_total: float = 0.0
    cleaning_total: float = 0.0

    @property
    def total_owed(self) -> float:
        return round(self.overnight_total + self.cleaning_total, 2)


@dataclass
class LandownerStatement:
    year: int
    month: int
    by_cabin: list[CabinOwed] = field(default_factory=list)

    @property
    def total_owed(self) -> float:
        return round(sum(c.total_owed for c in self.by_cabin), 2)


def landowner_statement(db: Session, year: int, month: int) -> LandownerStatement:
    bookings = bookings_closing_in_month(db, year, month)
    by_cabin: dict[str, CabinOwed] = {}

    for booking in bookings:
        fees = calculate_booking_fees(booking)
        entry = by_cabin.setdefault(booking.cabin.name, CabinOwed(cabin_name=booking.cabin.name))
        entry.nights += fees.nights
        entry.cleanings += 1
        entry.overnight_total = round(entry.overnight_total + fees.overnight_fee, 2)
        entry.cleaning_total = round(entry.cleaning_total + fees.cleaning_fee, 2)

    return LandownerStatement(year=year, month=month, by_cabin=sorted(by_cabin.values(), key=lambda c: c.cabin_name))


@dataclass
class FinancialSummary:
    year: int
    month: int
    total_revenue: float = 0.0
    total_landowner_costs: float = 0.0
    total_supply_costs: float = 0.0
    stays_closed: int = 0
    nights_occupied: int = 0
    nights_available: int = 0
    flagged_stays: int = 0

    @property
    def total_costs(self) -> float:
        return round(self.total_landowner_costs + self.total_supply_costs, 2)

    @property
    def profit(self) -> float:
        return round(self.total_revenue - self.total_costs, 2)

    @property
    def occupancy_rate(self) -> float:
        if self.nights_available == 0:
            return 0.0
        return round(self.nights_occupied / self.nights_available, 4)


def financial_summary(db: Session, year: int, month: int) -> FinancialSummary:
    start, end = _month_bounds(year, month)
    summary = FinancialSummary(year=year, month=month)

    closing_bookings = bookings_closing_in_month(db, year, month)
    summary.stays_closed = len(closing_bookings)
    summary.total_revenue = round(sum(b.total_price for b in closing_bookings), 2)
    summary.flagged_stays = sum(1 for b in closing_bookings if b.flags)

    statement = landowner_statement(db, year, month)
    summary.total_landowner_costs = statement.total_owed

    supply_total = (
        db.query(Expense).filter(Expense.month == start).all()
    )
    summary.total_supply_costs = round(sum(e.amount for e in supply_total), 2)

    # A night "belongs" to the month its start date falls in, so the overlap window
    # for counting nights must use an EXCLUSIVE end (first day of next month) --
    # unlike `end` above, which is the inclusive last calendar day used for billing.
    next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    overlapping = (
        db.query(Booking)
        .filter(Booking.check_in < next_month_start, Booking.check_out > start)
        .all()
    )
    nights = 0
    for booking in overlapping:
        overlap_start = max(booking.check_in, start)
        overlap_end = min(booking.check_out, next_month_start)
        nights += max((overlap_end - overlap_start).days, 0)
    summary.nights_occupied = nights

    days_in_month = calendar.monthrange(year, month)[1]
    cabin_count = db.query(Cabin).count()
    summary.nights_available = days_in_month * cabin_count

    return summary
