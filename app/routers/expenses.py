from datetime import date

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense

router = APIRouter()


@router.post("/expenses")
def add_expense(
    month: str = Form(...),  # "YYYY-MM"
    category: str = Form("supplies"),
    description: str = Form(""),
    amount: float = Form(...),
    db: Session = Depends(get_db),
):
    year, mon = (int(part) for part in month.split("-"))
    db.add(Expense(month=date(year, mon, 1), category=category, description=description, amount=amount))
    db.commit()
    return RedirectResponse("/ledger", status_code=303)


@router.post("/expenses/{expense_id}/delete")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if expense:
        db.delete(expense)
        db.commit()
    return RedirectResponse("/ledger", status_code=303)
