"""A read-only, token-protected page for the land partner (landowner) --
completely separate from the admin app, so sharing its link never exposes
Revenue, Profit, or any other internal business figure. It reads straight
from the same database the admin app writes to, so it's always live: no
"sync" step is needed on the landowner's side for a correction made in the
admin app (a no-show flag, a shortened stay, a cabin fix) to show up here.

Three tabs:
  - Calendar: which cabin, which guest, how many nights, and whether the
    stay has a late check-out -- no price, no revenue.
  - Monthly Close-out: the same landowner_statement/landowner_justification
    already shown to the owner -- nights slept, cleaning dates, and the
    amount owed per cabin -- without the admin-only Financial Summary
    (Revenue, Profit, Occupancy) that's none of the landowner's business.
  - Weekly notes: the same cleanings-this-week list and advance notes as the
    WhatsApp weekly briefing, read straight off the live data.
"""

import secrets

from sqlalchemy.orm import Session

from app.settings_store import get_setting, set_setting

LANDOWNER_TOKEN_SETTING_KEY = "landowner_token"


def get_or_create_landowner_token(db: Session) -> str:
    token = get_setting(db, LANDOWNER_TOKEN_SETTING_KEY)
    if not token:
        token = secrets.token_urlsafe(9)
        set_setting(db, LANDOWNER_TOKEN_SETTING_KEY, token)
    return token


def regenerate_landowner_token(db: Session) -> str:
    """Invalidates the current link (e.g. if it was shared too widely) and
    issues a new one."""
    token = secrets.token_urlsafe(9)
    set_setting(db, LANDOWNER_TOKEN_SETTING_KEY, token)
    return token
