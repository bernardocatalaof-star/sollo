from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/expenses")
def list_expenses(request: Request, db: Session = Depends(get_db)):
    expenses = db.query(Expense).order_by(Expense.month.desc(), Expense.created_at.desc()).all()
    return templates.TemplateResponse("expenses.html", {"request": request, "expenses": expenses})


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
    return RedirectResponse("/expenses", status_code=303)


@router.post("/expenses/{expense_id}/delete")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if expense:
        db.delete(expense)
        db.commit()
    return RedirectResponse("/expenses", status_code=303)
