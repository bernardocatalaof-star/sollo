"""Month-grid calendar view: which cabin is occupied by which guest, per day.

Rendered as one week per row, with each stay drawn as a single bar spanning the
nights it covers (clipped at week boundaries) rather than repeated per-day tags --
this reads like a normal calendar/Gantt view instead of a checklist.
"""

import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import Booking, Cabin

# Specific cabins get a fixed, memorable colour; anything else cycles through the
# fallback palette below (stable as long as the cabin list doesn't change).
_NAMED_COLORS = {
    "santiago": "#4f8cff",  # blue
    "olivia": "#ffa8d0",  # light pink
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
    grid_start: int  # 1-indexed CSS grid line, out of 14 half-day columns per week
    grid_end: int  # 1-indexed CSS grid line (exclusive), out of 14 half-day columns


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

    effective_check_out = func.coalesce(Booking.check_out_override, Booking.check_out)
    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.cabin), joinedload(Booking.cabin_override))
        .filter(Booking.check_in < next_month_start, effective_check_out > month_start)
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
            booking_check_out = booking.effective_check_out
            overlap_start = max(booking.check_in, week_start)
            overlap_end = min(booking_check_out, week_end_exclusive)
            span = (overlap_end - overlap_start).days
            if span <= 0:
                # No full night falls in this week -- but if checkout lands exactly
                # on this week's Monday (e.g. a Fri check-in/Mon check-out stay,
                # all 3 nights in the previous week), it still needs a same-day
                # "checkout stub" here so the bar visibly reaches Monday instead of
                # stopping dead at Sunday's edge.
                if booking_check_out == week_start:
                    segments.append((0, 0, 1, 2, booking))  # first half of Monday
                continue
            start_col = (overlap_start - week_start).days
            end_col = start_col + span
            # A bar only starts/ends mid-cell on the actual check-in/check-out day.
            # If it's a continuation from a previous week, or carries on into the
            # next, it runs edge-to-edge instead -- there's no "half day" to show.
            starts_at_checkin = overlap_start == booking.check_in
            ends_at_checkout = overlap_end == booking_check_out and end_col < 7
            # 14 half-day columns per week (2 per day): a bar that truly starts/ends
            # on check-in/check-out begins or finishes at that day's midpoint;
            # otherwise it runs to the full edge of the column.
            grid_start = 2 * start_col + 2 if starts_at_checkin else 2 * start_col + 1
            grid_end = 2 * end_col + 2 if ends_at_checkout else 2 * end_col + 1
            segments.append((start_col, span, grid_start, grid_end, booking))

        # Greedy lane packing, done in the same half-day GRID units actually
        # rendered (not whole-day units) -- two different bookings that both end
        # their stay on the same day (e.g. a same-day turnover, or two check-outs
        # landing on the same Monday stub) occupy the exact same half-day cell,
        # which whole-day bookkeeping can't tell apart from merely "adjacent".
        segments.sort(key=lambda s: (s[2], -s[3]))
        lane_ends: list[int] = []
        bars = []
        for start_col, span, grid_start, grid_end, booking in segments:
            lane = next((i for i, lane_end in enumerate(lane_ends) if grid_start >= lane_end), None)
            if lane is None:
                lane = len(lane_ends)
                lane_ends.append(grid_end)
            else:
                lane_ends[lane] = grid_end

            bars.append(
                Bar(
                    booking=booking,
                    color=colors.get(booking.cabin_override_id or booking.cabin_id, "#8b90a0"),
                    start_col=start_col,
                    span=span,
                    lane=lane,
                    grid_start=grid_start,
                    grid_end=grid_end,
                )
            )

        days = [DayCell(day=d, in_month=(d.month == month)) for d in week]
        weeks.append(Week(days=days, bars=bars))

    return weeks
