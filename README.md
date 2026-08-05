# Sollo — Guest & Operations Management

A small single-user web app for managing cabin/cottage bookings: it pulls reservation
data from Google Sheets, lets you flag issues per stay, log monthly supply costs, and
auto-generates the monthly landowner statement plus a revenue/cost/occupancy/profit
summary.

## How it works

- **Sheets sync (read-only)** — pulls booking rows from your Sheet into the app's own
  database. The Sheet stays your booking intake; nothing is written back to it.
- **Fee calculation** (automatic, no manual entry):
  - Overnight ("land") fee: **€19.80 per night occupied**, per cabin.
    Nights occupied = check-out date minus check-in date.
  - Cleaning fee: **€33 per stay**, charged once at checkout, or **€40** if the
    checkout date falls on a **Portuguese public holiday**.
  - A stay's fees are billed entirely to the calendar month of its **checkout** date.
- **Flags** — free-text issues/occurrences (damage, complaint, note...) attached to
  any booking.
- **Expenses** — manually entered monthly costs (e.g. supplies) not tied to a stay.
- **Monthly close-out** (`/monthly`) — landowner statement (what you owe them, split
  by land fee vs. cleaning fee, per cabin) plus revenue, total costs, occupancy rate,
  and profit for the month.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Run it:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Click **"Sync bookings from Sheet"** on the dashboard or
bookings page to pull data in.

Run the tests:

```bash
pytest
```

## Connecting your real Google Sheet

The app ships configured to read `data/sample_bookings.csv` so you can try it with no
Google setup at all. When you're ready to point it at your real Sheet, edit `.env`:

**Option A — Published CSV (easiest, no credentials):**
1. In Google Sheets: File → Share → Publish to web → select your bookings tab → CSV.
2. Copy the generated URL.
3. In `.env`: set `SHEETS_SOURCE_MODE=csv_url` and `SHEETS_CSV_URL=<that URL>`.

Note: this makes the sheet's data readable by anyone with the link.

**Option B — Google service account (private, recommended for ongoing use):**
1. In Google Cloud Console, create a service account and download its JSON key.
2. Share your Google Sheet with the service account's email (view access is enough).
3. Save the JSON key to `data/service_account.json` (already git-ignored).
4. In `.env`: set `SHEETS_SOURCE_MODE=service_account`, `GOOGLE_SHEET_ID=<the ID from
   the sheet's URL>`, and `GOOGLE_SHEET_WORKSHEET=<tab name>`.

### Matching your Sheet's columns

The app maps its internal fields to your Sheet's actual column headers via `.env` —
no code changes needed:

```
COL_EXTERNAL_ID=Reservation ID
COL_GUEST_NAME=Guest Name
COL_CABIN=Cabin
COL_CHECK_IN=Check-in
COL_CHECK_OUT=Check-out
COL_TOTAL_PRICE=Total Price
COL_BOOKING_SOURCE=Source
COL_STATUS=Status
```

Just change the values on the right to match your actual headers. If your sheet has
no unique reservation ID column, leave `COL_EXTERNAL_ID` pointing at a (possibly
empty) column — the app falls back to a stable ID derived from cabin + guest + dates
so repeat syncs still update rather than duplicate rows.

Dates are parsed as ISO (`YYYY-MM-DD`) first, then as day-first (`DD/MM/YYYY`), which
covers both Google Sheets' default export format and typical European sheets.

## Assumptions worth knowing about

- **Cabins** are created automatically the first time a new name shows up in the
  `Cabin` column — no separate setup needed.
- **Fee schedule** (€19.80/night, €33/€40 cleaning, PT holidays) is hardcoded in
  `app/config.py` — change the values there if rates change.
- **Occupancy rate** = nights actually occupied (any stay overlapping the month,
  correctly split across a month boundary) ÷ (days in month × number of cabins).
- Revenue and landowner costs, by contrast, are attributed to the checkout month as a
  whole (matches how the cleaning fee is billed) — a stay that spans a month
  boundary shows up in occupancy for both months but is billed in one.

## Project layout

```
app/
  main.py           FastAPI app + dashboard route
  config.py         Settings (.env-driven)
  database.py       SQLAlchemy engine/session
  models.py         Cabin, Booking, StayFlag, Expense
  fees.py           Land + cleaning fee calculation
  analytics.py      Monthly landowner statement + financial summary
  sheets_sync.py    Pulls rows from Sheets/CSV, upserts bookings
  routers/          bookings, expenses, monthly HTTP routes
  templates/        Jinja2 HTML
  static/           CSS
tests/              pytest suite
data/               sample CSV + local SQLite DB (git-ignored)
```

## Deploying it somewhere you can check from your phone

This is a plain ASGI app, so it runs on Render, Railway, Fly.io, or a small VPS with
no changes — set the same environment variables from `.env` there, and swap
`DATABASE_URL` for a persistent volume path or a hosted Postgres URL if you outgrow
SQLite.
