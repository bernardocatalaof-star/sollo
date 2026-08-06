from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExtraRevenue

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/extra-revenue")
def list_extra_revenue(request: Request, db: Session = Depends(get_db)):
    entries = db.query(ExtraRevenue).order_by(ExtraRevenue.month.desc(), ExtraRevenue.created_at.desc()).all()
    return templates.TemplateResponse("extra_revenue.html", {"request": request, "entries": entries})


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
    return RedirectResponse("/extra-revenue", status_code=303)


@router.post("/extra-revenue/{entry_id}/delete")
def delete_extra_revenue(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(ExtraRevenue, entry_id)
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse("/extra-revenue", status_code=303)
