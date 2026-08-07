from datetime import date

from app.calendar_view import cabin_colors, month_grid
from app.models import Booking, Cabin


def _seed(db_session):
    olivia = Cabin(name="Olivia")
    santiago = Cabin(name="Santiago")
    db_session.add_all([olivia, santiago])
    db_session.flush()

    db_session.add_all(
        [
            Booking(
                external_id="R-1", cabin=olivia, guest_name="Ana Silva",
                check_in=date(2026, 8, 5), check_out=date(2026, 8, 8), total_price=100,
            ),
            # spans into September
            Booking(
                external_id="R-2", cabin=santiago, guest_name="John Smith",
                check_in=date(2026, 8, 30), check_out=date(2026, 9, 2), total_price=150,
            ),
        ]
    )
    db_session.commit()
    return olivia, santiago


def test_cabin_colors_uses_fixed_colors_for_santiago_and_olivia(db_session):
    olivia, santiago = _seed(db_session)
    colors = cabin_colors(db_session)
    assert colors[santiago.id] == "#4f8cff"
    assert colors[olivia.id] == "#ff6fae"


def test_cabin_colors_falls_back_to_palette_for_other_names(db_session):
    other = Cabin(name="Treehouse")
    db_session.add(other)
    db_session.commit()
    colors = cabin_colors(db_session)
    assert colors[other.id] not in ("#4f8cff", "#ff6fae")


def _all_bars(grid):
    return [bar for week in grid for bar in week.bars]


def test_month_grid_covers_the_whole_month(db_session):
    _seed(db_session)
    grid = month_grid(db_session, 2026, 8)
    in_month_days = {c.day for week in grid for c in week.days if c.in_month}
    assert in_month_days == {date(2026, 8, d) for d in range(1, 32)}


def test_month_grid_renders_a_stay_as_one_bar_not_per_day_tags(db_session):
    _seed(db_session)
    grid = month_grid(db_session, 2026, 8)
    bars = [b for b in _all_bars(grid) if b.booking.guest_name == "Ana Silva"]
    # Aug 5 (Wed) -> Aug 8 (Sat): 3 nights, all within one week -> exactly one bar
    assert len(bars) == 1
    assert bars[0].span == 3


def test_month_grid_splits_bar_at_week_boundary(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    # Aug 2026: week rows run Mon-Sun; pick a stay crossing a week boundary.
    # Aug 3 2026 is a Monday, so a stay from Sat Aug 1 to Wed Aug 5 crosses into the next week.
    db_session.add(
        Booking(
            external_id="R-3", cabin=olivia, guest_name="Cross Week",
            check_in=date(2026, 8, 1), check_out=date(2026, 8, 5), total_price=100,
        )
    )
    db_session.commit()

    grid = month_grid(db_session, 2026, 8)
    bars = [b for b in _all_bars(grid) if b.booking.guest_name == "Cross Week"]
    assert len(bars) == 2  # one segment per week it touches
    assert sum(b.span for b in bars) == 4  # total nights preserved across the split


def test_month_grid_shows_cross_month_stay_on_boundary_days_in_both_months(db_session):
    _seed(db_session)
    august_grid = month_grid(db_session, 2026, 8)
    september_grid = month_grid(db_session, 2026, 9)

    august_bars = [b for b in _all_bars(august_grid) if b.booking.guest_name == "John Smith"]
    september_bars = [b for b in _all_bars(september_grid) if b.booking.guest_name == "John Smith"]

    # August's grid shows all 3 nights: Aug 30 in its own week row, plus Aug 31 +
    # Sep 1 on the trailing padding days of the next week row (same as a normal
    # calendar showing next month's leading days for context).
    assert sum(b.span for b in august_bars) == 3
    # September's grid shows Aug 31 (leading padding) + Sep 1 (in-month) = 2.
    assert sum(b.span for b in september_bars) == 2


def test_month_grid_stacks_overlapping_stays_in_different_lanes(db_session):
    cabin1 = Cabin(name="Olivia")
    cabin2 = Cabin(name="Santiago")
    db_session.add_all([cabin1, cabin2])
    db_session.flush()
    db_session.add_all(
        [
            Booking(external_id="A", cabin=cabin1, guest_name="Guest A",
                    check_in=date(2026, 8, 10), check_out=date(2026, 8, 12), total_price=50),
            Booking(external_id="B", cabin=cabin2, guest_name="Guest B",
                    check_in=date(2026, 8, 10), check_out=date(2026, 8, 12), total_price=50),
        ]
    )
    db_session.commit()

    grid = month_grid(db_session, 2026, 8)
    bars = [b for b in _all_bars(grid) if b.start_col is not None and b.booking.guest_name in ("Guest A", "Guest B")]
    lanes = {b.lane for b in bars}
    assert lanes == {0, 1}
