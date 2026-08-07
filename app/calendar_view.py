"""Month-grid calendar view: which cabin is occupied by which guest, per day."""

import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session, joinedload

from app.models import Booking, Cabin

# Cycled by cabin name order -- stable as long as the cabin list doesn't change,
# and distinct enough to tell cabins apart at a glance on the grid.
_PALETTE = [
    "#4f8cff", "#e8b339", "#3ecf8e", "#ef5a5a", "#a97ff0",
    "#3ac1c9", "#f0955d", "#c774e8", "#6ad1e3", "#8d99ae",
]


def cabin_colors(db: Session) -> dict[int, str]:
    cabins = db.query(Cabin).order_by(Cabin.name).all()
    return {cabin.id: _PALETTE[i % len(_PALETTE)] for i, cabin in enumerate(cabins)}


@dataclass
class Stay:
    booking: Booking
    color: str


@dataclass
class DayCell:
    day: date
    in_month: bool
    stays: list[Stay] = field(default_factory=list)


def month_grid(db: Session, year: int, month: int) -> list[list[DayCell]]:
    colors = cabin_colors(db)

    month_start = date(year, month, 1)
    next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.cabin))
        .filter(Booking.check_in < next_month_start, Booking.check_out > month_start)
        .order_by(Booking.cabin_id, Booking.check_in)
        .all()
    )

    weeks = _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    grid = []
    for week in weeks:
        row = []
        for day in week:
            stays = [
                Stay(booking=b, color=colors.get(b.cabin_id, "#8b90a0"))
                for b in bookings
                if b.check_in <= day < b.check_out
            ]
            row.append(DayCell(day=day, in_month=(day.month == month), stays=stays))
        grid.append(row)
    return grid
