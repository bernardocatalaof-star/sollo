# Sollo — Guest & Operations Management

A small single-user web app for managing cabin/cottage bookings: it pulls reservation
data from Google Sheets, lets you flag issues per stay, log monthly supply costs, and
auto-generates the monthly landowner statement plus a revenue/cost/occupancy/profit
summary.

## How it works

- **Sheets sync (read-only)** — pulls booking rows from your Sheet into the app's own
  database. The Sheet stays your booking intake; nothing is written back to it.
- **Fee calculation** (automatic, no manual entry):
  - Overnight ("land") fee: **€19.80 per night occupied**, per cabin. A stay that
    spans a month boundary has its nights split across both months by calendar
    date (e.g. 2 nights in July + 1 in August), not billed entirely to one month.
  - Cleaning fee: **€33 per stay**, charged once at checkout, or **€40** if the
    checkout date falls on a **Portuguese public holiday** — billed entirely to
    the calendar month of checkout, since that's when the clean happens.
- **Flags** — free-text issues/occurrences (damage, complaint, note...) attached to
  any booking.
- **Calendar** (`/calendar`) — month grid showing which cabin is occupied by which
  guest, colour-coded per cabin.
- **Ledger** (`/ledger`) — manually entered costs (e.g. supplies) and extra income
  received outside the Sheet (e.g. a bank transfer for a gift card).
- **Monthly close-out** (`/monthly`) — landowner statement (what you owe them, split
  by land fee vs. cleaning fee, per cabin) plus revenue, total costs, occupancy rate,
  and profit for the month.
- **Dashboard** — Revenue (checkout-based), Sales this month (bookings actually
  *made* this month, regardless of when they check in/out), Profit year-to-date
  against a target, Revenue/Profit by month (scrollable, spans all activity),
  a 100%-of-Revenue cost breakdown (last 6 months), and per-cabin occupancy
  (last 3 months through the next 3).

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
blocked, and works with no terminal at all if the app is hosted — see the
deployment section below):**
1. Cloud Console → APIs & Services → **OAuth consent screen** → configure it (User
   type "External" is fine for personal use; add yourself under "Test users").
2. Add the scope `.../auth/spreadsheets.readonly`.
3. Cloud Console → APIs & Services → **Credentials** → Create Credentials → **OAuth
   client ID** → Application type **Web application** (not Desktop app) → under
   "Authorized redirect URIs" add the exact URL from `GOOGLE_OAUTH_REDIRECT_URI` in
   `.env` (e.g. `https://your-app.onrender.com/auth/google/callback` once hosted, or
   `http://127.0.0.1:8000/auth/google/callback` for local testing) → Create → download
   the JSON.
4. Either save it to `data/oauth_client_secret.json` (git-ignored), or paste its raw
   JSON content directly into the `GOOGLE_OAUTH_CLIENT_SECRET_JSON` environment
   variable — the app accepts either.
5. In `.env`: set `SHEETS_SOURCE_MODE=oauth_user`, `GOOGLE_SHEET_ID=<the ID from the
   sheet's URL>`, `GOOGLE_SHEET_WORKSHEET=<tab name>`, and `GOOGLE_OAUTH_REDIRECT_URI`
   matching what you registered in step 3.
6. Start the app and visit `/auth/google` in a browser (e.g.
   `http://127.0.0.1:8000/auth/google`, or your hosted URL's `/auth/google`). It
   redirects to a normal Google login/consent screen; after you approve, the
   resulting token is saved in the app's database (not a local file), so it survives
   restarts and works the same way whether the app is running on your laptop or
   hosted online.

This is a normal OAuth *client* credential (like any web app uses to offer
"Sign in with Google"), not a service account key, so it's unaffected by that org
policy — and it authenticates as you, so it only ever sees sheets you personally
have access to.

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
COL_CUSTOMER_PHONE=customer_mobile_number
COL_CABIN=products
COL_CHECK_IN=start_on
COL_CHECK_OUT=end_on
COL_BOOKED_AT=booked_at
COL_TOTAL_PRICE=net_paid
COL_BOOKING_SOURCE=sales_channel
COL_STATUS=state
BILLABLE_STATES=completed
```

`COL_BOOKED_AT` is the date the reservation was actually made (not check-in/out) —
it only powers the Dashboard's "Sales this month" card. If your sheet doesn't have
an equivalent column, leave the setting as-is; missing or unparseable values are
just left blank rather than failing the sync.

`COL_CUSTOMER_PHONE` is synced into each booking and shown (as a tappable `tel:`
link) on that booking's detail page — reached by clicking a guest's name on the
Calendar or Bookings page.

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
- **Fixed operating costs** (website, tech tools, accounting, check-in supplies)
  are deducted from Profit every month regardless of activity — including
  months with zero bookings, which is why Profit year-to-date can start deeply
  negative if you view a year before you had any real bookings synced. Defaults
  in `app/config.py`: website €200 fixed + 4% + €0.25 per booking that closes in
  the month (not manual Extra Revenue entries), €66/month tech tools, €200/month
  accounting, €5 per booking that CHECKS IN in the month (e.g. a polaroid handed
  out at check-in — attributed to check-in month, unlike the other per-booking
  costs above which use checkout month).
  A one-off or time-limited cost (e.g. a contractor paid for a few months) isn't
  a good fit for these always-on settings — add it as a dated entry on the
  Ledger page instead.
- **Occupancy rate** and the **land fee** both split a stay's nights by calendar
  month — a stay spanning a month boundary contributes nights (and land fee) to
  both months, in proportion to how many nights actually fall in each.
- The **cleaning fee** and **Revenue**, by contrast, are attributed to the
  checkout month as a whole — that's when the clean happens and when the
  platform/sheet records the payment as settled.
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

## Deploying it online (no terminal, no local install required)

This guide assumes you've never used Render, Git, or a terminal before. Everything
below happens by clicking around in a web browser.

### 1. Create a free Postgres database

The app needs somewhere permanent to store bookings, flags, and expenses. Render's
free "Web Service" tier wipes its local disk on every restart, so a local SQLite
file would lose your data — use a real hosted database instead:

1. Go to [neon.tech](https://neon.tech) and sign up (free tier is enough).
2. Create a new project — accept the defaults.
3. On the project's dashboard, find the **connection string** — it looks like
   `postgresql://user:password@host/dbname?sslmode=require`. Copy it exactly as
   shown, no editing needed — you'll paste it into Render's `DATABASE_URL` in step 3
   below as-is.

### 2. Create the Render web service

1. Go to [render.com](https://render.com) and sign up (you can sign up with your
   Google account).
2. Click **New +** → **Web Service**.
3. Choose **Build and deploy from a Git repository**, then connect your GitHub
   account and select the `sollo` repository.
4. Render will ask for a branch — pick `claude/guest-operations-management-tucv0b`
   (or whichever branch has the latest code).
5. Fill in:
   - **Name**: anything, e.g. `sollo`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: Free
6. Don't click Create yet — scroll down to **Environment Variables** first.

### 3. Set the environment variables

This replaces editing a `.env` file — Render gives you a form instead. Add each of
these as a separate row (Key / Value):

| Key | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string from step 1 (with `postgresql+psycopg://`) |
| `SHEETS_SOURCE_MODE` | `oauth_user` |
| `GOOGLE_SHEET_ID` | the long ID from your bookings sheet's URL, between `/d/` and `/edit` |
| `GOOGLE_SHEET_WORKSHEET` | the exact tab name with your booking rows |
| `GOOGLE_OAUTH_CLIENT_SECRET_JSON` | the *entire contents* of the OAuth client JSON file you'll download in step 4 below — paste the whole thing, curly braces and all |
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://YOUR-APP-NAME.onrender.com/auth/google/callback` (you'll know the exact URL once Render assigns it — see step 5) |

Only add `COL_...` / `BILLABLE_STATES` rows if your sheet's column names differ from
the defaults already built into the app (see "Matching your Sheet's columns" above).

Click **Create Web Service**. Render will build and deploy — this takes a few
minutes. It'll fail to start correctly until you finish step 4 below, and that's
expected.

### 4. Create the Google OAuth client (Web application type)

Once deployed, Render shows you the app's URL at the top of its dashboard, e.g.
`https://sollo-abcd.onrender.com`. Use that exact URL below.

1. In [Google Cloud Console](https://console.cloud.google.com), enable the
   **Google Sheets API** (APIs & Services → Library → search "Google Sheets API" →
   Enable).
2. APIs & Services → **OAuth consent screen** → configure it (User type "External"
   is fine; add your own Google account under "Test users").
3. APIs & Services → **Credentials** → Create Credentials → **OAuth client ID** →
   Application type **Web application**.
4. Under "Authorized redirect URIs", add:
   `https://sollo-abcd.onrender.com/auth/google/callback` (using your actual Render
   URL from above).
5. Click Create — it shows you a Client ID and Client Secret, and offers a JSON
   download. Download it, open it in any text editor, and copy its entire contents.
6. Back in Render: go to your web service → **Environment** → paste that JSON
   content into `GOOGLE_OAUTH_CLIENT_SECRET_JSON`, and set
   `GOOGLE_OAUTH_REDIRECT_URI` to the same URL you just registered
   (`https://sollo-abcd.onrender.com/auth/google/callback`). Save — Render
   redeploys automatically.

### 5. Share your Sheet and connect it

1. Open your real bookings Google Sheet, click **Share**, and make sure the Google
   account you'll log in with (the one you added as a "Test user" above) has at
   least **Viewer** access — it's probably already the owner, in which case no
   action needed.
2. Visit `https://sollo-abcd.onrender.com` (your app's real URL) in your browser.
3. You'll see a banner: "Your Google account isn't connected yet." Click it.
4. Log into Google, approve access, and you're redirected back into the app —
   connected.
5. Click **"Sync bookings from Sheet"**. Your real bookings should appear.

From here on, you just visit that same URL any time — from your phone, laptop,
anywhere — to check bookings, log flags/expenses, or view the monthly close-out.
No terminal, no files, ever again.

### If something's stuck

Render's dashboard has a **Logs** tab on your web service — if the app won't load,
that's the first place to look. Paste me what it says and I'll help you fix it.
