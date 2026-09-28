from datetime import date, datetime

from app.models import Booking, Cabin, StayFlag
from app.weekly_briefing import (
    cleanings_this_week,
    format_cleanings_message,
    format_notes_message,
    next_week_bounds,
    should_send_weekly_briefing,
    upcoming_check_in_notes,
)


def test_next_week_bounds_returns_the_monday_through_sunday_after_the_given_sunday():
    # 2026-10-04 is a Sunday.
    week_start, week_end = next_week_bounds(date(2026, 10, 4))
    assert week_start == date(2026, 10, 5)
    assert week_end == date(2026, 10, 11)


def test_cleanings_this_week_groups_cabins_by_checkout_day(db_session):
    olivia = Cabin(name="Olivia")
    santiago = Cabin(name="Santiago")
    db_session.add_all([olivia, santiago])
    db_session.flush()
    db_session.add_all(
        [
            Booking(external_id="A", cabin=olivia, guest_name="A",
                    check_in=date(2026, 10, 3), check_out=date(2026, 10, 5), total_price=100),
            Booking(external_id="B", cabin=santiago, guest_name="B",
                    check_in=date(2026, 10, 3), check_out=date(2026, 10, 5), total_price=100),
            Booking(external_id="C", cabin=santiago, guest_name="C",
                    check_in=date(2026, 10, 6), check_out=date(2026, 10, 9), total_price=100),
        ]
    )
    db_session.commit()

    days = cleanings_this_week(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert len(days) == 2
    assert days[0].day == date(2026, 10, 5)
    assert days[0].cabin_names == ["Olivia", "Santiago"]
    assert days[1].day == date(2026, 10, 9)
    assert days[1].cabin_names == ["Santiago"]


def test_cleanings_this_week_excludes_no_show_and_cancelled(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    db_session.add_all(
        [
            Booking(external_id="NOSHOW", cabin=olivia, guest_name="No Show", skip_cleaning_fee=True,
                    check_in=date(2026, 10, 5), check_out=date(2026, 10, 7), total_price=100),
            Booking(external_id="CANCELLED", cabin=olivia, guest_name="Cancelled", status="cancelled",
                    check_in=date(2026, 10, 5), check_out=date(2026, 10, 7), total_price=0),
        ]
    )
    db_session.commit()

    days = cleanings_this_week(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert days == []


def test_cleanings_this_week_respects_the_checkout_override(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    booking = Booking(
        external_id="A", cabin=olivia, guest_name="A",
        check_in=date(2026, 10, 5), check_out=date(2026, 10, 9), total_price=100,
        check_out_override=date(2026, 10, 7),
    )
    db_session.add(booking)
    db_session.commit()

    days = cleanings_this_week(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert len(days) == 1
    assert days[0].day == date(2026, 10, 7)


def test_upcoming_check_in_notes_only_includes_bookings_checking_in_that_week(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    in_week = Booking(external_id="IN", cabin=olivia, guest_name="In Week",
                       check_in=date(2026, 10, 8), check_out=date(2026, 10, 10), total_price=100)
    before_week = Booking(external_id="BEFORE", cabin=olivia, guest_name="Before Week",
                          check_in=date(2026, 9, 20), check_out=date(2026, 9, 22), total_price=100)
    db_session.add_all([in_week, before_week])
    db_session.flush()
    db_session.add_all(
        [
            StayFlag(booking_id=in_week.id, category="note", note="Guest requested extra towels"),
            StayFlag(booking_id=before_week.id, category="note", note="Old note, not relevant"),
        ]
    )
    db_session.commit()

    notes = upcoming_check_in_notes(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert len(notes) == 1
    assert notes[0].external_id == "IN"
    assert notes[0].note == "Guest requested extra towels"


def test_upcoming_check_in_notes_skips_bookings_without_flags(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    db_session.add(
        Booking(external_id="A", cabin=olivia, guest_name="A",
                check_in=date(2026, 10, 8), check_out=date(2026, 10, 10), total_price=100)
    )
    db_session.commit()

    notes = upcoming_check_in_notes(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert notes == []


def test_format_cleanings_message_lists_cabins_by_day(db_session):
    santiago = Cabin(name="Santiago")
    db_session.add(santiago)
    db_session.flush()
    db_session.add(
        Booking(external_id="5C5-M8JL", cabin=santiago, guest_name="Maria Silva",
                check_in=date(2026, 10, 8), check_out=date(2026, 10, 10), total_price=200)
    )
    db_session.commit()

    message = format_cleanings_message(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert message.startswith("Limpezas esta semana:")
    assert "* Sábado: Santiago" in message
    assert "Maria Silva" not in message  # cleanings message is cabin/day only, no guest names
    assert "Notas" not in message  # the two messages are fully separate


def test_format_cleanings_message_shows_fallback_text_when_none(db_session):
    message = format_cleanings_message(db_session, date(2026, 10, 5), date(2026, 10, 11))
    assert "Sem checkouts agendados esta semana." in message


def test_format_notes_message_lists_upcoming_check_ins_with_notes(db_session):
    santiago = Cabin(name="Santiago")
    db_session.add(santiago)
    db_session.flush()
    guest = Booking(external_id="5C5-M8JL", cabin=santiago, guest_name="Maria Silva",
                     check_in=date(2026, 10, 8), check_out=date(2026, 10, 10), total_price=200)
    db_session.add(guest)
    db_session.flush()
    db_session.add(StayFlag(booking_id=guest.id, category="note", note="Allergic to feathers"))
    db_session.commit()

    message = format_notes_message(db_session, date(2026, 10, 5), date(2026, 10, 11))

    assert "05/10" in message and "11/10" in message
    assert "5C5-M8JL" in message
    assert "Maria Silva" in message
    assert "Allergic to feathers" in message
    assert "Limpezas" not in message  # the two messages are fully separate


def test_format_notes_message_shows_fallback_text_when_none(db_session):
    message = format_notes_message(db_session, date(2026, 10, 5), date(2026, 10, 11))
    assert "Sem notas esta semana." in message


def test_should_send_weekly_briefing_only_fires_on_sunday(monkeypatch):
    monkeypatch.setattr("app.weekly_briefing.settings.weekly_briefing_send_hour", 20)
    saturday_night = datetime(2026, 10, 3, 21, 0)  # Saturday
    assert should_send_weekly_briefing(saturday_night, None) is False


def test_should_send_weekly_briefing_waits_for_the_configured_hour(monkeypatch):
    monkeypatch.setattr("app.weekly_briefing.settings.weekly_briefing_send_hour", 20)
    sunday_afternoon = datetime(2026, 10, 4, 18, 0)  # Sunday, before 20:00
    assert should_send_weekly_briefing(sunday_afternoon, None) is False


def test_should_send_weekly_briefing_fires_once_the_hour_arrives(monkeypatch):
    monkeypatch.setattr("app.weekly_briefing.settings.weekly_briefing_send_hour", 20)
    sunday_night = datetime(2026, 10, 4, 20, 30)
    assert should_send_weekly_briefing(sunday_night, None) is True


def test_should_send_weekly_briefing_does_not_repeat_for_the_same_week(monkeypatch):
    monkeypatch.setattr("app.weekly_briefing.settings.weekly_briefing_send_hour", 20)
    sunday_night = datetime(2026, 10, 4, 20, 30)
    already_sent = date(2026, 10, 5).isoformat()  # the Monday this Sunday reports on
    assert should_send_weekly_briefing(sunday_night, already_sent) is False


def test_should_send_weekly_briefing_fires_again_for_a_later_week(monkeypatch):
    monkeypatch.setattr("app.weekly_briefing.settings.weekly_briefing_send_hour", 20)
    next_sunday_night = datetime(2026, 10, 11, 20, 30)
    last_week_sent = date(2026, 10, 5).isoformat()  # a previous week's marker
    assert should_send_weekly_briefing(next_sunday_night, last_week_sent) is True
