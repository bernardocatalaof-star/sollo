"""Weekly operations briefing sent over WhatsApp (see app/whatsapp.py) as TWO
separate messages, covering the Monday-Sunday week following the Sunday
night it's sent:

  - Cleanings needed: which cabins need cleaning on which day. Cleanings only
    happen Monday, Wednesday or Friday -- a checkout on any other day rolls
    forward to the next one of those days (see _next_cleaning_day). A
    no-show or cancelled booking (Booking.skip_landowner_fees) never needed
    cleaning, so it's excluded.
  - Notes to know in advance: every Issues & Occurrences note on a booking
    CHECKING IN that week, surfaced before the guest arrives rather than
    discovered after the fact.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import Booking

_WEEKDAY_NAMES_PT = [
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
    "Sexta-feira", "Sábado", "Domingo",
]


def weekday_name_pt(d: date) -> str:
    return _WEEKDAY_NAMES_PT[d.weekday()]


def next_week_bounds(sunday: date) -> tuple[date, date]:
    """(Monday, Sunday) of the week following the given Sunday -- the week a
    briefing sent that night reports on."""
    week_start = sunday + timedelta(days=1)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def current_week_start(today: date) -> date:
    """Monday of the calendar week containing `today`."""
    return today - timedelta(days=today.weekday())


# Cleanings only happen Monday(0), Wednesday(2) or Friday(4) -- a checkout on
# any other weekday rolls forward to the next one of those days. A checkout
# that already falls on one of them needs no rolling (offset 0).
_NEXT_CLEANING_DAY_OFFSET = {0: 0, 1: 1, 2: 0, 3: 1, 4: 0, 5: 2, 6: 1}


def _next_cleaning_day(checkout: date) -> date:
    return checkout + timedelta(days=_NEXT_CLEANING_DAY_OFFSET[checkout.weekday()])


@dataclass
class DayCleanings:
    day: date
    cabin_names: list[str] = field(default_factory=list)


def cleanings_this_week(db: Session, week_start: date, week_end: date) -> list[DayCleanings]:
    effective_check_out = func.coalesce(Booking.check_out_override, Booking.check_out)
    # A checkout up to 2 days before week_start can still roll forward onto a
    # cleaning day inside this week (e.g. a Saturday checkout cleans the
    # following Monday), so the query window has to start earlier than
    # week_start -- the actual per-week filter happens below, on the computed
    # cleaning day, not on the checkout date itself.
    query_start = week_start - timedelta(days=2)
    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.cabin), joinedload(Booking.cabin_override))
        .filter(effective_check_out >= query_start, effective_check_out <= week_end)
        .all()
    )
    by_day: dict[date, list[str]] = {}
    for booking in bookings:
        if booking.skip_landowner_fees:
            continue  # no-show / cancelled -- the cabin was never used, so no cleaning is needed
        cleaning_day = _next_cleaning_day(booking.effective_check_out)
        if not (week_start <= cleaning_day <= week_end):
            continue  # rolled into the previous or next week instead
        by_day.setdefault(cleaning_day, []).append(booking.effective_cabin.name)
    return [DayCleanings(day=d, cabin_names=sorted(names)) for d, names in sorted(by_day.items())]


@dataclass
class UpcomingNote:
    external_id: str
    guest_name: str
    check_in: date
    category: str
    note: str


def upcoming_check_in_notes(db: Session, week_start: date, week_end: date) -> list[UpcomingNote]:
    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.flags))
        .filter(Booking.check_in >= week_start, Booking.check_in <= week_end)
        .order_by(Booking.check_in)
        .all()
    )
    notes = []
    for booking in bookings:
        for flag in booking.flags:
            notes.append(
                UpcomingNote(
                    external_id=booking.external_id,
                    guest_name=booking.guest_name or "Guest",
                    check_in=booking.check_in,
                    category=flag.category,
                    note=flag.note,
                )
            )
    return notes


def format_cleanings_message(db: Session, week_start: date, week_end: date) -> str:
    cleanings = cleanings_this_week(db, week_start, week_end)

    lines = ["Limpezas esta semana:", ""]
    if cleanings:
        for entry in cleanings:
            weekday_name = weekday_name_pt(entry.day)
            lines.append(f"* {weekday_name}: {', '.join(entry.cabin_names)}")
    else:
        lines.append("Sem checkouts agendados esta semana.")

    return "\n".join(lines)


def format_notes_message(db: Session, week_start: date, week_end: date) -> str:
    notes = upcoming_check_in_notes(db, week_start, week_end)

    lines = [f"📝 Sollo — Notas semana {week_start:%d/%m} a {week_end:%d/%m}", ""]
    if notes:
        for n in notes:
            weekday_name = weekday_name_pt(n.check_in)
            lines.append(f"• {n.external_id} — {n.guest_name} (check-in {weekday_name} {n.check_in:%d/%m}): {n.note}")
    else:
        lines.append("Sem notas esta semana.")

    return "\n".join(lines)


LAST_WEEKLY_BRIEFING_SETTING_KEY = "last_weekly_briefing_week_start"


def should_send_weekly_briefing(now: datetime, last_sent_week_start: str | None) -> bool:
    """Pure decision logic (no I/O), kept separate from the scheduling loop so
    it can be unit tested directly: fires once, Sunday night at/after the
    configured hour, and never twice for the same reported week."""
    if now.weekday() != 6:  # Monday=0 .. Sunday=6
        return False
    if now.hour < settings.weekly_briefing_send_hour:
        return False
    week_start, _ = next_week_bounds(now.date())
    return last_sent_week_start != week_start.isoformat()
