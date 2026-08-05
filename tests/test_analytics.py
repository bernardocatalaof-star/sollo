from datetime import date

from app.analytics import financial_summary, landowner_statement
from app.models import Booking, Cabin, Expense


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
    assert cabins_billed == {"Cabin 1", "Cabin 2"}  # the Aug 30 -> Sep 2 stay is NOT billed in August
    assert statement.total_owed > 0


def test_landowner_statement_bills_cross_month_stay_in_checkout_month(db_session):
    _seed(db_session)
    september = landowner_statement(db_session, 2026, 9)
    assert len(september.by_cabin) == 1
    assert september.by_cabin[0].cabin_name == "Cabin 1"
    assert september.by_cabin[0].nights == 3  # Aug 30 -> Sep 2


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
