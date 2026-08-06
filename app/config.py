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
    google_oauth_client_secret_json: str = "./data/oauth_client_secret.json"
    google_oauth_token_path: str = "./data/oauth_token.json"

    col_external_id: str = "reference"
    col_guest_name: str = ""  # leave blank to compose from first/last name columns below
    col_customer_first_name: str = "customer_first_name"
    col_customer_last_name: str = "customer_last_name"
    col_cabin: str = "products"
    col_check_in: str = "start_on"
    col_check_out: str = "end_on"
    col_total_price: str = "net_paid"
    col_booking_source: str = "sales_channel"
    col_status: str = "state"

    # Only rows whose status column matches one of these (case-insensitive) are
    # synced as real, billable stays -- everything else (cancelled, pending, quote,
    # etc.) is skipped entirely.
    billable_states: str = "completed"

    @property
    def billable_states_set(self) -> set[str]:
        return {s.strip().lower() for s in self.billable_states.split(",") if s.strip()}

    # Fee schedule (EUR)
    cleaning_fee_standard: float = 33.0
    cleaning_fee_holiday: float = 40.0
    overnight_fee_per_night: float = 19.8
    holiday_country: str = "PT"


settings = Settings()
