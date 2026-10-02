from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import cumulative_profit_through, financial_summary, pnl_rows_for_month
from app.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/pnl")
def pnl_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month

    rows = pnl_rows_for_month(db, year, month)
    summary = financial_summary(db, year, month)
    cumulative_profit = cumulative_profit_through(db, year, month)

    bookings_net_subtotal = round(sum(r.net for r in rows), 2)
    computed_total = round(
        bookings_net_subtotal + summary.extra_revenue - summary.total_other_costs - summary.fixed_costs.total, 2
    )
    reconciliation_diff = round(summary.profit - computed_total, 2)

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    return templates.TemplateResponse(
        "pnl.html",
        {
            "request": request,
            "year": year,
            "month": month,
            "rows": rows,
            "summary": summary,
            "cumulative_profit": cumulative_profit,
            "bookings_net_subtotal": bookings_net_subtotal,
            "computed_total": computed_total,
            "reconciliation_diff": reconciliation_diff,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )
