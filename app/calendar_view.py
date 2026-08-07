"""Month-grid calendar view: which cabin is occupied by which guest, per day.

Rendered as one week per row, with each stay drawn as a single bar spanning the
nights it covers (clipped at week boundaries) rather than repeated per-day tags --
this reads like a normal calendar/Gantt view instead of a checklist.
"""

import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models import Booking, Cabin

# Specific cabins get a fixed, memorable colour; anything else cycles through the
# fallback palette below (stable as long as the cabin list doesn't change).
_NAMED_COLORS = {
    "santiago": "#4f8cff",  # blue
    "olivia": "#ff6fae",  # pink
}
_PALETTE = [
    "#3ecf8e", "#e8b339", "#a97ff0", "#3ac1c9", "#f0955d",
    "#c774e8", "#6ad1e3", "#8d99ae", "#ef5a5a",
]


def cabin_colors(db: Session) -> dict[int, str]:
    cabins = db.query(Cabin).order_by(Cabin.name).all()
    colors: dict[int, str] = {}
    fallback_idx = 0
    for cabin in cabins:
        named = _NAMED_COLORS.get(cabin.name.strip().lower())
        if named:
            colors[cabin.id] = named
        else:
            colors[cabin.id] = _PALETTE[fallback_idx % len(_PALETTE)]
            fallback_idx += 1
    return colors


@dataclass
class DayCell:
    day: date
    in_month: bool


@dataclass
class Bar:
    booking: Booking
    color: str
    start_col: int  # 0 (Mon) .. 6 (Sun)
    span: int  # number of day-columns this bar covers in this week
    lane: int  # vertical stacking row, for overlapping stays in the same week


@dataclass
class Week:
    days: list[DayCell]
    bars: list[Bar] = field(default_factory=list)

    @property
    def lane_count(self) -> int:
        return max((b.lane for b in self.bars), default=-1) + 1


def month_grid(db: Session, year: int, month: int) -> list[Week]:
    colors = cabin_colors(db)

    month_start = date(year, month, 1)
    next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.cabin))
        .filter(Booking.check_in < next_month_start, Booking.check_out > month_start)
        .order_by(Booking.check_in)
        .all()
    )

    week_dates = _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    weeks = []
    for week in week_dates:
        week_start = week[0]
        week_end_exclusive = week[-1] + timedelta(days=1)

        segments = []
        for booking in bookings:
            overlap_start = max(booking.check_in, week_start)
            overlap_end = min(booking.check_out, week_end_exclusive)
            span = (overlap_end - overlap_start).days
            if span <= 0:
                continue
            start_col = (overlap_start - week_start).days
            segments.append((start_col, span, booking))

        # Greedy lane packing: place each bar in the first lane free at its start
        # column, opening a new lane only when every existing one is still busy.
        segments.sort(key=lambda s: (s[0], -s[1]))
        lane_ends: list[int] = []
        bars = []
        for start_col, span, booking in segments:
            end_col = start_col + span
            lane = next((i for i, lane_end in enumerate(lane_ends) if start_col >= lane_end), None)
            if lane is None:
                lane = len(lane_ends)
                lane_ends.append(end_col)
            else:
                lane_ends[lane] = end_col
            bars.append(
                Bar(
                    booking=booking,
                    color=colors.get(booking.cabin_id, "#8b90a0"),
                    start_col=start_col,
                    span=span,
                    lane=lane,
                )
            )

        days = [DayCell(day=d, in_month=(d.month == month)) for d in week]
        weeks.append(Week(days=days, bars=bars))

    return weeks
