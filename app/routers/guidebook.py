import re
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Cabin, GuidebookSection

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Seeded into a cabin's guidebook the first time it's opened with no sections
# yet, so the owner starts from a ready-made structure instead of a blank page.
DEFAULT_SECTIONS = [
    ("📌", "Most important stuff"),
    ("🧭", "How to get there"),
    ("🔑", "Door codes"),
    ("🏡", "Cabin features"),
    ("📖", "How to use the cabin"),
    ("🔥", "Fire danger rating"),
    ("🎲", "Recipes & entertainment"),
    ("🛟", "Safety info"),
    ("☎️", "Important contacts"),
]

_URL_RE = re.compile(r"(https?://[^\s<]+)")


def _inline(line: str) -> str:
    s = str(escape(line))
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = _URL_RE.sub(lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>', s)
    return s


def render_body(text: str) -> Markup:
    """Turns a section's plain-text body into safe HTML: blank lines start a
    new paragraph, lines starting with "- " become a bullet list, **bold**
    and bare URLs are recognized. Everything else is escaped as plain text."""
    if not text or not text.strip():
        return Markup("")
    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if lines and all(ln.startswith(("- ", "* ")) for ln in lines):
            items = "".join(f"<li>{_inline(ln[2:])}</li>" for ln in lines)
            blocks.append(f"<ul>{items}</ul>")
        else:
            blocks.append("<p>" + "<br>".join(_inline(ln) for ln in lines) + "</p>")
    return Markup("".join(blocks))


templates.env.filters["render_body"] = render_body


def _seed_default_sections(db: Session, cabin: Cabin) -> None:
    for position, (icon, title) in enumerate(DEFAULT_SECTIONS):
        db.add(GuidebookSection(cabin_id=cabin.id, icon=icon, title=title, body="", position=position))
    db.commit()


@router.get("/guidebook")
def guidebook_index(db: Session = Depends(get_db)):
    """No per-cabin picker needed for the common one-cabin case -- jump
    straight to its guidebook. With several cabins, land on the first one;
    the admin page's cabin switcher covers the rest."""
    cabin = db.query(Cabin).order_by(Cabin.name).first()
    if cabin is None:
        return RedirectResponse("/bookings", status_code=303)
    return RedirectResponse(f"/guidebook/{cabin.id}", status_code=303)


@router.get("/guidebook/{cabin_id}")
def guidebook_admin(request: Request, cabin_id: int, db: Session = Depends(get_db)):
    cabin = db.get(Cabin, cabin_id)
    if cabin is None:
        return RedirectResponse("/guidebook", status_code=303)
    if not cabin.guidebook_sections:
        _seed_default_sections(db, cabin)
        db.refresh(cabin)
    cabins = db.query(Cabin).order_by(Cabin.name).all()
    return templates.TemplateResponse(
        "guidebook_admin.html",
        {
            "request": request,
            "cabin": cabin,
            "cabins": cabins,
            "sections": cabin.guidebook_sections,
        },
    )


@router.post("/guidebook/{cabin_id}/sections")
def add_section(
    cabin_id: int,
    title: str = Form(...),
    icon: str = Form(""),
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    max_position = max((s.position for s in db.query(GuidebookSection).filter_by(cabin_id=cabin_id)), default=-1)
    db.add(GuidebookSection(cabin_id=cabin_id, title=title, icon=icon, body=body, position=max_position + 1))
    db.commit()
    return RedirectResponse(f"/guidebook/{cabin_id}", status_code=303)


@router.post("/guidebook/sections/{section_id}")
def update_section(
    section_id: int,
    title: str = Form(...),
    icon: str = Form(""),
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    section = db.get(GuidebookSection, section_id)
    if section is None:
        return RedirectResponse("/guidebook", status_code=303)
    section.title = title
    section.icon = icon
    section.body = body
    section.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/guidebook/{section.cabin_id}", status_code=303)


@router.post("/guidebook/sections/{section_id}/delete")
def delete_section(section_id: int, db: Session = Depends(get_db)):
    section = db.get(GuidebookSection, section_id)
    if section is None:
        return RedirectResponse("/guidebook", status_code=303)
    cabin_id = section.cabin_id
    db.delete(section)
    db.commit()
    return RedirectResponse(f"/guidebook/{cabin_id}", status_code=303)


@router.post("/guidebook/sections/{section_id}/move")
def move_section(section_id: int, direction: str = Form(...), db: Session = Depends(get_db)):
    section = db.get(GuidebookSection, section_id)
    if section is None:
        return RedirectResponse("/guidebook", status_code=303)
    siblings = (
        db.query(GuidebookSection)
        .filter_by(cabin_id=section.cabin_id)
        .order_by(GuidebookSection.position)
        .all()
    )
    index = siblings.index(section)
    swap_index = index - 1 if direction == "up" else index + 1
    if 0 <= swap_index < len(siblings):
        other = siblings[swap_index]
        section.position, other.position = other.position, section.position
        db.commit()
    return RedirectResponse(f"/guidebook/{section.cabin_id}", status_code=303)


@router.get("/guide/{token}")
def guest_guide(request: Request, token: str, db: Session = Depends(get_db)):
    cabin = db.query(Cabin).filter(Cabin.guide_token == token).first()
    if cabin is None:
        return templates.TemplateResponse("guidebook_not_found.html", {"request": request}, status_code=404)
    return templates.TemplateResponse(
        "guidebook_guest.html",
        {"request": request, "cabin": cabin, "sections": cabin.guidebook_sections},
    )
