from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import financial_summary, landowner_statement
from app.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/monthly")
def monthly_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month

    statement = landowner_statement(db, year, month)
    summary = financial_summary(db, year, month)

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    return templates.TemplateResponse(
        "monthly.html",
        {
            "request": request,
            "year": year,
            "month": month,
            "statement": statement,
            "summary": summary,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )
