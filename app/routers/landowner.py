from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import landowner_justification, landowner_statement
from app.calendar_view import exclude_no_shows, month_grid
from app.database import get_db
from app.landowner import get_or_create_landowner_token, regenerate_landowner_token
from app.weekly_briefing import cleanings_this_week, current_week_start, upcoming_check_in_notes

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _valid_token(db: Session, token: str) -> bool:
    return token == get_or_create_landowner_token(db)


def _not_found(request: Request):
    return templates.TemplateResponse("landowner_not_found.html", {"request": request}, status_code=404)


@router.get("/landowner/{token}")
def landowner_calendar(
    request: Request, token: str, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)
):
    if not _valid_token(db, token):
        return _not_found(request)

    today = date.today()
    year = year or today.year
    month = month or today.month
    weeks = exclude_no_shows(month_grid(db, year, month))

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    return templates.TemplateResponse(
        "landowner_calendar.html",
        {
            "request": request,
            "token": token,
            "year": year,
            "month": month,
            "today": today,
            "weeks": weeks,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


@router.get("/landowner/{token}/monthly")
def landowner_monthly(
    request: Request, token: str, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)
):
    if not _valid_token(db, token):
        return _not_found(request)

    today = date.today()
    year = year or today.year
    month = month or today.month
    statement = landowner_statement(db, year, month)
    justification = landowner_justification(db, year, month)

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    return templates.TemplateResponse(
        "landowner_monthly.html",
        {
            "request": request,
            "token": token,
            "year": year,
            "month": month,
            "statement": statement,
            "justification": justification,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


@router.get("/landowner/{token}/weekly")
def landowner_weekly(request: Request, token: str, db: Session = Depends(get_db)):
    if not _valid_token(db, token):
        return _not_found(request)

    week_start = current_week_start(date.today())
    week_end = week_start + timedelta(days=6)
    cleanings = cleanings_this_week(db, week_start, week_end)
    notes = upcoming_check_in_notes(db, week_start, week_end)

    return templates.TemplateResponse(
        "landowner_weekly.html",
        {
            "request": request,
            "token": token,
            "week_start": week_start,
            "week_end": week_end,
            "cleanings": cleanings,
            "notes": notes,
        },
    )


@router.post("/landowner-link/regenerate")
def regenerate_landowner_link(db: Session = Depends(get_db)):
    regenerate_landowner_token(db)
    return RedirectResponse("/monthly", status_code=303)
