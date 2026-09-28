import pytest

from app.whatsapp import WhatsAppNotConfiguredError, send_whatsapp_message


def _configure(monkeypatch, **overrides):
    defaults = dict(
        twilio_account_sid="ACxxxx",
        twilio_auth_token="secret",
        twilio_whatsapp_from="whatsapp:+14155238886",
        twilio_whatsapp_to="whatsapp:+351912345678",
    )
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(f"app.whatsapp.settings.{key}", value)


def test_send_whatsapp_message_raises_when_not_configured(monkeypatch):
    _configure(monkeypatch, twilio_account_sid="")
    with pytest.raises(WhatsAppNotConfiguredError):
        send_whatsapp_message("hello")


def test_send_whatsapp_message_posts_to_twilio_with_expected_payload(monkeypatch):
    _configure(monkeypatch)
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, auth, data, timeout):
        captured["url"] = url
        captured["auth"] = auth
        captured["data"] = data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.whatsapp.requests.post", fake_post)

    send_whatsapp_message("weekly briefing text")

    assert captured["url"] == "https://api.twilio.com/2010-04-01/Accounts/ACxxxx/Messages.json"
    assert captured["auth"] == ("ACxxxx", "secret")
    assert captured["data"] == {
        "From": "whatsapp:+14155238886",
        "To": "whatsapp:+351912345678",
        "Body": "weekly briefing text",
    }


def test_send_whatsapp_message_raises_on_http_error(monkeypatch):
    _configure(monkeypatch)

    class FailingResponse:
        def raise_for_status(self):
            raise RuntimeError("Twilio 401")

    monkeypatch.setattr("app.whatsapp.requests.post", lambda *a, **k: FailingResponse())

    with pytest.raises(RuntimeError):
        send_whatsapp_message("hello")
