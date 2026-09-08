from datetime import date

from app.analytics import (
    cost_breakdown_by_month,
    financial_summary,
    fixed_costs_for_month,
    landowner_justification,
    landowner_statement,
    occupancy_by_cabin_and_month,
    profit_by_month,
    profit_year_to_date,
    revenue_by_month,
    sales_in_month,
)
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
    assert summary.total_costs == round(
        summary.total_landowner_costs + 25.0 + summary.fixed_costs.total, 2
    )
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


def test_fixed_costs_for_month_charges_flat_fees_even_with_no_bookings(db_session):
    costs = fixed_costs_for_month(db_session, 2026, 8)
    assert costs.website_fixed == 200.0
    assert costs.website_percentage == 0.0
    assert costs.website_per_transaction == 0.0
    assert costs.tech_tools == 66.0
    assert costs.accounting == 200.0
    assert costs.website_total == 200.0
    assert costs.total == 466.0


def test_fixed_costs_for_month_adds_website_percentage_and_per_transaction_fee(db_session):
    _seed(db_session)  # R-1 (320) + R-2 (180) close in August = 500 net_paid, 2 transactions

    costs = fixed_costs_for_month(db_session, 2026, 8)

    assert costs.website_percentage == 20.0  # 4% of 500
    assert costs.website_per_transaction == 0.5  # 2 x 0.25
    assert costs.website_total == 220.5  # 200 + 20 + 0.5
    # R-1, R-2, R-3 all check in during August (R-3 checks out in September)
    assert costs.checkin_supplies == 15.0  # 3 x 5.0
    assert costs.total == round(220.5 + 66.0 + 200.0 + 15.0, 2)


def test_checkin_supplies_charged_by_checkin_month_not_checkout_month(db_session):
    _seed(db_session)
    august = fixed_costs_for_month(db_session, 2026, 8)
    september = fixed_costs_for_month(db_session, 2026, 9)

    # R-3 checks in Aug 30 but checks out Sep 2 -- the supply is handed out at
    # check-in, so it belongs to August even though R-3's cleaning/revenue bill
    # in September.
    assert august.checkin_supplies == 15.0  # R-1 + R-2 + R-3, all check in in August
    assert september.checkin_supplies == 0.0  # no booking checks in during September


def test_fixed_costs_only_counts_bookings_closing_in_month_not_extra_revenue(db_session):
    _seed(db_session)
    db_session.add(ExtraRevenue(month=date(2026, 8, 1), category="booking", description="", amount=1000.0))
    db_session.commit()

    costs = fixed_costs_for_month(db_session, 2026, 8)

    # Extra Revenue doesn't go through the website's payment processor, so it
    # must not affect the per-transaction/percentage website fee.
    assert costs.website_percentage == 20.0
    assert costs.website_per_transaction == 0.5


def test_financial_summary_deducts_fixed_costs_from_profit(db_session):
    _seed(db_session)
    summary = financial_summary(db_session, 2026, 8)
    assert summary.fixed_costs.total == round(220.5 + 66.0 + 200.0 + 15.0, 2)
    assert summary.profit == round(summary.total_revenue - summary.total_costs, 2)


def test_profit_year_to_date_sums_january_through_given_month(db_session):
    _seed(db_session)
    ytd = profit_year_to_date(db_session, 2026, 8)
    expected = round(sum(financial_summary(db_session, 2026, m).profit for m in range(1, 9)), 2)
    assert ytd == expected
    # Fixed costs are charged every month regardless of activity, so January-July
    # (no bookings) still drag the total down by their fixed costs alone.
    jan_to_july_fixed_costs = sum(fixed_costs_for_month(db_session, 2026, m).total for m in range(1, 8))
    assert ytd == round(financial_summary(db_session, 2026, 8).profit - jan_to_july_fixed_costs, 2)


def test_profit_by_month_matches_revenue_by_month_range(db_session):
    _seed(db_session)
    revenue_months = revenue_by_month(db_session)
    profit_months = profit_by_month(db_session)
    assert [(m.year, m.month) for m in profit_months] == [(m.year, m.month) for m in revenue_months]


def test_profit_by_month_values_match_financial_summary_profit(db_session):
    _seed(db_session)
    profit_months = profit_by_month(db_session)
    for m in profit_months:
        assert m.amount == financial_summary(db_session, m.year, m.month).profit


def test_profit_by_month_reflects_fixed_costs_even_on_a_slow_month(db_session):
    _seed(db_session)  # only 2 small bookings in August, 1 in September
    profit_months = profit_by_month(db_session)
    august = next(m for m in profit_months if (m.year, m.month) == (2026, 8))
    assert august.amount == financial_summary(db_session, 2026, 8).profit
    # Revenue (500) doesn't cover landowner + supply + fixed costs this small --
    # confirms fixed costs are actually landing in the monthly figure, not just
    # in the standalone fixed_costs_for_month() helper.
    assert august.amount < 0


def test_cost_breakdown_by_month_spans_six_months_ending_at_given_month(db_session):
    months = cost_breakdown_by_month(db_session, 2026, 8, count=6)
    assert [(m.year, m.month) for m in months] == [
        (2026, 3), (2026, 4), (2026, 5), (2026, 6), (2026, 7), (2026, 8),
    ]
    assert months[-1].label == "Aug 2026"


def test_cost_breakdown_by_month_shares_match_known_sources(db_session):
    _seed(db_session)  # includes a "supplies" Expense of 25.0 and real landowner costs
    db_session.add(Expense(month=date(2026, 8, 1), category="staff", description="Madalena", amount=200.0))
    db_session.add(Expense(month=date(2026, 8, 1), category="maintenance", description="AC", amount=150.0))
    db_session.commit()

    august = next(m for m in cost_breakdown_by_month(db_session, 2026, 8) if (m.year, m.month) == (2026, 8))
    by_label = {s.label: s for s in august.shares}

    summary = financial_summary(db_session, 2026, 8)
    assert by_label.keys() == {"Landowner", "Tech", "Supplies", "Staff", "Maintenance"}
    assert by_label["Landowner"].amount == summary.total_landowner_costs
    assert by_label["Tech"].amount == summary.fixed_costs.total
    assert by_label["Supplies"].amount == 25.0
    assert by_label["Staff"].amount == 200.0
    assert by_label["Maintenance"].amount == 150.0


def test_cost_breakdown_by_month_shares_plus_profit_equals_revenue(db_session):
    _seed(db_session)
    db_session.add(Expense(month=date(2026, 8, 1), category="other", description="misc", amount=999.0))
    db_session.commit()
    for m in cost_breakdown_by_month(db_session, 2026, 8):
        assert round(sum(s.amount for s in m.shares) + m.profit, 2) == round(m.revenue, 2)


def test_cost_breakdown_profit_always_matches_real_financial_summary_profit(db_session):
    _seed(db_session)
    db_session.add(Expense(month=date(2026, 8, 1), category="other", description="misc", amount=999.0))
    db_session.add(Expense(month=date(2026, 8, 1), category="custom_bucket", description="x", amount=40.0))
    db_session.commit()

    august = next(m for m in cost_breakdown_by_month(db_session, 2026, 8) if (m.year, m.month) == (2026, 8))
    summary = financial_summary(db_session, 2026, 8)

    # Every Expense category (including "Other" and an ad-hoc custom one) is
    # broken out as its own share, so nothing is hidden -- the chart's profit
    # is exactly the same figure shown on the Dashboard/Monthly pages.
    assert {"Landowner", "Tech", "Supplies", "Other", "Custom_Bucket"} <= {s.label for s in august.shares}
    assert august.profit == summary.profit


def test_cost_breakdown_assigns_a_color_to_every_share_including_unknown_categories(db_session):
    _seed(db_session)
    db_session.add(Expense(month=date(2026, 8, 1), category="weird_new_category", description="x", amount=10.0))
    db_session.commit()

    august = next(m for m in cost_breakdown_by_month(db_session, 2026, 8) if (m.year, m.month) == (2026, 8))
    for share in august.shares:
        assert share.color


def test_occupancy_by_cabin_and_month_spans_three_before_and_three_after(db_session):
    _seed(db_session)
    months = occupancy_by_cabin_and_month(db_session, 2026, 8, months_before=3, months_after=3)
    assert [(m.year, m.month) for m in months] == [
        (2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11),
    ]


def test_occupancy_by_cabin_and_month_computes_rate_per_cabin(db_session):
    cabin1, cabin2, _ = _seed(db_session)
    months = occupancy_by_cabin_and_month(db_session, 2026, 8, months_before=1, months_after=0)
    august = months[0]
    rates = {c.cabin_name: c.rate for c in august.cabins}

    # Cabin 1: R-1 (Aug1-4, 3 nights) + R-3's Aug30-31 portion (2 nights) = 5 / 31 days
    assert round(rates["Cabin 1"], 4) == round(5 / 31, 4)
    # Cabin 2: R-2 (Aug3-5, 2 nights) / 31 days
    assert round(rates["Cabin 2"], 4) == round(2 / 31, 4)


def test_occupancy_by_cabin_and_month_uses_the_same_colors_as_the_calendar(db_session):
    from app.calendar_view import cabin_colors

    _seed(db_session)  # Cabin 1 / Cabin 2 -- not named Olivia/Santiago, so palette-assigned
    months = occupancy_by_cabin_and_month(db_session, 2026, 8, months_before=1, months_after=0)
    expected_colors = cabin_colors(db_session)
    for cabin_rate in months[0].cabins:
        cabin = db_session.query(Cabin).filter(Cabin.name == cabin_rate.cabin_name).first()
        assert cabin_rate.color == expected_colors[cabin.id]


def test_landowner_justification_lists_every_individual_night_and_cleaning_date(db_session):
    _seed(db_session)
    august = landowner_justification(db_session, 2026, 8)
    by_cabin = {c.cabin_name: c for c in august.by_cabin}

    # Cabin 1: R-1 (Aug1-4, guest A) contributes nights Aug1-3, plus R-3's
    # Aug30-31 portion (guest C) -- 5 individual night dates, sorted.
    cabin1_nights = [(n.date, n.guest_name) for n in by_cabin["Cabin 1"].nights]
    assert cabin1_nights == [
        (date(2026, 8, 1), "A"), (date(2026, 8, 2), "A"), (date(2026, 8, 3), "A"),
        (date(2026, 8, 30), "C"), (date(2026, 8, 31), "C"),
    ]
    # Only R-1 checks out in August for Cabin 1 -- R-3 checks out in September.
    assert [(c.date, c.guest_name) for c in by_cabin["Cabin 1"].cleanings] == [(date(2026, 8, 4), "A")]

    # Cabin 2: R-2 (Aug3-5, guest B) -- 2 nights, 1 cleaning.
    cabin2_nights = [(n.date, n.guest_name) for n in by_cabin["Cabin 2"].nights]
    assert cabin2_nights == [(date(2026, 8, 3), "B"), (date(2026, 8, 4), "B")]
    assert [(c.date, c.guest_name) for c in by_cabin["Cabin 2"].cleanings] == [(date(2026, 8, 5), "B")]


def test_landowner_justification_september_only_has_the_cross_month_stay(db_session):
    _seed(db_session)
    september = landowner_justification(db_session, 2026, 9)
    by_cabin = {c.cabin_name: c for c in september.by_cabin}

    assert "Cabin 2" not in by_cabin  # no September activity at all for Cabin 2
    assert [(n.date, n.guest_name) for n in by_cabin["Cabin 1"].nights] == [(date(2026, 9, 1), "C")]
    assert [(c.date, c.guest_name) for c in by_cabin["Cabin 1"].cleanings] == [(date(2026, 9, 2), "C")]


def test_landowner_justification_cleaning_amount_matches_fee_calculation(db_session):
    _seed(db_session)
    august = landowner_justification(db_session, 2026, 8)
    cabin1 = next(c for c in august.by_cabin if c.cabin_name == "Cabin 1")
    assert cabin1.cleanings[0].amount in (33.0, 40.0)  # standard or PT-holiday rate


def test_landowner_statement_bills_the_overridden_cabin_not_the_synced_one(db_session):
    cabin1, cabin2, bookings = _seed(db_session)
    r1 = next(b for b in bookings if b.external_id == "R-1")
    r1.cabin_override_id = cabin2.id
    db_session.commit()

    august = landowner_statement(db_session, 2026, 8)
    cabin1_entry = next(c for c in august.by_cabin if c.cabin_name == "Cabin 1")
    cabin2_entry = next(c for c in august.by_cabin if c.cabin_name == "Cabin 2")

    # R-1 (3 nights, 1 cleaning) moves entirely to Cabin 2; only R-3's 2 August
    # nights remain under Cabin 1, with no cleaning (it checks out in September).
    assert cabin1_entry.nights == 2
    assert cabin1_entry.cleanings == 0
    assert cabin2_entry.nights == 3 + 2  # R-1's 3 nights now attributed to Cabin 2, plus R-2's own 2
    assert cabin2_entry.cleanings == 2  # both R-1 and R-2 now bill their cleaning under Cabin 2


def test_landowner_statement_skips_cleaning_for_a_no_show(db_session):
    cabin1, cabin2, bookings = _seed(db_session)
    r1 = next(b for b in bookings if b.external_id == "R-1")
    r1.skip_cleaning_fee = True
    db_session.commit()

    august = landowner_statement(db_session, 2026, 8)
    cabin1_entry = next(c for c in august.by_cabin if c.cabin_name == "Cabin 1")

    assert cabin1_entry.cleanings == 0
    assert cabin1_entry.cleaning_total == 0.0
    assert cabin1_entry.nights == 5  # land fee is still owed -- it's not a cancellation


def test_landowner_statement_bills_fewer_nights_when_checkout_is_overridden(db_session):
    cabin1, cabin2, bookings = _seed(db_session)
    r1 = next(b for b in bookings if b.external_id == "R-1")  # Aug 1 -> Aug 4, 3 nights
    r1.check_out_override = date(2026, 8, 2)  # guest actually left after 1 night
    db_session.commit()

    august = landowner_statement(db_session, 2026, 8)
    cabin1_entry = next(c for c in august.by_cabin if c.cabin_name == "Cabin 1")

    # R-1 now contributes 1 night instead of 3, plus R-3's 2 August nights = 3.
    assert cabin1_entry.nights == 3
    # The cleaning is still billed (checkout month unchanged), just on the earlier date.
    assert cabin1_entry.cleanings == 1


def test_landowner_justification_uses_the_overridden_cabin_and_checkout_date(db_session):
    cabin1, cabin2, bookings = _seed(db_session)
    r1 = next(b for b in bookings if b.external_id == "R-1")
    r1.cabin_override_id = cabin2.id
    r1.check_out_override = date(2026, 8, 2)
    db_session.commit()

    august = landowner_justification(db_session, 2026, 8)
    by_cabin = {c.cabin_name: c for c in august.by_cabin}

    assert [(n.date, n.guest_name) for n in by_cabin["Cabin 2"].nights if n.guest_name == "A"] == [
        (date(2026, 8, 1), "A")
    ]
    assert [(c.date, c.guest_name) for c in by_cabin["Cabin 2"].cleanings if c.guest_name == "A"] == [
        (date(2026, 8, 2), "A")
    ]
