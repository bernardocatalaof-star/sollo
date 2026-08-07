from datetime import date

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import bookings_closing_in_month, financial_summary, landowner_statement
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import auth, bookings, calendar, expenses, extra_revenue, ledger, monthly
from app.sheets_sync import oauth_is_connected

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sollo — Guest & Operations Management")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(bookings.router)
app.include_router(calendar.router)
app.include_router(expenses.router)
app.include_router(extra_revenue.router)
app.include_router(ledger.router)
app.include_router(monthly.router)


@app.get("/")
def dashboard(request: Request):
    db: Session = SessionLocal()
    try:
        today = date.today()
        statement = landowner_statement(db, today.year, today.month)
        summary = financial_summary(db, today.year, today.month)
        revenue_bookings = bookings_closing_in_month(db, today.year, today.month)
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
            "revenue_bookings": revenue_bookings,
            "needs_google_connect": needs_google_connect,
        },
    )
