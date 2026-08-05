from datetime import date

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import financial_summary, landowner_statement
from app.database import Base, SessionLocal, engine
from app.routers import bookings, expenses, monthly

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sollo — Guest & Operations Management")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(bookings.router)
app.include_router(expenses.router)
app.include_router(monthly.router)


@app.get("/")
def dashboard(request: Request):
    db: Session = SessionLocal()
    try:
        today = date.today()
        statement = landowner_statement(db, today.year, today.month)
        summary = financial_summary(db, today.year, today.month)
    finally:
        db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "year": today.year, "month": today.month, "statement": statement, "summary": summary},
    )
