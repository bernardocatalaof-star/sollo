from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.weekly_briefing import format_weekly_briefing, next_week_bounds
from app.whatsapp import send_whatsapp_message

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _upcoming_sunday(today: date) -> date:
    return today + timedelta(days=(6 - today.weekday()) % 7)


@router.get("/weekly-briefing")
def preview_weekly_briefing(
    request: Request, sent: int | None = None, error: str | None = None, db: Session = Depends(get_db)
):
    week_start, week_end = next_week_bounds(_upcoming_sunday(date.today()))
    message = format_weekly_briefing(db, week_start, week_end)
    return templates.TemplateResponse(
        "weekly_briefing.html",
        {
            "request": request,
            "message": message,
            "week_start": week_start,
            "week_end": week_end,
            "sent": sent,
            "error": error,
        },
    )


@router.post("/weekly-briefing/send-now")
def send_weekly_briefing_now(db: Session = Depends(get_db)):
    week_start, week_end = next_week_bounds(_upcoming_sunday(date.today()))
    message = format_weekly_briefing(db, week_start, week_end)
    try:
        send_whatsapp_message(message)
    except Exception as exc:
        return RedirectResponse(f"/weekly-briefing?error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/weekly-briefing?sent=1", status_code=303)
