from app.models import Cabin, GuidebookSection
from app.routers.guidebook import (
    DEFAULT_SECTIONS,
    _seed_default_sections,
    add_section,
    delete_section,
    move_section,
    render_body,
    update_section,
)


def _make_cabin(db, name="Cabin 1"):
    cabin = Cabin(name=name, guide_token="tok123")
    db.add(cabin)
    db.commit()
    return cabin


def test_render_body_wraps_paragraphs_and_breaks_lines():
    html = render_body("Line one\nLine two\n\nSecond paragraph")
    assert str(html) == "<p>Line one<br>Line two</p><p>Second paragraph</p>"


def test_render_body_renders_bullet_list():
    html = render_body("- First\n- Second")
    assert str(html) == "<ul><li>First</li><li>Second</li></ul>"


def test_render_body_escapes_html_and_applies_bold():
    html = render_body("<script>alert(1)</script> **safe**")
    assert "<script>" not in str(html)
    assert "&lt;script&gt;" in str(html)
    assert "<strong>safe</strong>" in str(html)


def test_render_body_renders_underline():
    html = render_body("This is __important__")
    assert str(html) == "<p>This is <u>important</u></p>"


def test_render_body_renders_heading_line():
    html = render_body("# Wifi\nPassword: 12345")
    assert str(html) == "<h3>Wifi</h3><p>Password: 12345</p>"


def test_render_body_autolinks_urls():
    html = render_body("Wifi info at https://example.com/wifi for details")
    assert '<a href="https://example.com/wifi" target="_blank" rel="noopener">https://example.com/wifi</a>' in str(
        html
    )


def test_render_body_empty_returns_empty_markup():
    assert str(render_body("")) == ""
    assert str(render_body("   ")) == ""


def test_seed_default_sections_creates_all_defaults_in_order(db_session):
    cabin = _make_cabin(db_session)
    _seed_default_sections(db_session, cabin)

    sections = (
        db_session.query(GuidebookSection)
        .filter_by(cabin_id=cabin.id)
        .order_by(GuidebookSection.position)
        .all()
    )
    assert len(sections) == len(DEFAULT_SECTIONS)
    assert [s.title for s in sections] == [title for _, title in DEFAULT_SECTIONS]
    assert [s.position for s in sections] == list(range(len(DEFAULT_SECTIONS)))


def test_add_section_appends_after_existing_sections(db_session):
    cabin = _make_cabin(db_session)
    db_session.add(GuidebookSection(cabin_id=cabin.id, title="First", position=0))
    db_session.commit()

    add_section(cabin.id, title="Second", icon="🔥", body="hello", db=db_session)

    sections = db_session.query(GuidebookSection).filter_by(cabin_id=cabin.id).order_by(GuidebookSection.position).all()
    assert [s.title for s in sections] == ["First", "Second"]
    assert sections[1].position == 1
    assert sections[1].icon == "🔥"


def test_update_section_overwrites_fields(db_session):
    cabin = _make_cabin(db_session)
    section = GuidebookSection(cabin_id=cabin.id, title="Old", icon="", body="old body", position=0)
    db_session.add(section)
    db_session.commit()

    update_section(section.id, title="New", icon="🔑", body="new body", db=db_session)
    db_session.expire_all()

    updated = db_session.get(GuidebookSection, section.id)
    assert updated.title == "New"
    assert updated.icon == "🔑"
    assert updated.body == "new body"


def test_move_section_swaps_position_with_previous_sibling(db_session):
    cabin = _make_cabin(db_session)
    first = GuidebookSection(cabin_id=cabin.id, title="First", position=0)
    second = GuidebookSection(cabin_id=cabin.id, title="Second", position=1)
    db_session.add_all([first, second])
    db_session.commit()

    move_section(second.id, direction="up", db=db_session)
    db_session.expire_all()

    sections = db_session.query(GuidebookSection).filter_by(cabin_id=cabin.id).order_by(GuidebookSection.position).all()
    assert [s.title for s in sections] == ["Second", "First"]


def test_move_section_up_at_top_is_a_no_op(db_session):
    cabin = _make_cabin(db_session)
    first = GuidebookSection(cabin_id=cabin.id, title="First", position=0)
    db_session.add(first)
    db_session.commit()

    move_section(first.id, direction="up", db=db_session)
    db_session.expire_all()

    assert db_session.get(GuidebookSection, first.id).position == 0


def test_delete_section_removes_it(db_session):
    cabin = _make_cabin(db_session)
    section = GuidebookSection(cabin_id=cabin.id, title="Doomed", position=0)
    db_session.add(section)
    db_session.commit()
    section_id = section.id

    delete_section(section_id, db=db_session)
    db_session.expire_all()

    assert db_session.get(GuidebookSection, section_id) is None
