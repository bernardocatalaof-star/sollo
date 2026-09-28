"""Sends WhatsApp messages via Twilio's WhatsApp Business API."""

import requests

from app.config import settings


class WhatsAppNotConfiguredError(RuntimeError):
    """Raised when a send is attempted before Twilio's settings are filled in."""


def send_whatsapp_message(body: str) -> None:
    if not (
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_whatsapp_from
        and settings.twilio_whatsapp_to
    ):
        raise WhatsAppNotConfiguredError(
            "Twilio isn't configured yet -- set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "TWILIO_WHATSAPP_FROM and TWILIO_WHATSAPP_TO."
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    resp = requests.post(
        url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        data={
            "From": settings.twilio_whatsapp_from,
            "To": settings.twilio_whatsapp_to,
            "Body": body,
        },
        timeout=15,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        # Twilio's error body (code + message) is far more actionable than the
        # generic "400 Client Error" -- e.g. "21211: The 'To' number ... is not
        # a valid phone number" -- so surface that instead when it's present.
        try:
            detail = resp.json()
            message = detail.get("message")
            code = detail.get("code")
        except ValueError:
            message = None
            code = None
        if message:
            raise RuntimeError(f"Twilio error {code}: {message}") from exc
        raise
