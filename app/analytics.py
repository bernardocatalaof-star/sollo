"""Monthly close-out: landowner payout + revenue/cost/occupancy/profit summary.

Attribution rules:
  - Revenue is booked to the calendar month of a stay's CHECK-OUT date -- that's
    when the platform/sheet records the payment as settled.
  - Land (overnight) fee is split across calendar months by nights actually slept
    in each one -- a stay spanning a month boundary owes part of its land fee to
    each month, matching a night-by-night occupancy log.
  - Cleaning fee is booked entirely to the calendar month of CHECK-OUT, since
    that's when the clean (and the charge) actually happens.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.fees import calculate_booking_fees
from app.models import Booking, Cabin, Expense, ExtraRevenue


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    end = date(year, month, days_in_month)
    return start, end


def bookings_closing_in_month(db: Session, year: int, month: int) -> list[Booking]:
    start, end = _month_bounds(year, month)
    return (
        db.query(Booking)
        .options(joinedload(Booking.cabin))
        .filter(Booking.check_out >= start, Booking.check_out <= end)
        .order_by(Booking.check_out)
        .all()
    )


def bookings_starting_in_month(db: Session, year: int, month: int) -> list[Booking]:
    start, end = _month_bounds(year, month)
    return (
        db.query(Booking)
        .options(joinedload(Booking.cabin))
        .filter(Booking.check_in >= start, Booking.check_in <= end)
        .order_by(Booking.check_in)
        .all()
    )


def _nights_in_month(db: Session, year: int, month: int) -> list[tuple[Booking, int]]:
    """Bookings overlapping the month, paired with how many of their nights fall
    inside it. A night "belongs" to the month its start date falls in, so the
    overlap window uses an EXCLUSIVE end (first day of next month)."""
    start, _ = _month_bounds(year, month)
    next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    overlapping = (
        db.query(Booking)
        .options(joinedload(Booking.cabin))
        .filter(Booking.check_in < next_month_start, Booking.check_out > start)
        .all()
    )
    result = []
    for booking in overlapping:
        overlap_start = max(booking.check_in, start)
        overlap_end = min(booking.check_out, next_month_start)
        nights = max((overlap_end - overlap_start).days, 0)
        if nights:
            result.append((booking, nights))
    return result


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
    by_cabin: dict[str, CabinOwed] = {}

    # Land (overnight) fee: nights actually slept in THIS calendar month.
    for booking, nights_in_month in _nights_in_month(db, year, month):
        entry = by_cabin.setdefault(booking.cabin.name, CabinOwed(cabin_name=booking.cabin.name))
        entry.nights += nights_in_month
        entry.overnight_total = round(
            entry.overnight_total + nights_in_month * settings.overnight_fee_per_night, 2
        )

    # Cleaning fee: one per stay, charged when the clean happens -- the calendar
    # month containing check-out.
    for booking in bookings_closing_in_month(db, year, month):
        fees = calculate_booking_fees(booking)
        entry = by_cabin.setdefault(booking.cabin.name, CabinOwed(cabin_name=booking.cabin.name))
        entry.cleanings += 1
        entry.cleaning_total = round(entry.cleaning_total + fees.cleaning_fee, 2)

    return LandownerStatement(year=year, month=month, by_cabin=sorted(by_cabin.values(), key=lambda c: c.cabin_name))


@dataclass
class CleaningEntry:
    date: date
    guest_name: str
    amount: float


@dataclass
class NightEntry:
    date: date
    guest_name: str


@dataclass
class CabinJustification:
    cabin_name: str
    cleanings: list[CleaningEntry] = field(default_factory=list)
    nights: list[NightEntry] = field(default_factory=list)


@dataclass
class LandownerJustification:
    year: int
    month: int
    by_cabin: list[CabinJustification] = field(default_factory=list)


def landowner_justification(db: Session, year: int, month: int) -> LandownerJustification:
    """Day-by-day backup for the landowner statement: every individual cleaning
    date and every individual night-slept date this month, per cabin -- so a
    specific charge can be pointed at a specific guest/date if questioned."""
    by_cabin: dict[str, CabinJustification] = {}

    for booking, nights_in_month in _nights_in_month(db, year, month):
        entry = by_cabin.setdefault(booking.cabin.name, CabinJustification(cabin_name=booking.cabin.name))
        month_start, _ = _month_bounds(year, month)
        next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        overlap_start = max(booking.check_in, month_start)
        overlap_end = min(booking.check_out, next_month_start)
        d = overlap_start
        while d < overlap_end:
            entry.nights.append(NightEntry(date=d, guest_name=booking.guest_name))
            d += timedelta(days=1)

    for booking in bookings_closing_in_month(db, year, month):
        fees = calculate_booking_fees(booking)
        entry = by_cabin.setdefault(booking.cabin.name, CabinJustification(cabin_name=booking.cabin.name))
        entry.cleanings.append(
            CleaningEntry(date=booking.check_out, guest_name=booking.guest_name, amount=fees.cleaning_fee)
        )

    for entry in by_cabin.values():
        entry.nights.sort(key=lambda n: n.date)
        entry.cleanings.sort(key=lambda c: c.date)

    return LandownerJustification(
        year=year, month=month, by_cabin=sorted(by_cabin.values(), key=lambda c: c.cabin_name)
    )


@dataclass
class FixedCosts:
    """Recurring monthly operating costs, deducted from Profit alongside the
    landowner and supply costs. Website costs mirror a typical payment
    processor: a flat monthly fee plus a percentage + flat fee per transaction,
    charged on bookings synced from the Sheet (not manual Extra Revenue entries),
    attributed to the same month as Revenue (checkout). Check-in supplies (e.g. a
    polaroid handed to each guest) are charged per stay that CHECKS IN this
    month instead -- that's when the item is actually given out."""

    website_fixed: float = 0.0
    website_percentage: float = 0.0
    website_per_transaction: float = 0.0
    tech_tools: float = 0.0
    accounting: float = 0.0
    checkin_supplies: float = 0.0

    @property
    def website_total(self) -> float:
        return round(self.website_fixed + self.website_percentage + self.website_per_transaction, 2)

    @property
    def total(self) -> float:
        return round(self.website_total + self.tech_tools + self.accounting + self.checkin_supplies, 2)


def fixed_costs_for_month(db: Session, year: int, month: int) -> FixedCosts:
    closing_bookings = bookings_closing_in_month(db, year, month)
    net_paid_total = sum(b.total_price for b in closing_bookings)
    starting_bookings = bookings_starting_in_month(db, year, month)

    return FixedCosts(
        website_fixed=settings.website_fixed_fee,
        website_percentage=round(net_paid_total * settings.website_percentage_fee, 2),
        website_per_transaction=round(len(closing_bookings) * settings.website_per_transaction_fee, 2),
        tech_tools=settings.tech_tools_fee,
        accounting=settings.accounting_fee,
        checkin_supplies=round(len(starting_bookings) * settings.checkin_supplies_fee, 2),
    )


@dataclass
class FinancialSummary:
    year: int
    month: int
    booking_revenue: float = 0.0
    extra_revenue: float = 0.0
    total_landowner_costs: float = 0.0
    total_supply_costs: float = 0.0
    fixed_costs: FixedCosts = field(default_factory=FixedCosts)
    stays_closed: int = 0
    nights_occupied: int = 0
    nights_available: int = 0
    flagged_stays: int = 0

    @property
    def total_revenue(self) -> float:
        return round(self.booking_revenue + self.extra_revenue, 2)

    @property
    def total_costs(self) -> float:
        return round(self.total_landowner_costs + self.total_supply_costs + self.fixed_costs.total, 2)

    @property
    def profit(self) -> float:
        return round(self.total_revenue - self.total_costs, 2)

    @property
    def occupancy_rate(self) -> float:
        if self.nights_available == 0:
            return 0.0
        return round(self.nights_occupied / self.nights_available, 4)


def financial_summary(db: Session, year: int, month: int) -> FinancialSummary:
    start, _ = _month_bounds(year, month)
    summary = FinancialSummary(year=year, month=month)

    closing_bookings = bookings_closing_in_month(db, year, month)
    summary.stays_closed = len(closing_bookings)
    summary.booking_revenue = round(sum(b.total_price for b in closing_bookings), 2)
    summary.flagged_stays = sum(1 for b in closing_bookings if b.flags)

    extra_revenue_entries = db.query(ExtraRevenue).filter(ExtraRevenue.month == start).all()
    summary.extra_revenue = round(sum(e.amount for e in extra_revenue_entries), 2)

    statement = landowner_statement(db, year, month)
    summary.total_landowner_costs = statement.total_owed

    supply_total = (
        db.query(Expense).filter(Expense.month == start).all()
    )
    summary.total_supply_costs = round(sum(e.amount for e in supply_total), 2)

    summary.fixed_costs = fixed_costs_for_month(db, year, month)

    summary.nights_occupied = sum(nights for _, nights in _nights_in_month(db, year, month))

    days_in_month = calendar.monthrange(year, month)[1]
    cabin_count = db.query(Cabin).count()
    summary.nights_available = days_in_month * cabin_count

    return summary


def profit_year_to_date(db: Session, year: int, month: int) -> float:
    """Sum of each month's Profit from January through `month` of `year`."""
    return round(sum(financial_summary(db, year, m).profit for m in range(1, month + 1)), 2)


@dataclass
class SalesSummary:
    year: int
    month: int
    total_amount: float = 0.0
    count: int = 0


def sales_in_month(db: Session, year: int, month: int) -> SalesSummary:
    """Bookings actually MADE (reservation date, not check-in/check-out) this
    month -- a different question from Revenue, which is booked to the
    checkout month regardless of when the reservation happened."""
    start, end = _month_bounds(year, month)
    bookings = (
        db.query(Booking)
        .filter(Booking.booked_at.isnot(None), Booking.booked_at >= start, Booking.booked_at <= end)
        .all()
    )
    return SalesSummary(
        year=year,
        month=month,
        total_amount=round(sum(b.total_price for b in bookings), 2),
        count=len(bookings),
    )


def _activity_month_range(db: Session) -> tuple[tuple[int, int], tuple[int, int]]:
    """(start_year, start_month), (end_year, end_month) spanning every month with
    any booking or Extra Revenue activity -- from the earliest entry on record
    through the latest, which naturally includes future months for stays already
    booked ahead. Falls back to just the current month when there's no data yet."""
    from sqlalchemy import func

    min_checkout = db.query(func.min(Booking.check_out)).scalar()
    max_checkout = db.query(func.max(Booking.check_out)).scalar()
    min_extra = db.query(func.min(ExtraRevenue.month)).scalar()
    max_extra = db.query(func.max(ExtraRevenue.month)).scalar()

    starts = [d for d in (min_checkout, min_extra) if d]
    ends = [d for d in (max_checkout, max_extra) if d]

    if not starts:
        today = date.today()
        return (today.year, today.month), (today.year, today.month)

    start, end = min(starts), max(ends)
    return (start.year, start.month), (end.year, end.month)


@dataclass
class MonthRevenue:
    year: int
    month: int
    label: str
    amount: float


def revenue_by_month(db: Session) -> list[MonthRevenue]:
    """Revenue (bookings + extra) for every month with any activity."""
    (start_year, start_month), (end_year, end_month) = _activity_month_range(db)

    results = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        month_start, _ = _month_bounds(y, m)
        booking_revenue = sum(b.total_price for b in bookings_closing_in_month(db, y, m))
        extra_revenue = sum(
            e.amount for e in db.query(ExtraRevenue).filter(ExtraRevenue.month == month_start).all()
        )
        results.append(
            MonthRevenue(
                year=y, month=m, label=date(y, m, 1).strftime("%b %Y"),
                amount=round(booking_revenue + extra_revenue, 2),
            )
        )
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return results


@dataclass
class MonthProfit:
    year: int
    month: int
    label: str
    amount: float


def profit_by_month(db: Session) -> list[MonthProfit]:
    """Profit (Revenue minus all costs, including fixed monthly costs) for every
    month with any activity -- same range as revenue_by_month. Since fixed costs
    apply every month regardless of bookings, a month with no activity still
    shows up as a loss equal to that month's fixed costs."""
    (start_year, start_month), (end_year, end_month) = _activity_month_range(db)

    results = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        profit = financial_summary(db, y, m).profit
        results.append(MonthProfit(year=y, month=m, label=date(y, m, 1).strftime("%b %Y"), amount=profit))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return results


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, total % 12 + 1


_COST_SHARE_COLORS = {
    "Landowner": "#4f8cff",
    "Tech": "#3ac1c9",
    "Supplies": "#e8b339",
    "Maintenance": "#a97ff0",
    "Staff": "#f0955d",
    "Other": "#8d99ae",
}
_COST_SHARE_FALLBACK_PALETTE = ["#3ecf8e", "#c774e8", "#6ad1e3", "#ef5a5a"]


@dataclass
class CostShare:
    label: str
    amount: float
    color: str
    pct: float  # percentage of that month's Revenue -- can push the stack past
    # 100% in a loss month, since costs aren't capped to what Revenue can cover


@dataclass
class MonthCostBreakdown:
    year: int
    month: int
    label: str
    revenue: float
    shares: list[CostShare]  # every cost category that reduces Profit
    profit: float  # revenue minus the shares above -- always exact, can be negative
    profit_pct: float


def cost_breakdown_by_month(db: Session, year: int, month: int, count: int = 6) -> list[MonthCostBreakdown]:
    """Last `count` months (ending at year/month): each month's Revenue split into
    every cost category that reduces Profit, plus Profit itself, as percentages
    that always add up to exactly 100% -- Landowner and Tech (the always-on fixed
    costs: website, tech tools, accounting, check-in supplies) come from the
    automatic calculations; every OTHER category is whatever Ledger Expense
    categories actually have entries that month (Supplies, Maintenance, Staff,
    Other, or any custom category), so nothing is silently left out."""
    fallback_idx = 0
    fallback_colors: dict[str, str] = {}

    def _color_for(label: str) -> str:
        nonlocal fallback_idx
        if label in _COST_SHARE_COLORS:
            return _COST_SHARE_COLORS[label]
        if label not in fallback_colors:
            fallback_colors[label] = _COST_SHARE_FALLBACK_PALETTE[fallback_idx % len(_COST_SHARE_FALLBACK_PALETTE)]
            fallback_idx += 1
        return fallback_colors[label]

    results = []
    for i in range(-(count - 1), 1):
        y, m = _shift_month(year, month, i)
        summary = financial_summary(db, y, m)
        month_start, _ = _month_bounds(y, m)
        revenue = summary.total_revenue

        category_totals: dict[str, float] = {}
        for expense in db.query(Expense).filter(Expense.month == month_start).all():
            label = expense.category.title()
            category_totals[label] = category_totals.get(label, 0.0) + expense.amount

        amounts = {"Landowner": summary.total_landowner_costs, "Tech": summary.fixed_costs.total}
        for label, total in sorted(category_totals.items()):
            amounts[label] = round(total, 2)

        def _pct(amount: float) -> float:
            return round(amount / revenue * 100, 1) if revenue else 0.0

        shares = [
            CostShare(label=label, amount=amount, color=_color_for(label), pct=_pct(amount))
            for label, amount in amounts.items()
        ]
        # By construction (landowner + every Expense category + fixed costs are
        # exactly the terms financial_summary() subtracts from Revenue), this
        # always equals the real Profit shown elsewhere -- not a separate figure.
        profit = summary.profit

        results.append(
            MonthCostBreakdown(
                year=y, month=m, label=date(y, m, 1).strftime("%b %Y"),
                revenue=revenue, shares=shares, profit=profit, profit_pct=_pct(profit),
            )
        )
    return results


@dataclass
class CabinRate:
    cabin_name: str
    color: str
    rate: float


@dataclass
class MonthCabinOccupancy:
    year: int
    month: int
    label: str
    cabins: list[CabinRate]


def occupancy_by_cabin_and_month(
    db: Session, year: int, month: int, months_before: int = 3, months_after: int = 3
) -> list[MonthCabinOccupancy]:
    """Per-cabin occupancy rate for the `months_before` months up to and
    including year/month, plus the `months_after` months following it."""
    from app.calendar_view import cabin_colors

    colors = cabin_colors(db)
    cabins = db.query(Cabin).order_by(Cabin.name).all()

    results = []
    for i in range(-(months_before - 1), months_after + 1):
        y, m = _shift_month(year, month, i)
        days_in_month = calendar.monthrange(y, m)[1]

        nights_by_cabin = {cabin.id: 0 for cabin in cabins}
        for booking, nights in _nights_in_month(db, y, m):
            if booking.cabin_id in nights_by_cabin:
                nights_by_cabin[booking.cabin_id] += nights

        cabin_rates = [
            CabinRate(
                cabin_name=cabin.name,
                color=colors.get(cabin.id, "#8b90a0"),
                rate=(nights_by_cabin[cabin.id] / days_in_month) if days_in_month else 0.0,
            )
            for cabin in cabins
        ]
        results.append(
            MonthCabinOccupancy(year=y, month=m, label=date(y, m, 1).strftime("%b %Y"), cabins=cabin_rates)
        )
    return results
