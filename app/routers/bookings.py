from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.fees import calculate_booking_fees
from app.models import Booking, Cabin, StayFlag
from app.sheets_sync import GoogleNotConnectedError, oauth_is_connected, sync_bookings

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
    removed: int = 0,
    error: str | None = None,
    google_connected: int | None = None,
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
        sync_message = (
            f"Sync complete: {created} created, {updated} updated, "
            f"{skipped} skipped (of which {removed} removed as no longer billable)."
        )
    if google_connected:
        sync_message = "Google account connected. You can sync now."

    needs_google_connect = settings.sheets_source_mode == "oauth_user" and not oauth_is_connected(db)

    return templates.TemplateResponse(
        "bookings.html",
        {
            "request": request,
            "rows": rows,
            "cabins": cabins,
            "selected_cabin_id": cabin_id,
            "sync_message": sync_message,
            "sync_error": error,
            "needs_google_connect": needs_google_connect,
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
    try:
        result = sync_bookings(db)
    except GoogleNotConnectedError as exc:
        return RedirectResponse(f"/bookings?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(
        "/bookings?synced=1"
        f"&created={result.created}&updated={result.updated}"
        f"&skipped={result.skipped}&removed={result.removed}",
        status_code=303,
    )
