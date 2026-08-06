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

Note: this makes the sheet's data readable by anyone with the link — skip this if
your sheet has guest PII (name/email/address/phone), which a platform export usually does.

**Option B — Google service account (private, needs an unrestricted GCP org):**
1. In Google Cloud Console, create a service account and download its JSON key.
2. Share your Google Sheet with the service account's email (view access is enough).
3. Save the JSON key to `data/service_account.json` (already git-ignored).
4. In `.env`: set `SHEETS_SOURCE_MODE=service_account`, `GOOGLE_SHEET_ID=<the ID from
   the sheet's URL>`, and `GOOGLE_SHEET_WORKSHEET=<tab name>`.

If step 1 fails with `iam.disableServiceAccountKeyCreation` — a policy your Google
Cloud organization enforces and that you likely can't override yourself — use
Option C instead. It reaches the same private sheet without a service account key.

**Option C — OAuth as yourself (private, works even when service account keys are
blocked):**
1. Cloud Console → APIs & Services → **OAuth consent screen** → configure it (User
   type "External" is fine for personal use; add yourself under "Test users").
2. Add the scope `.../auth/spreadsheets.readonly`.
3. Cloud Console → APIs & Services → **Credentials** → Create Credentials → **OAuth
   client ID** → Application type **Desktop app** → Create → download the JSON.
4. Save it to `data/oauth_client_secret.json` (already git-ignored).
5. In `.env`: set `SHEETS_SOURCE_MODE=oauth_user`, `GOOGLE_SHEET_ID=<the ID from the
   sheet's URL>`, and `GOOGLE_SHEET_WORKSHEET=<tab name>`.
6. Run a sync. The first time, it opens your browser for a one-time Google login +
   consent; after that, a refresh token is cached to `data/oauth_token.json` (also
   git-ignored) so it never prompts again unless you revoke access.

This is a normal OAuth *client* credential (like any desktop app uses), not a
service account key, so it's unaffected by that org policy — and it authenticates
as you, so it only ever sees sheets you personally have access to.

### Matching your Sheet's columns

The app maps its internal fields to your Sheet's actual column headers via `.env` —
no code changes needed. The defaults already match a reservations-platform export
(the kind with columns like `reference`, `state`, `products`, `start_on`, `end_on`,
`net_paid`, `sales_channel`, ...):

```
COL_EXTERNAL_ID=reference
COL_GUEST_NAME=
COL_CUSTOMER_FIRST_NAME=customer_first_name
COL_CUSTOMER_LAST_NAME=customer_last_name
COL_CABIN=products
COL_CHECK_IN=start_on
COL_CHECK_OUT=end_on
COL_TOTAL_PRICE=net_paid
COL_BOOKING_SOURCE=sales_channel
COL_STATUS=state
BILLABLE_STATES=completed
```

If your sheet instead has one plain "Guest Name" column, set `COL_GUEST_NAME` to it
and the first/last name columns are ignored. If there's no unique reservation ID
column, leave `COL_EXTERNAL_ID` empty — the app falls back to a stable ID derived
from cabin + check-in + check-out so repeat syncs still update rather than
duplicate rows.

`COL_STATUS` / `BILLABLE_STATES` control which rows count at all: only rows whose
status matches one of the comma-separated `BILLABLE_STATES` values (case-insensitive)
are synced as real stays — everything else (cancelled, pending, quote, refunded...)
is skipped, and if a previously-synced booking's status later changes to a
non-billable one, it's automatically removed on the next sync so it stops counting
towards revenue.

`COL_CABIN` (typically a `products`/`variants`-style column from booking platforms)
is parsed defensively: it handles a plain name ("Cabin 1"), a JSON list/dict
(`[{"name": "Cabin 1"}]`), and strips trailing quantity annotations like " x1". If
your platform's export format is different, check `_extract_cabin_name()` in
`app/sheets_sync.py` after a first sync — if cabin names look wrong on the
Bookings page, tell me the raw format and I'll adjust the parser.

Dates are parsed as ISO (`YYYY-MM-DD`, including full timestamps like
`2026-08-01T14:00:00Z`) first, then as day-first (`DD/MM/YYYY`), which covers both
platform exports and typical European sheets.

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
- **Revenue** uses `net_paid` (actual amount collected, net of refunds) rather than
  the full quoted `total` — change `COL_TOTAL_PRICE` in `.env` if you'd rather
  recognize revenue on the full booked price regardless of payment status.

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
