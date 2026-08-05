from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/sollo.db"

    sheets_source_mode: str = "local_csv"  # local_csv | csv_url | service_account

    sheets_local_csv_path: str = "./data/sample_bookings.csv"
    sheets_csv_url: str = ""

    google_service_account_json: str = "./data/service_account.json"
    google_sheet_id: str = ""
    google_sheet_worksheet: str = "Bookings"

    col_external_id: str = "Reservation ID"
    col_guest_name: str = "Guest Name"
    col_cabin: str = "Cabin"
    col_check_in: str = "Check-in"
    col_check_out: str = "Check-out"
    col_total_price: str = "Total Price"
    col_booking_source: str = "Source"
    col_status: str = "Status"

    # Fee schedule (EUR)
    cleaning_fee_standard: float = 33.0
    cleaning_fee_holiday: float = 40.0
    overnight_fee_per_night: float = 19.8
    holiday_country: str = "PT"


settings = Settings()
