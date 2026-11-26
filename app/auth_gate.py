"""Single shared password for the whole app (see settings.app_password).

A logged-in browser keeps a long-lived cookie (one year) so phones don't have
to log in again every visit. The cookie value is derived from the password
itself, so changing APP_PASSWORD logs every device out.
"""

import hashlib
import hmac

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

COOKIE_NAME = "sollo_session"
COOKIE_MAX_AGE = 365 * 24 * 3600

# Pages that must work without logging in: guests, the landowner and the
# cleaning company open these from a link.
_PUBLIC_PREFIXES = ("/static/", "/guide/", "/landowner/", "/stock/p/", "/login")


def _session_value(password: str) -> str:
    return hmac.new(password.encode(), b"sollo-session-v1", hashlib.sha256).hexdigest()


def is_public_path(path: str) -> bool:
    return path == "/favicon.ico" or path.startswith(_PUBLIC_PREFIXES)


def is_logged_in(request: Request) -> bool:
    if not settings.app_password:
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    return hmac.compare_digest(cookie, _session_value(settings.app_password))


def _safe_next(next_path: str | None) -> str:
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/"


async def password_gate(request: Request, call_next):
    if settings.app_password and not is_public_path(request.url.path) and not is_logged_in(request):
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        from urllib.parse import quote

        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
    return await call_next(request)


@router.get("/login")
def login_page(request: Request, next: str | None = None, error: int | None = None):
    return templates.TemplateResponse(
        "login.html", {"request": request, "next": _safe_next(next), "error": error}
    )


@router.post("/login")
def login(request: Request, password: str = Form(...), next: str = Form("/")):
    if not settings.app_password or not hmac.compare_digest(password, settings.app_password):
        from urllib.parse import quote

        return RedirectResponse(f"/login?error=1&next={quote(_safe_next(next))}", status_code=303)
    response = RedirectResponse(_safe_next(next), status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE_NAME,
        _session_value(settings.app_password),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
