import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import (
    cost_breakdown_by_month,
    financial_summary,
    landowner_statement,
    occupancy_by_cabin_and_month,
    profit_by_month,
    profit_year_to_date,
    revenue_by_month,
    sales_in_month,
)
from app.config import settings
from app.database import (
    Base,
    SessionLocal,
    backfill_cabin_guide_tokens,
    engine,
    run_data_fixes,
    run_schema_migrations,
    seed_cabin_extra_sections,
)
from app.routers import (
    auth,
    bookings,
    calendar,
    expenses,
    extra_revenue,
    guidebook,
    ledger,
    monthly,
    pnl,
    weekly_briefing,
)
from app.settings_store import get_setting, set_setting
from app.sheets_sync import oauth_is_connected
from app.weekly_briefing import (
    LAST_WEEKLY_BRIEFING_SETTING_KEY,
    format_cleanings_message,
    format_notes_message,
    next_week_bounds,
    should_send_weekly_briefing,
)
from app.whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)
_LISBON = ZoneInfo("Europe/Lisbon")

Base.metadata.create_all(bind=engine)
run_schema_migrations(engine)
backfill_cabin_guide_tokens(engine)
run_data_fixes(engine)
seed_cabin_extra_sections(engine)

app = FastAPI(title="Sollo — Guest & Operations Management")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(bookings.router)
app.include_router(calendar.router)
app.include_router(expenses.router)
app.include_router(extra_revenue.router)
app.include_router(guidebook.router)
app.include_router(ledger.router)
app.include_router(monthly.router)
app.include_router(pnl.router)
app.include_router(weekly_briefing.router)


async def _weekly_briefing_loop() -> None:
    """Checks every 30 minutes whether it's time to send the weekly WhatsApp
    briefing. Runs in-process (no separate cron service) since a check every
    30 minutes is cheap and the app is already always running."""
    while True:
        try:
            if settings.weekly_briefing_enabled:
                now = datetime.now(_LISBON)
                db = SessionLocal()
                try:
                    last_sent = get_setting(db, LAST_WEEKLY_BRIEFING_SETTING_KEY)
                    if should_send_weekly_briefing(now, last_sent):
                        week_start, week_end = next_week_bounds(now.date())
                        send_whatsapp_message(format_cleanings_message(db, week_start, week_end))
                        send_whatsapp_message(format_notes_message(db, week_start, week_end))
                        set_setting(db, LAST_WEEKLY_BRIEFING_SETTING_KEY, week_start.isoformat())
                finally:
                    db.close()
        except Exception:
            logger.exception("Weekly briefing send failed")
        await asyncio.sleep(1800)


@app.on_event("startup")
async def _start_weekly_briefing_loop() -> None:
    asyncio.create_task(_weekly_briefing_loop())


@app.get("/")
def dashboard(request: Request):
    db: Session = SessionLocal()
    try:
        today = date.today()
        statement = landowner_statement(db, today.year, today.month)
        summary = financial_summary(db, today.year, today.month)
        revenue_months = revenue_by_month(db)
        profit_months = profit_by_month(db)
        cost_breakdown_months = cost_breakdown_by_month(db, today.year, today.month)
        cost_chart_max_scale = max(
            [100.0] + [sum(s.pct for s in m.shares) for m in cost_breakdown_months]
        )
        cabin_occupancy_months = occupancy_by_cabin_and_month(db, today.year, today.month)
        sales = sales_in_month(db, today.year, today.month)
        profit_ytd = profit_year_to_date(db, today.year, today.month)
        target = settings.annual_profit_target
        profit_ytd_pct = min(max(profit_ytd / target * 100, 0), 100) if target else 0
        needs_google_connect = settings.sheets_source_mode == "oauth_user" and not oauth_is_connected(db)
    finally:
        db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "year": today.year,
            "month": today.month,
            "statement": statement,
            "summary": summary,
            "revenue_months": revenue_months,
            "profit_months": profit_months,
            "cost_breakdown_months": cost_breakdown_months,
            "cost_chart_max_scale": cost_chart_max_scale,
            "cabin_occupancy_months": cabin_occupancy_months,
            "sales": sales,
            "profit_ytd": profit_ytd,
            "profit_ytd_pct": profit_ytd_pct,
            "annual_profit_target": target,
            "needs_google_connect": needs_google_connect,
        },
    )
