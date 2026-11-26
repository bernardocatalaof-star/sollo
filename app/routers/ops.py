"""Operations pages: /tarefas (maintenance), /compras (shopping list) and
/stock (consumables + gas), plus the public stock link for the cleaning
company (/stock/p/<token>). All logic lives in app/ops.py."""

from datetime import date
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import ops
from app.database import get_db
from app.models import GasBottle, OpsPurchase, OpsSupply, OpsTask, SeasonTemplate
from app.settings_store import set_setting

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(
    PLACES=ops.PLACES,
    OWNERS=ops.OWNERS,
    CONTACTS=ops.CONTACTS,
    PURCHASE_CATEGORIES=ops.PURCHASE_CATEGORIES,
    SUPPLY_LEVELS=ops.SUPPLY_LEVELS,
    GAS_STATUSES=ops.GAS_STATUSES,
    task_who=ops.task_who,
)


def _back(path: str, **params) -> RedirectResponse:
    clean = {k: v for k, v in params.items() if v}
    return RedirectResponse(path + ("?" + urlencode(clean) if clean else ""), status_code=303)


def _parse_who(who: str) -> tuple[str, str]:
    """Form value -> (owner, contact). "contact:Carlos" means Leo talks to Carlos."""
    who = (who or "").strip()
    if who.startswith("contact:"):
        return ops.CONTACT_DEFAULT_OWNER, who.split(":", 1)[1].strip()
    return who, ""


def _get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404)
    return obj


# ------------------------------------------------------------------- tarefas


@router.get("/tarefas")
def tarefas(request: Request, quem: str | None = None, added: str | None = None, db: Session = Depends(get_db)):
    today = date.today()
    board = ops.task_board(db, today, quem)
    return templates.TemplateResponse(
        "ops_tarefas.html",
        {
            "request": request,
            "board": board,
            "quem": quem or "",
            "added": added,
            "today": today,
            "seasons_due": ops.seasons_due(db, today),
            "open_purchases": len(ops.open_purchases(db)),
        },
    )


@router.post("/tarefas")
def quick_add(
    title: str = Form(...),
    kind: str = Form("tarefa"),
    place: str = Form("Geral"),
    who: str = Form(""),
    urgent: bool = Form(False),
    quem: str = Form(""),
    db: Session = Depends(get_db),
):
    title = title.strip()
    if not title:
        return _back("/tarefas", quem=quem)
    if kind == "compra":
        db.add(OpsPurchase(item=title, place=place, category="cabin", urgent=urgent))
        db.commit()
        return _back("/tarefas", quem=quem, added="compra")
    owner, contact = _parse_who(who)
    db.add(OpsTask(title=title, place=place, owner=owner, contact=contact, urgent=urgent))
    db.commit()
    return _back("/tarefas", quem=quem, added="tarefa")


@router.post("/tarefas/{task_id}/feito")
def task_done(task_id: int, quem: str = Form(""), db: Session = Depends(get_db)):
    task = _get_or_404(db, OpsTask, task_id)
    ops.complete_task(db, task, by=quem)
    return _back("/tarefas", quem=quem)


@router.post("/tarefas/{task_id}/reabrir")
def task_reopen(task_id: int, quem: str = Form(""), db: Session = Depends(get_db)):
    ops.reopen_task(db, _get_or_404(db, OpsTask, task_id))
    return _back("/tarefas", quem=quem)


@router.get("/tarefas/mensagem")
def task_message(request: Request, para: str, db: Session = Depends(get_db)):
    text = ops.build_message(db, para)
    return templates.TemplateResponse(
        "ops_mensagem.html",
        {
            "request": request,
            "title": f"Mensagem para {para}",
            "text": text,
            "share_url": ops.whatsapp_share_url(text),
            "back": "/tarefas?" + urlencode({"quem": para}),
        },
    )


@router.get("/tarefas/estacoes")
def seasons_page(request: Request, saved: int | None = None, db: Session = Depends(get_db)):
    today = date.today()
    return templates.TemplateResponse(
        "ops_estacoes.html",
        {
            "request": request,
            "seasons": db.query(SeasonTemplate).order_by(SeasonTemplate.id).all(),
            "checklist": "\n".join(ops.cleaning_checklist(db)),
            "saved": saved,
            "today": today,
            "season_marker": lambda key: ops.get_setting(db, ops.season_marker(key, today.year)),
        },
    )


@router.post("/tarefas/estacoes/{key}")
def season_save(key: str, items: str = Form(""), months: str = Form(""), db: Session = Depends(get_db)):
    tpl = db.query(SeasonTemplate).filter_by(key=key).first()
    if tpl is None:
        raise HTTPException(status_code=404)
    tpl.items = items.strip()
    tpl.months = ",".join(m.strip() for m in months.split(",") if m.strip().isdigit())
    db.commit()
    return _back("/tarefas/estacoes", saved=1)


@router.post("/tarefas/estacoes/{key}/ativar")
def season_activate(key: str, db: Session = Depends(get_db)):
    tpl = db.query(SeasonTemplate).filter_by(key=key).first()
    if tpl is None:
        raise HTTPException(status_code=404)
    ops.activate_season(db, tpl, date.today())
    return _back("/tarefas")


@router.post("/tarefas/estacoes/{key}/dispensar")
def season_dismiss(key: str, db: Session = Depends(get_db)):
    tpl = db.query(SeasonTemplate).filter_by(key=key).first()
    if tpl is None:
        raise HTTPException(status_code=404)
    ops.dismiss_season(db, tpl, date.today())
    return _back("/tarefas")


@router.post("/tarefas/limpeza-checklist")
def save_cleaning_checklist(checklist: str = Form(""), db: Session = Depends(get_db)):
    set_setting(db, ops.CLEANING_CHECKLIST_KEY, checklist.strip())
    return _back("/tarefas/estacoes", saved=1)


@router.get("/tarefas/{task_id}")
def task_edit_page(request: Request, task_id: int, db: Session = Depends(get_db)):
    task = _get_or_404(db, OpsTask, task_id)
    purchases = db.query(OpsPurchase).filter(OpsPurchase.task_id == task.id).all()
    return templates.TemplateResponse(
        "ops_tarefa.html", {"request": request, "task": task, "purchases": purchases}
    )


@router.post("/tarefas/{task_id}")
def task_save(
    task_id: int,
    title: str = Form(...),
    place: str = Form("Geral"),
    owner: str = Form(""),
    contact: str = Form(""),
    notes: str = Form(""),
    due_date: str = Form(""),
    recurrence_months: str = Form(""),
    urgent: bool = Form(False),
    status: str = Form("todo"),
    db: Session = Depends(get_db),
):
    task = _get_or_404(db, OpsTask, task_id)
    task.title = title.strip() or task.title
    task.place = place
    task.owner = owner.strip()
    task.contact = contact.strip()
    if task.contact and not task.owner:
        task.owner = ops.CONTACT_DEFAULT_OWNER
    task.notes = notes.strip()
    task.due_date = date.fromisoformat(due_date) if due_date else None
    task.recurrence_months = int(recurrence_months) if recurrence_months.isdigit() else None
    task.urgent = urgent
    if status == "done" and task.status != "done":
        ops.complete_task(db, task)
    else:
        if status in ("todo", "doing"):
            if task.status == "done":
                ops.reopen_task(db, task)
            task.status = status
        db.commit()
    return _back("/tarefas")


@router.post("/tarefas/{task_id}/apagar")
def task_delete(task_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, OpsTask, task_id))
    db.commit()
    return _back("/tarefas")


@router.post("/tarefas/{task_id}/compra")
def task_add_purchase(
    task_id: int, item: str = Form(...), category: str = Form("obra"), db: Session = Depends(get_db)
):
    task = _get_or_404(db, OpsTask, task_id)
    if item.strip():
        db.add(OpsPurchase(item=item.strip(), place=task.place, category=category, task_id=task.id, urgent=task.urgent))
        db.commit()
    return _back(f"/tarefas/{task_id}")


# ------------------------------------------------------------------- compras


@router.get("/compras")
def compras(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    items = ops.open_purchases(db)
    by_category: dict[str, list[OpsPurchase]] = {key: [] for key in ops.PURCHASE_CATEGORIES}
    for p in items:
        by_category.setdefault(p.category, []).append(p)
    return templates.TemplateResponse(
        "ops_compras.html",
        {
            "request": request,
            "by_category": by_category,
            "count": len(items),
            "bought": ops.recently_bought(db, today),
        },
    )


@router.post("/compras")
def compras_add(
    item: str = Form(...),
    place: str = Form("Geral"),
    category: str = Form("cabin"),
    urgent: bool = Form(False),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if item.strip():
        db.add(OpsPurchase(item=item.strip(), place=place, category=category, urgent=urgent, notes=notes.strip()))
        db.commit()
    return _back("/compras")


@router.get("/compras/mensagem")
def compras_message(request: Request, db: Session = Depends(get_db)):
    lines = ["*Lista de compras sollō*", ""]
    for key, label in ops.PURCHASE_CATEGORIES.items():
        items = [p for p in ops.open_purchases(db) if p.category == key]
        if not items:
            continue
        lines.append(f"*{label}*")
        for p in items:
            where = f" ({p.place})" if p.place and p.place != "Geral" else ""
            lines.append(f"- {p.item}{where}" + (" — urgente" if p.urgent else ""))
        lines.append("")
    text = "\n".join(lines).strip()
    return templates.TemplateResponse(
        "ops_mensagem.html",
        {
            "request": request,
            "title": "Lista de compras",
            "text": text,
            "share_url": ops.whatsapp_share_url(text),
            "back": "/compras",
        },
    )


@router.post("/compras/{purchase_id}/comprado")
def compras_bought(purchase_id: int, db: Session = Depends(get_db)):
    ops.mark_bought(db, _get_or_404(db, OpsPurchase, purchase_id))
    return _back("/compras")


@router.post("/compras/{purchase_id}/desfazer")
def compras_undo(purchase_id: int, db: Session = Depends(get_db)):
    ops.unmark_bought(db, _get_or_404(db, OpsPurchase, purchase_id))
    return _back("/compras")


@router.post("/compras/{purchase_id}/apagar")
def compras_delete(purchase_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, OpsPurchase, purchase_id))
    db.commit()
    return _back("/compras")


# --------------------------------------------------------------------- stock


def _stock_context(db: Session) -> dict:
    return {"supplies": ops.supplies(db), "gas": ops.gas_summary(db)}


@router.get("/stock")
def stock(request: Request, db: Session = Depends(get_db)):
    token = ops.get_or_create_stock_token(db)
    public_url = str(request.base_url).rstrip("/") + f"/stock/p/{token}"
    return templates.TemplateResponse(
        "ops_stock.html", {"request": request, "public_url": public_url, **_stock_context(db)}
    )


@router.post("/stock")
def stock_add(name: str = Form(...), db: Session = Depends(get_db)):
    if name.strip():
        last = db.query(OpsSupply).order_by(OpsSupply.position.desc()).first()
        db.add(OpsSupply(name=name.strip(), position=(last.position + 1) if last else 0))
        db.commit()
    return _back("/stock")


@router.post("/stock/link/regenerar")
def stock_regenerate_link(db: Session = Depends(get_db)):
    ops.regenerate_stock_token(db)
    return _back("/stock")


@router.post("/stock/gas")
def gas_add(label: str = Form(...), db: Session = Depends(get_db)):
    if label.strip():
        db.add(GasBottle(label=label.strip(), position=db.query(GasBottle).count()))
        db.commit()
    return _back("/stock")


@router.post("/stock/gas/{bottle_id}")
def gas_set(bottle_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    ops.set_gas_status(db, _get_or_404(db, GasBottle, bottle_id), status)
    return _back("/stock")


@router.post("/stock/gas/{bottle_id}/apagar")
def gas_delete(bottle_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, GasBottle, bottle_id))
    db.commit()
    return _back("/stock")


@router.post("/stock/{supply_id}/nivel")
def stock_set_level(supply_id: int, level: str = Form(...), db: Session = Depends(get_db)):
    ops.set_supply_level(db, _get_or_404(db, OpsSupply, supply_id), level, by="Dashboard")
    return _back("/stock")


@router.post("/stock/{supply_id}/apagar")
def stock_delete(supply_id: int, db: Session = Depends(get_db)):
    supply = _get_or_404(db, OpsSupply, supply_id)
    db.query(OpsPurchase).filter(OpsPurchase.supply_id == supply.id, OpsPurchase.bought.is_(False)).delete()
    db.delete(supply)
    db.commit()
    return _back("/stock")


# ------------------------------------------- public stock link (no login)


def _check_token(db: Session, token: str) -> None:
    if token != ops.get_or_create_stock_token(db):
        raise HTTPException(status_code=404)


@router.get("/stock/p/{token}")
def stock_public(request: Request, token: str, ok: int | None = None, db: Session = Depends(get_db)):
    _check_token(db, token)
    return templates.TemplateResponse(
        "ops_stock_public.html", {"request": request, "token": token, "ok": ok, **_stock_context(db)}
    )


@router.post("/stock/p/{token}/gas/{bottle_id}")
def stock_public_gas(token: str, bottle_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    _check_token(db, token)
    ops.set_gas_status(db, _get_or_404(db, GasBottle, bottle_id), status)
    return RedirectResponse(f"/stock/p/{quote(token)}?ok=1", status_code=303)


@router.post("/stock/p/{token}/{supply_id}")
def stock_public_level(token: str, supply_id: int, level: str = Form(...), db: Session = Depends(get_db)):
    _check_token(db, token)
    ops.set_supply_level(db, _get_or_404(db, OpsSupply, supply_id), level, by="Limpeza")
    return RedirectResponse(f"/stock/p/{quote(token)}?ok=1", status_code=303)
