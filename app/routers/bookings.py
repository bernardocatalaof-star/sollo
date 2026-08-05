from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.fees import calculate_booking_fees
from app.models import Booking, Cabin, StayFlag
from app.sheets_sync import sync_bookings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/bookings")
def list_bookings(
    request: Request,
    cabin_id: int | None = None,
    synced: int | None = None,
    created: int = 0,
    updated: int = 0,
    skipped: int = 0,
    db: Session = Depends(get_db),
):
    query = db.query(Booking).order_by(Booking.check_in.desc())
    if cabin_id:
        query = query.filter(Booking.cabin_id == cabin_id)
    bookings = query.all()
    rows = [(b, calculate_booking_fees(b)) for b in bookings]
    cabins = db.query(Cabin).order_by(Cabin.name).all()
    sync_message = None
    if synced:
        sync_message = f"Sync complete: {created} created, {updated} updated, {skipped} skipped."
    return templates.TemplateResponse(
        "bookings.html",
        {
            "request": request,
            "rows": rows,
            "cabins": cabins,
            "selected_cabin_id": cabin_id,
            "sync_message": sync_message,
        },
    )


@router.get("/bookings/{booking_id}")
def booking_detail(request: Request, booking_id: int, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    fees = calculate_booking_fees(booking)
    return templates.TemplateResponse(
        "booking_detail.html", {"request": request, "booking": booking, "fees": fees}
    )


@router.post("/bookings/{booking_id}/flags")
def add_flag(
    booking_id: int,
    category: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    db.add(StayFlag(booking_id=booking_id, category=category, note=note))
    db.commit()
    return RedirectResponse(f"/bookings/{booking_id}", status_code=303)


@router.post("/sync")
def trigger_sync(db: Session = Depends(get_db)):
    result = sync_bookings(db)
    return RedirectResponse(
        f"/bookings?synced=1&created={result.created}&updated={result.updated}&skipped={result.skipped}",
        status_code=303,
    )
