import json

import pytest

from app.sheets_sync import GoogleNotConnectedError, build_oauth_flow, fetch_rows, oauth_is_connected
from app.settings_store import set_setting

FAKE_CLIENT_CONFIG = {
    "web": {
        "client_id": "fake-client-id.apps.googleusercontent.com",
        "client_secret": "fake-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://127.0.0.1:8000/auth/google/callback"],
    }
}


def test_oauth_is_connected_false_when_no_token_stored(db_session):
    assert oauth_is_connected(db_session) is False


def test_oauth_is_connected_true_after_token_stored(db_session):
    set_setting(db_session, "google_oauth_token", "{}")
    assert oauth_is_connected(db_session) is True


def test_fetch_rows_raises_clear_error_when_oauth_mode_not_connected(db_session, monkeypatch):
    monkeypatch.setattr("app.sheets_sync.settings.sheets_source_mode", "oauth_user")
    with pytest.raises(GoogleNotConnectedError):
        fetch_rows(db_session)


def test_build_oauth_flow_accepts_raw_json_content_and_sets_redirect_uri(monkeypatch):
    monkeypatch.setattr(
        "app.sheets_sync.settings.google_oauth_client_secret_json", json.dumps(FAKE_CLIENT_CONFIG)
    )
    flow = build_oauth_flow(redirect_uri="https://example.onrender.com/auth/google/callback")
    auth_url, _ = flow.authorization_url()
    assert "accounts.google.com" in auth_url
    assert "example.onrender.com" in auth_url
