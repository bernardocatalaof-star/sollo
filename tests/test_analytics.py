from datetime import date

from app.analytics import financial_summary, landowner_statement, revenue_by_month, sales_in_month
from app.models import Booking, Cabin, Expense, ExtraRevenue


def _seed(db_session):
    cabin1 = Cabin(name="Cabin 1")
    cabin2 = Cabin(name="Cabin 2")
    db_session.add_all([cabin1, cabin2])
    db_session.flush()

    bookings = [
        Booking(external_id="R-1", cabin=cabin1, guest_name="A", check_in=date(2026, 8, 1), check_out=date(2026, 8, 4), total_price=320),
        Booking(external_id="R-2", cabin=cabin2, guest_name="B", check_in=date(2026, 8, 3), check_out=date(2026, 8, 5), total_price=180),
        # spans into September -> should count for August occupancy but bill in September
        Booking(external_id="R-3", cabin=cabin1, guest_name="C", check_in=date(2026, 8, 30), check_out=date(2026, 9, 2), total_price=150),
    ]
    db_session.add_all(bookings)
    db_session.add(Expense(month=date(2026, 8, 1), category="supplies", description="cleaning kit", amount=25.0))
    db_session.commit()
    return cabin1, cabin2, bookings


def test_landowner_statement_only_counts_stays_closing_in_month(db_session):
    _seed(db_session)
    statement = landowner_statement(db_session, 2026, 8)
    cabins_billed = {c.cabin_name for c in statement.by_cabin}
    assert cabins_billed == {"Cabin 1", "Cabin 2"}
    assert statement.total_owed > 0


def test_landowner_statement_splits_cross_month_stay_nights_by_calendar_month(db_session):
    _seed(db_session)
    august = landowner_statement(db_session, 2026, 8)
    september = landowner_statement(db_session, 2026, 9)

    cabin1_august = next(c for c in august.by_cabin if c.cabin_name == "Cabin 1")
    cabin1_september = next(c for c in september.by_cabin if c.cabin_name == "Cabin 1")

    # R-3 (Aug 30 -> Sep 2): 2 nights actually slept in August, 1 in September.
    # R-1 (Aug 1-4, 3 nights) is entirely in August, so Cabin 1's August total is 3 + 2 = 5.
    assert cabin1_august.nights == 5
    assert cabin1_september.nights == 1


def test_landowner_statement_bills_cleaning_fee_only_in_checkout_month(db_session):
    _seed(db_session)
    august = landowner_statement(db_session, 2026, 8)
    september = landowner_statement(db_session, 2026, 9)

    cabin1_august = next(c for c in august.by_cabin if c.cabin_name == "Cabin 1")
    cabin1_september = next(c for c in september.by_cabin if c.cabin_name == "Cabin 1")

    # R-3 checks out in September, so its cleaning fee is billed there, not in
    # August, even though 2 of its nights were slept in August.
    assert cabin1_august.cleanings == 1  # just R-1
    assert cabin1_september.cleanings == 1  # just R-3


def test_financial_summary_includes_supply_expenses(db_session):
    _seed(db_session)
    summary = financial_summary(db_session, 2026, 8)
    assert summary.total_supply_costs == 25.0
    assert summary.total_costs == round(summary.total_landowner_costs + 25.0, 2)
    assert summary.profit == round(summary.total_revenue - summary.total_costs, 2)


def test_financial_summary_occupancy_counts_overlapping_nights(db_session):
    _seed(db_session)
    summary = financial_summary(db_session, 2026, 8)
    # Cabin1: Aug1-4 (3 nights) + Aug30-31 (2 nights of the cross-month stay) = 5
    # Cabin2: Aug3-5 (2 nights)
    assert summary.nights_occupied == 7
    assert summary.nights_available == 31 * 2  # 2 cabins x 31 days in August


def test_financial_summary_includes_extra_revenue_in_total(db_session):
    _seed(db_session)
    db_session.add(ExtraRevenue(month=date(2026, 8, 1), category="gift_card", description="", amount=50.0))
    db_session.add(ExtraRevenue(month=date(2026, 8, 1), category="booking", description="", amount=75.0))
    db_session.add(ExtraRevenue(month=date(2026, 9, 1), category="booking", description="", amount=999.0))
    db_session.commit()

    summary = financial_summary(db_session, 2026, 8)

    assert summary.booking_revenue == 500.0  # R-1 (320) + R-2 (180); R-3 bills in September
    assert summary.extra_revenue == 125.0
    assert summary.total_revenue == 625.0
    assert summary.profit == round(summary.total_revenue - summary.total_costs, 2)


def test_sales_in_month_counts_by_booked_at_not_checkout(db_session):
    cabin = Cabin(name="Cabin 1")
    db_session.add(cabin)
    db_session.flush()
    db_session.add_all(
        [
            # booked in August, checks out in September -- should count as an August sale
            Booking(external_id="A", cabin=cabin, guest_name="A", check_in=date(2026, 8, 30),
                    check_out=date(2026, 9, 2), booked_at=date(2026, 8, 15), total_price=150.0),
            # booked in July, checks out in August -- should NOT count as an August sale
            Booking(external_id="B", cabin=cabin, guest_name="B", check_in=date(2026, 8, 1),
                    check_out=date(2026, 8, 3), booked_at=date(2026, 7, 20), total_price=100.0),
            # no booked_at at all -- excluded, not crashing
            Booking(external_id="C", cabin=cabin, guest_name="C", check_in=date(2026, 8, 5),
                    check_out=date(2026, 8, 6), booked_at=None, total_price=80.0),
        ]
    )
    db_session.commit()

    sales = sales_in_month(db_session, 2026, 8)

    assert sales.count == 1
    assert sales.total_amount == 150.0


def test_revenue_by_month_spans_from_earliest_to_latest_activity(db_session):
    _seed(db_session)  # bookings checking out in Aug and Sep 2026 only

    months = revenue_by_month(db_session)

    assert [(m.year, m.month) for m in months] == [(2026, 8), (2026, 9)]
    assert months[0].label == "Aug 2026"
    assert months[0].amount == 500.0  # R-1 (320) + R-2 (180); R-3 bills in September
    assert months[1].amount == 150.0  # R-3


def test_revenue_by_month_includes_future_months_already_booked(db_session):
    cabin = Cabin(name="Cabin 1")
    db_session.add(cabin)
    db_session.flush()
    db_session.add(
        Booking(external_id="FUTURE", cabin=cabin, guest_name="Future Guest",
                check_in=date(2027, 3, 1), check_out=date(2027, 3, 3), total_price=200.0)
    )
    db_session.commit()

    months = revenue_by_month(db_session)

    assert (2027, 3) == (months[-1].year, months[-1].month)
    assert months[-1].amount == 200.0


def test_revenue_by_month_extends_range_to_cover_extra_revenue_entries(db_session):
    db_session.add(ExtraRevenue(month=date(2025, 1, 1), category="booking", description="", amount=60.0))
    db_session.commit()

    months = revenue_by_month(db_session)

    assert (months[0].year, months[0].month) == (2025, 1)
    assert months[0].amount == 60.0


def test_revenue_by_month_defaults_to_current_month_when_no_data(db_session):
    months = revenue_by_month(db_session)
    today = date.today()
    assert len(months) == 1
    assert (months[0].year, months[0].month) == (today.year, today.month)
    assert months[0].amount == 0.0
