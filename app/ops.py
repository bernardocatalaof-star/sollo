"""Operations logic: maintenance tasks, shopping list, consumables stock, gas
bottles, seasonal checklists and the WhatsApp messages built from them.

Kept free of FastAPI so it can be unit tested directly (see tests/test_ops.py);
the web pages live in app/routers/ops.py.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import quote

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models import GasBottle, GasLog, OpsPurchase, OpsSupply, OpsTask, SeasonTemplate
from app.settings_store import get_setting, set_setting

PLACES = ["Olivia", "Santiago", "Ambas", "Armazém", "Casa técnica", "Barragem", "Geral"]
OWNERS = ["Ben", "Leo", "Limpeza"]
# Outside helpers: a task for one of them reads "Leo falar com <nome>".
CONTACTS = ["Carlos", "Paulo Linguiça", "Azinheirinha"]
CONTACT_DEFAULT_OWNER = "Leo"

PURCHASE_CATEGORIES = {"consumivel": "Consumível", "cabin": "Cabin", "obra": "Obra / ferramentas"}
SUPPLY_LEVELS = {"ok": "Tem", "low": "Está a acabar", "out": "Acabou"}
GAS_STATUSES = {"in_use": "Em uso", "full": "Cheia (reserva)", "empty": "Vazia", "check": "Por verificar"}

TASK_LATER_DAYS = 30  # open tasks due further away than this go under "Mais tarde"
DONE_RECENT_DAYS = 14

CLEANING_CHECKLIST_KEY = "cleaning_checklist"
STOCK_TOKEN_KEY = "stock_public_token"
OPS_SEED_KEY = "ops_seed_v1"


# --------------------------------------------------------------------- tasks


def task_who(task: OpsTask) -> str:
    """Human label for who's on the hook, e.g. "Leo falar com Carlos"."""
    if task.contact:
        return f"{task.owner or CONTACT_DEFAULT_OWNER} falar com {task.contact}"
    return task.owner or "Por atribuir"


def _task_sort_key(task: OpsTask):
    return (
        not task.urgent,
        task.due_date or date.max,
        task.created_at or datetime.min,
    )


def place_order(place: str) -> int:
    return PLACES.index(place) if place in PLACES else len(PLACES)


@dataclass
class PlaceGroup:
    place: str
    tasks: list[OpsTask] = field(default_factory=list)


@dataclass
class TaskBoard:
    groups: list[PlaceGroup]
    later: list[OpsTask]
    done_recent: list[OpsTask]
    open_count: int
    urgent_count: int


def matches_who(task: OpsTask, who: str | None) -> bool:
    if not who:
        return True
    return who in (task.owner, task.contact)


def task_board(db: Session, today: date, who: str | None = None) -> TaskBoard:
    open_tasks = [t for t in db.query(OpsTask).filter(OpsTask.status != "done").all() if matches_who(t, who)]
    horizon = today + timedelta(days=TASK_LATER_DAYS)
    now_tasks = [t for t in open_tasks if t.due_date is None or t.due_date <= horizon]
    later = sorted([t for t in open_tasks if t.due_date and t.due_date > horizon], key=lambda t: t.due_date)

    by_place: dict[str, list[OpsTask]] = {}
    for t in now_tasks:
        by_place.setdefault(t.place or "Geral", []).append(t)
    groups = [
        PlaceGroup(place, sorted(tasks, key=_task_sort_key))
        for place, tasks in sorted(by_place.items(), key=lambda kv: place_order(kv[0]))
    ]

    since = datetime.combine(today - timedelta(days=DONE_RECENT_DAYS), datetime.min.time())
    done_recent = [
        t
        for t in db.query(OpsTask).filter(OpsTask.status == "done", OpsTask.done_at >= since).all()
        if matches_who(t, who)
    ]
    done_recent.sort(key=lambda t: t.done_at, reverse=True)

    return TaskBoard(
        groups=groups,
        later=later,
        done_recent=done_recent,
        open_count=len(now_tasks),
        urgent_count=sum(1 for t in now_tasks if t.urgent),
    )


def complete_task(db: Session, task: OpsTask, by: str = "", today: date | None = None) -> OpsTask | None:
    """Marks a task done. A repeating task immediately gets its next
    occurrence, due `recurrence_months` after today. Returns that new task."""
    today = today or date.today()
    task.status = "done"
    task.done_at = datetime.utcnow()
    task.done_by = by
    next_task = None
    if task.recurrence_months:
        next_task = OpsTask(
            title=task.title,
            place=task.place,
            owner=task.owner,
            contact=task.contact,
            notes=task.notes,
            urgent=False,
            due_date=today + relativedelta(months=task.recurrence_months),
            recurrence_months=task.recurrence_months,
            source=task.source,
        )
        db.add(next_task)
    db.commit()
    return next_task


def reopen_task(db: Session, task: OpsTask) -> None:
    task.status = "todo"
    task.done_at = None
    task.done_by = ""
    db.commit()


# --------------------------------------------------------------- shopping list


def open_purchases(db: Session) -> list[OpsPurchase]:
    items = db.query(OpsPurchase).filter(OpsPurchase.bought.is_(False)).all()
    return sorted(items, key=lambda p: (not p.urgent, p.category, place_order(p.place), p.created_at))


def recently_bought(db: Session, today: date) -> list[OpsPurchase]:
    since = datetime.combine(today - timedelta(days=DONE_RECENT_DAYS), datetime.min.time())
    items = db.query(OpsPurchase).filter(OpsPurchase.bought.is_(True), OpsPurchase.bought_at >= since).all()
    return sorted(items, key=lambda p: p.bought_at, reverse=True)


def mark_bought(db: Session, purchase: OpsPurchase) -> None:
    purchase.bought = True
    purchase.bought_at = datetime.utcnow()
    if purchase.supply is not None:
        purchase.supply.level = "ok"
        purchase.supply.updated_at = datetime.utcnow()
        purchase.supply.updated_by = "Compra"
    db.commit()


def unmark_bought(db: Session, purchase: OpsPurchase) -> None:
    purchase.bought = False
    purchase.bought_at = None
    db.commit()


# --------------------------------------------------------------------- stock


def set_supply_level(db: Session, supply: OpsSupply, level: str, by: str = "") -> None:
    """Updates a consumable's traffic light. Low/out puts it on the shopping
    list (once -- never a duplicate line); back to "tem" removes the line if
    it wasn't bought yet."""
    if level not in SUPPLY_LEVELS:
        raise ValueError(f"Unknown level: {level}")
    supply.level = level
    supply.updated_at = datetime.utcnow()
    supply.updated_by = by
    pending = (
        db.query(OpsPurchase)
        .filter(OpsPurchase.supply_id == supply.id, OpsPurchase.bought.is_(False))
        .first()
    )
    if level in ("low", "out"):
        if pending is None:
            db.add(OpsPurchase(item=supply.name, category="consumivel", supply_id=supply.id, urgent=level == "out"))
        elif level == "out":
            pending.urgent = True
    elif pending is not None:
        db.delete(pending)
    db.commit()


def supplies(db: Session) -> list[OpsSupply]:
    return db.query(OpsSupply).order_by(OpsSupply.position, OpsSupply.id).all()


# ----------------------------------------------------------------------- gas


@dataclass
class GasSummary:
    bottles: list[GasBottle]
    avg_days: int | None
    runs_out_around: date | None
    has_reserve: bool
    order_pending: bool


def set_gas_status(db: Session, bottle: GasBottle, status: str, now: datetime | None = None) -> None:
    if status not in GAS_STATUSES:
        raise ValueError(f"Unknown gas status: {status}")
    now = now or datetime.utcnow()
    if bottle.status == "in_use" and status == "empty" and bottle.status_since:
        db.add(GasLog(bottle_label=bottle.label, started_at=bottle.status_since, emptied_at=now))
    bottle.status = status
    bottle.status_since = now

    pending = db.query(OpsPurchase).filter(OpsPurchase.gas.is_(True), OpsPurchase.bought.is_(False)).first()
    if status == "empty" and pending is None:
        db.add(
            OpsPurchase(
                item="Encomendar botija de gás",
                category="consumivel",
                place="Geral",
                urgent=True,
                gas=True,
                notes="Criado automaticamente: uma botija ficou vazia.",
            )
        )
    db.flush()
    if status == "full" and pending is not None:
        still_empty = db.query(GasBottle).filter(GasBottle.status == "empty").count()
        if still_empty == 0:
            db.delete(pending)
    db.commit()


def gas_summary(db: Session) -> GasSummary:
    bottles = db.query(GasBottle).order_by(GasBottle.position, GasBottle.id).all()
    logs = db.query(GasLog).all()
    durations = [(log.emptied_at - log.started_at).days for log in logs if log.emptied_at > log.started_at]
    avg_days = round(sum(durations) / len(durations)) if durations else None
    in_use = [b for b in bottles if b.status == "in_use"]
    runs_out_around = None
    if avg_days and in_use:
        runs_out_around = (min(b.status_since for b in in_use) + timedelta(days=avg_days)).date()
    order_pending = (
        db.query(OpsPurchase).filter(OpsPurchase.gas.is_(True), OpsPurchase.bought.is_(False)).count() > 0
    )
    return GasSummary(
        bottles=bottles,
        avg_days=avg_days,
        runs_out_around=runs_out_around,
        has_reserve=any(b.status == "full" for b in bottles),
        order_pending=order_pending,
    )


# ------------------------------------------------------------------- seasons


def season_marker(key: str, year: int) -> str:
    return f"season_{key}_{year}"


def seasons_due(db: Session, today: date) -> list[SeasonTemplate]:
    """Season checklists whose reminder months include this month and that
    haven't been activated or dismissed yet this year."""
    due = []
    for tpl in db.query(SeasonTemplate).order_by(SeasonTemplate.id).all():
        months = {int(m) for m in tpl.months.split(",") if m.strip().isdigit()}
        if today.month in months and not get_setting(db, season_marker(tpl.key, today.year)):
            due.append(tpl)
    return due


def parse_season_line(line: str) -> tuple[str, str]:
    """"Olivia: Trocar edredon" -> ("Olivia", "Trocar edredon"); a line with
    no known place prefix goes to "Ambas"."""
    if ":" in line:
        prefix, rest = line.split(":", 1)
        if prefix.strip() in PLACES and rest.strip():
            return prefix.strip(), rest.strip()
    return "Ambas", line.strip()


def activate_season(db: Session, tpl: SeasonTemplate, today: date) -> int:
    count = 0
    for raw in tpl.items.splitlines():
        if not raw.strip():
            continue
        place, title = parse_season_line(raw)
        db.add(OpsTask(title=title, place=place, source=f"{tpl.name} {today.year}"))
        count += 1
    db.commit()
    set_setting(db, season_marker(tpl.key, today.year), "activated")
    return count


def dismiss_season(db: Session, tpl: SeasonTemplate, today: date) -> None:
    set_setting(db, season_marker(tpl.key, today.year), "dismissed")


# ------------------------------------------------------------------ messages


def _lines_by_place(tasks: list[OpsTask], show_contact: bool = False) -> list[str]:
    lines: list[str] = []
    by_place: dict[str, list[OpsTask]] = {}
    for t in sorted(tasks, key=_task_sort_key):
        by_place.setdefault(t.place or "Geral", []).append(t)
    for place in sorted(by_place, key=place_order):
        lines.append(f"*{place}*")
        for t in by_place[place]:
            extra = " (urgente)" if t.urgent else ""
            who = f" → {t.contact}" if show_contact and t.contact else ""
            lines.append(f"- {t.title}{who}{extra}")
        lines.append("")
    return lines


def open_tasks_now(db: Session, today: date) -> list[OpsTask]:
    horizon = today + timedelta(days=TASK_LATER_DAYS)
    return [
        t
        for t in db.query(OpsTask).filter(OpsTask.status != "done").all()
        if t.due_date is None or t.due_date <= horizon
    ]


def build_message(db: Session, para: str, today: date | None = None) -> str:
    """WhatsApp-ready text for one person: their own tasks grouped by place.
    For an outside helper (Carlos...) it's written to them, ready for Leo to
    send. For the person who has to contact helpers, those are listed too."""
    today = today or date.today()
    tasks = open_tasks_now(db, today)

    if para in CONTACTS or para not in OWNERS and any(t.contact == para for t in tasks):
        mine = [t for t in tasks if t.contact == para]
        if not mine:
            return f"Olá {para}! De momento não temos nada pendente. Obrigado!"
        lines = [f"Olá {para}! Quando puderes, precisávamos da tua ajuda com isto:", ""]
        lines += _lines_by_place(mine)
        lines.append("Obrigado!")
        return "\n".join(lines).strip()

    own = [t for t in tasks if t.owner == para and not t.contact]
    calls = [t for t in tasks if (t.owner or CONTACT_DEFAULT_OWNER) == para and t.contact]

    header = "Limpeza — tarefas extra" if para == "Limpeza" else f"{para} — tarefas sollō"
    lines = [f"*{header}* ({today:%d/%m})", ""]
    if own:
        lines += _lines_by_place(own)
    if calls:
        lines.append("*Falar com:*")
        by_contact: dict[str, list[OpsTask]] = {}
        for t in calls:
            by_contact.setdefault(t.contact, []).append(t)
        for contact, items in by_contact.items():
            lines.append(f"- {contact}: " + "; ".join(t.title for t in sorted(items, key=_task_sort_key)))
        lines.append("")
    if para == "Limpeza":
        checklist = cleaning_checklist(db)
        if checklist:
            lines.append("*Sempre, em todas as limpezas:*")
            lines += [f"- {item}" for item in checklist]
    if not own and not calls and not (para == "Limpeza" and cleaning_checklist(db)):
        lines.append("Nada pendente 🙌")
    return "\n".join(lines).strip()


def whatsapp_share_url(text: str) -> str:
    return "https://wa.me/?text=" + quote(text)


def cleaning_checklist(db: Session) -> list[str]:
    raw = get_setting(db, CLEANING_CHECKLIST_KEY) or ""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def cleaning_extra_lines(db: Session, today: date) -> list[str]:
    """Lines appended to the weekly cleaning briefing: open tasks for the
    cleaning company plus the fixed every-clean checklist."""
    tasks = [t for t in open_tasks_now(db, today) if t.owner == "Limpeza" and not t.contact]
    lines: list[str] = []
    if tasks:
        lines += ["", "Tarefas extra:"]
        for t in sorted(tasks, key=_task_sort_key):
            lines.append(f"* {t.place}: {t.title}" + (" (urgente)" if t.urgent else ""))
    checklist = cleaning_checklist(db)
    if checklist:
        lines += ["", "Sempre, em todas as limpezas:"]
        lines += [f"* {item}" for item in checklist]
    return lines


# --------------------------------------------------------------- stock link


def get_or_create_stock_token(db: Session) -> str:
    token = get_setting(db, STOCK_TOKEN_KEY)
    if not token:
        token = secrets.token_urlsafe(12)
        set_setting(db, STOCK_TOKEN_KEY, token)
    return token


def regenerate_stock_token(db: Session) -> str:
    token = secrets.token_urlsafe(12)
    set_setting(db, STOCK_TOKEN_KEY, token)
    return token
