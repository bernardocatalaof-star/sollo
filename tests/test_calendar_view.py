from datetime import date

from app.calendar_view import cabin_colors, month_grid
from app.models import Booking, Cabin


def _seed(db_session):
    cabin1 = Cabin(name="Olivia")
    cabin2 = Cabin(name="Santiago")
    db_session.add_all([cabin1, cabin2])
    db_session.flush()

    db_session.add_all(
        [
            Booking(
                external_id="R-1", cabin=cabin1, guest_name="Ana Silva",
                check_in=date(2026, 8, 5), check_out=date(2026, 8, 8), total_price=100,
            ),
            # spans into September
            Booking(
                external_id="R-2", cabin=cabin2, guest_name="John Smith",
                check_in=date(2026, 8, 30), check_out=date(2026, 9, 2), total_price=150,
            ),
        ]
    )
    db_session.commit()
    return cabin1, cabin2


def test_cabin_colors_assigns_distinct_colors_per_cabin(db_session):
    cabin1, cabin2 = _seed(db_session)
    colors = cabin_colors(db_session)
    assert colors[cabin1.id] != colors[cabin2.id]


def _all_cells(grid):
    return [cell for week in grid for cell in week]


def test_month_grid_covers_the_whole_month(db_session):
    _seed(db_session)
    grid = month_grid(db_session, 2026, 8)
    in_month_days = {c.day for c in _all_cells(grid) if c.in_month}
    assert in_month_days == {date(2026, 8, d) for d in range(1, 32)}


def test_month_grid_places_stay_on_every_night_it_occupies(db_session):
    _seed(db_session)
    grid = month_grid(db_session, 2026, 8)
    cells_by_day = {c.day: c for c in _all_cells(grid)}

    # R-1: check_in 5, check_out 8 -> nights of the 5th, 6th, 7th (not the 8th, that's checkout)
    for day in (5, 6, 7):
        guests = [s.booking.guest_name for s in cells_by_day[date(2026, 8, day)].stays]
        assert "Ana Silva" in guests
    assert "Ana Silva" not in [s.booking.guest_name for s in cells_by_day[date(2026, 8, 8)].stays]


def test_month_grid_shows_cross_month_stay_on_boundary_days_in_both_months(db_session):
    _seed(db_session)
    august_grid = month_grid(db_session, 2026, 8)
    september_grid = month_grid(db_session, 2026, 9)

    august_cells = {c.day: c for c in _all_cells(august_grid)}
    september_cells = {c.day: c for c in _all_cells(september_grid)}

    assert "John Smith" in [s.booking.guest_name for s in august_cells[date(2026, 8, 30)].stays]
    assert "John Smith" in [s.booking.guest_name for s in august_cells[date(2026, 8, 31)].stays]
    assert "John Smith" in [s.booking.guest_name for s in september_cells[date(2026, 9, 1)].stays]
