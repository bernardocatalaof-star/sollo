from datetime import date

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExtraRevenue

router = APIRouter()


@router.post("/extra-revenue")
def add_extra_revenue(
    month: str = Form(...),  # "YYYY-MM"
    category: str = Form("booking"),
    description: str = Form(""),
    amount: float = Form(...),
    db: Session = Depends(get_db),
):
    year, mon = (int(part) for part in month.split("-"))
    db.add(
        ExtraRevenue(month=date(year, mon, 1), category=category, description=description, amount=amount)
    )
    db.commit()
    return RedirectResponse("/ledger", status_code=303)


@router.post("/extra-revenue/{entry_id}/delete")
def delete_extra_revenue(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(ExtraRevenue, entry_id)
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse("/ledger", status_code=303)
