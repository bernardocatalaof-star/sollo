from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.weekly_briefing import current_week_start, format_cleanings_message, format_notes_message
from app.whatsapp import send_whatsapp_message

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/weekly-briefing")
def preview_weekly_briefing(
    request: Request,
    week_start: date | None = None,
    sent: int | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    week_start = week_start or current_week_start(date.today())
    week_end = week_start + timedelta(days=6)
    return templates.TemplateResponse(
        "weekly_briefing.html",
        {
            "request": request,
            "cleanings_message": format_cleanings_message(db, week_start, week_end),
            "notes_message": format_notes_message(db, week_start, week_end),
            "week_start": week_start,
            "week_end": week_end,
            "prev_week_start": week_start - timedelta(days=7),
            "next_week_start": week_start + timedelta(days=7),
            "sent": sent,
            "error": error,
        },
    )


@router.post("/weekly-briefing/send-now")
def send_weekly_briefing_now(week_start: date = Form(...), db: Session = Depends(get_db)):
    week_end = week_start + timedelta(days=6)
    try:
        send_whatsapp_message(format_cleanings_message(db, week_start, week_end))
        send_whatsapp_message(format_notes_message(db, week_start, week_end))
    except Exception as exc:
        return RedirectResponse(
            f"/weekly-briefing?week_start={week_start}&error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/weekly-briefing?week_start={week_start}&sent=1", status_code=303)
