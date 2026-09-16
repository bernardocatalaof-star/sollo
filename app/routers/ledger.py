from dataclasses import dataclass
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.analytics import supplies_cost_per_stay_rate
from app.config import settings
from app.database import get_db
from app.models import Expense, ExtraRevenue

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@dataclass
class LedgerEntry:
    id: int
    kind: str  # "expense" | "revenue"
    month: date
    category: str
    description: str
    amount: float
    created_at: datetime


@router.get("/ledger")
def list_ledger(request: Request, db: Session = Depends(get_db)):
    entries = [
        LedgerEntry(e.id, "expense", e.month, e.category, e.description, e.amount, e.created_at)
        for e in db.query(Expense).all()
    ] + [
        LedgerEntry(r.id, "revenue", r.month, r.category, r.description, r.amount, r.created_at)
        for r in db.query(ExtraRevenue).all()
    ]
    entries.sort(key=lambda e: (e.month, e.created_at), reverse=True)

    today = date.today()
    supplies_rate = round(supplies_cost_per_stay_rate(db, today.year, today.month), 2)

    return templates.TemplateResponse(
        "ledger.html",
        {
            "request": request,
            "entries": entries,
            "supplies_rate": supplies_rate,
            "supplies_window": settings.supplies_rolling_window_months,
        },
    )
