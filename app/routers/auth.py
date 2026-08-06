from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.settings_store import set_setting
from app.sheets_sync import OAUTH_TOKEN_SETTING_KEY, build_oauth_flow

router = APIRouter()


@router.get("/auth/google")
def start_google_auth():
    """Kicks off the one-time Google login -- just a redirect to Google's consent screen."""
    flow = build_oauth_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    return RedirectResponse(auth_url)


@router.get("/auth/google/callback")
def google_auth_callback(code: str, db: Session = Depends(get_db)):
    """Google redirects back here with a one-time code after the user approves access."""
    flow = build_oauth_flow()
    flow.fetch_token(code=code)
    set_setting(db, OAUTH_TOKEN_SETTING_KEY, flow.credentials.to_json())
    return RedirectResponse("/bookings?google_connected=1", status_code=303)
