from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/sollo.db"

    sheets_source_mode: str = "local_csv"  # local_csv | csv_url | service_account | oauth_user

    sheets_local_csv_path: str = "./data/sample_bookings.csv"
    sheets_csv_url: str = ""

    google_service_account_json: str = "./data/service_account.json"
    google_sheet_id: str = ""
    google_sheet_worksheet: str = "Bookings"

    # Used when SHEETS_SOURCE_MODE=oauth_user -- authenticates as a real Google
    # user via a one-time browser consent instead of a service account key.
    # Either a file path to the downloaded OAuth client JSON, OR the raw JSON
    # content itself pasted directly (handy for hosting platforms where you set
    # environment variables through a web UI, not a file). The obtained token is
    # stored in the database (Setting table), not on local disk, so it survives
    # redeploys on hosts with ephemeral filesystems.
    google_oauth_client_secret_json: str = "./data/oauth_client_secret.json"
    google_oauth_redirect_uri: str = "http://127.0.0.1:8000/auth/google/callback"

    col_external_id: str = "reference"
    col_guest_name: str = ""  # leave blank to compose from first/last name columns below
    col_customer_first_name: str = "customer_first_name"
    col_customer_last_name: str = "customer_last_name"
    col_customer_phone: str = "customer_mobile_number"
    col_customer_email: str = "customer_email"
    col_cabin: str = "products"
    col_check_in: str = "start_on"
    col_check_out: str = "end_on"
    col_booked_at: str = "booked_at"  # date the reservation was made, for the Sales metric
    col_booking_source: str = "sales_channel"
    col_status: str = "state"

    # Revenue price columns (EUR) -- which one is authoritative depends on the
    # booking's current status, since "how much actually counts" differs: a
    # completed stay bills its full TOTAL, a still-pending one only what's
    # actually been RECEIVED so far, and a cancelled one whatever was NET_PAID
    # and kept (not refunded) -- see _resolve_total_price in sheets_sync.py.
    col_price_total: str = "total"
    col_price_received: str = "received"
    col_price_net_paid: str = "net_paid"

    # Only rows whose status column matches one of these (case-insensitive) are
    # synced into the database at all -- everything else (declined, quote, etc.)
    # is skipped entirely. A "cancelled" row is still synced (for its NET_PAID
    # revenue) but never bills the landowner -- see Booking.skip_landowner_fees.
    billable_states: str = "completed,pending_payment,cancelled"

    @property
    def billable_states_set(self) -> set[str]:
        return {s.strip().lower() for s in self.billable_states.split(",") if s.strip()}

    # Fee schedule (EUR)
    cleaning_fee_standard: float = 33.0
    cleaning_fee_holiday: float = 40.0
    overnight_fee_per_night: float = 19.8
    holiday_country: str = "PT"

    # Fixed monthly operating costs (EUR), deducted from Profit. Website costs are
    # a flat fee plus a per-transaction percentage + flat fee, mirroring a typical
    # payment processor -- charged on bookings synced from the Sheet (not manual
    # Extra Revenue entries), attributed to the same month as Revenue (checkout).
    website_fixed_fee: float = 200.0
    website_percentage_fee: float = 0.04
    website_per_transaction_fee: float = 0.25
    tech_tools_fee: float = 66.0
    accounting_fee: float = 200.0

    # Supplies (e.g. cleaning products, toiletries) are bought in irregular,
    # lumpy batches -- not evenly every month -- so instead of expensing each
    # purchase in full the month it happens, its cost per stay is smoothed by
    # averaging actual "supplies" Ledger expenses and stays over a trailing
    # window of this many months, then applied per stay closing each month.
    supplies_rolling_window_months: int = 6

    # Dashboard "Profit year-to-date" goal bar target (EUR/year).
    annual_profit_target: float = 36000.0


settings = Settings()
