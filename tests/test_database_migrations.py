from datetime import date

from sqlalchemy import create_engine, inspect, text

from app.database import backfill_cabin_guide_tokens, run_data_fixes, run_schema_migrations, seed_cabin_extra_sections
from app.models import Booking, Cabin, Expense, GuidebookSection


def test_run_schema_migrations_adds_missing_column_without_touching_existing_rows():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        # Simulate a pre-migration "bookings" table that predates booked_at.
        conn.execute(
            text(
                "CREATE TABLE bookings (id INTEGER PRIMARY KEY, external_id VARCHAR(120), "
                "check_in DATE, check_out DATE, total_price FLOAT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO bookings (id, external_id, check_in, check_out, total_price) "
                "VALUES (1, 'R-1', '2026-08-01', '2026-08-03', 100.0)"
            )
        )

    run_schema_migrations(engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("bookings")}
    assert "booked_at" in columns
    assert "phone" in columns
    assert "cabin_override_id" in columns
    assert "check_out_override" in columns
    assert "skip_cleaning_fee" in columns
    assert "override_note" in columns

    with engine.connect() as conn:
        row = conn.execute(text("SELECT external_id, total_price FROM bookings WHERE id = 1")).first()
    assert row == ("R-1", 100.0)


def test_run_schema_migrations_adds_guide_token_to_cabins():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cabins (id INTEGER PRIMARY KEY, name VARCHAR(120))"))
        conn.execute(text("INSERT INTO cabins (id, name) VALUES (1, 'Olivia')"))

    run_schema_migrations(engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("cabins")}
    assert "guide_token" in columns


def test_run_schema_migrations_adds_english_translation_columns_to_guidebook_sections():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE guidebook_sections (id INTEGER PRIMARY KEY, cabin_id INTEGER, "
                "title VARCHAR(120), icon VARCHAR(10), body TEXT, position INTEGER)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO guidebook_sections (id, cabin_id, title, icon, body, position) "
                "VALUES (1, 1, 'Door codes', '🔑', 'Front: 1234', 0)"
            )
        )

    run_schema_migrations(engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("guidebook_sections")}
    assert "title_en" in columns
    assert "body_en" in columns

    with engine.connect() as conn:
        row = conn.execute(text("SELECT title, body FROM guidebook_sections WHERE id = 1")).first()
    assert row == ("Door codes", "Front: 1234")


def test_run_schema_migrations_is_a_no_op_on_a_fresh_database(db_session):
    # db_session's engine already has booked_at via create_all() -- re-running the
    # migration must not error or duplicate the column.
    run_schema_migrations(db_session.get_bind())


def test_run_schema_migrations_skips_missing_tables():
    engine = create_engine("sqlite:///:memory:")
    run_schema_migrations(engine)  # no "bookings" table at all -- must not raise


def test_backfill_cabin_guide_tokens_assigns_distinct_tokens(db_session):
    olivia = Cabin(name="Olivia")
    santiago = Cabin(name="Santiago", guide_token="already-set")
    db_session.add_all([olivia, santiago])
    db_session.commit()

    backfill_cabin_guide_tokens(db_session.get_bind())
    db_session.expire_all()

    olivia = db_session.query(Cabin).filter(Cabin.name == "Olivia").first()
    santiago = db_session.query(Cabin).filter(Cabin.name == "Santiago").first()
    assert olivia.guide_token  # got a fresh token
    assert santiago.guide_token == "already-set"  # untouched
    assert olivia.guide_token != santiago.guide_token


def test_backfill_cabin_guide_tokens_skips_missing_table():
    engine = create_engine("sqlite:///:memory:")
    backfill_cabin_guide_tokens(engine)  # no "cabins" table at all -- must not raise


def test_run_data_fixes_recategorizes_madalena_expenses_as_staff(db_session):
    db_session.add_all(
        [
            Expense(month=date(2026, 10, 1), category="other", description="Madalena", amount=200.0),
            Expense(month=date(2026, 11, 1), category="other", description="madalena cleaning", amount=200.0),
            Expense(month=date(2026, 10, 1), category="other", description="Printer paper", amount=10.0),
            Expense(month=date(2026, 10, 1), category="supplies", description="Madalena extra", amount=50.0),
        ]
    )
    db_session.commit()

    run_data_fixes(db_session.get_bind())
    db_session.expire_all()

    categories = {e.description: e.category for e in db_session.query(Expense).all()}
    assert categories["Madalena"] == "staff"
    assert categories["madalena cleaning"] == "staff"
    assert categories["Printer paper"] == "other"  # unrelated "Other" entry untouched
    assert categories["Madalena extra"] == "supplies"  # already correctly categorised -- untouched


def test_run_data_fixes_is_idempotent(db_session):
    db_session.add(Expense(month=date(2026, 10, 1), category="other", description="Madalena", amount=200.0))
    db_session.commit()

    run_data_fixes(db_session.get_bind())
    run_data_fixes(db_session.get_bind())  # must not error or double-apply
    db_session.expire_all()

    expense = db_session.query(Expense).first()
    assert expense.category == "staff"


def test_run_data_fixes_skips_missing_tables():
    engine = create_engine("sqlite:///:memory:")
    run_data_fixes(engine)  # no "expenses" table at all -- must not raise


def test_run_data_fixes_corrects_9mw_6krd_cabin_to_olivia(db_session):
    santiago = Cabin(name="Santiago")
    olivia = Cabin(name="Olivia")
    db_session.add_all([santiago, olivia])
    db_session.flush()
    db_session.add(
        Booking(
            external_id="9MW-6KRD",
            cabin_id=santiago.id,
            check_in=date(2026, 9, 14),
            check_out=date(2026, 9, 16),
            total_price=100.0,
        )
    )
    db_session.commit()

    run_data_fixes(db_session.get_bind())
    db_session.expire_all()

    booking = db_session.query(Booking).filter(Booking.external_id == "9MW-6KRD").first()
    assert booking.cabin_override_id == olivia.id
    assert booking.cabin_id == santiago.id  # the synced (wrong) value is left as-is


def test_run_data_fixes_does_not_clobber_a_manually_cleared_9mw_6krd_override(db_session):
    santiago = Cabin(name="Santiago")
    olivia = Cabin(name="Olivia")
    db_session.add_all([santiago, olivia])
    db_session.flush()
    booking = Booking(
        external_id="9MW-6KRD",
        cabin_id=santiago.id,
        check_in=date(2026, 9, 14),
        check_out=date(2026, 9, 16),
        total_price=100.0,
    )
    db_session.add(booking)
    db_session.commit()

    run_data_fixes(db_session.get_bind())
    db_session.expire_all()
    booking = db_session.query(Booking).filter(Booking.external_id == "9MW-6KRD").first()
    booking.cabin_override_id = None  # user manually clears the correction
    db_session.commit()

    run_data_fixes(db_session.get_bind())  # must not reapply since it's not idempotent-blind
    db_session.expire_all()

    booking = db_session.query(Booking).filter(Booking.external_id == "9MW-6KRD").first()
    assert booking.cabin_override_id is None


def test_run_data_fixes_merges_phantom_olivia_weekend_cabin_into_olivia(db_session):
    olivia = Cabin(name="Olivia")
    olivia_weekend = Cabin(name="Olivia weekend")
    db_session.add_all([olivia, olivia_weekend])
    db_session.flush()
    booking = Booking(
        external_id="R-1",
        cabin_id=olivia_weekend.id,
        check_in=date(2026, 9, 1),
        check_out=date(2026, 9, 3),
        total_price=100.0,
    )
    db_session.add(booking)
    db_session.commit()

    run_data_fixes(db_session.get_bind())
    db_session.expire_all()

    booking = db_session.query(Booking).filter(Booking.external_id == "R-1").first()
    assert booking.cabin_id == olivia.id
    assert db_session.query(Cabin).filter(Cabin.name == "Olivia weekend").count() == 0
    assert db_session.query(Cabin).count() == 1  # the phantom cabin is gone, not just emptied


def test_run_data_fixes_merges_phantom_olivia_weekend_cabin_override_too(db_session):
    santiago = Cabin(name="Santiago")
    olivia = Cabin(name="Olivia")
    olivia_weekend = Cabin(name="Olivia weekend")
    db_session.add_all([santiago, olivia, olivia_weekend])
    db_session.flush()
    booking = Booking(
        external_id="R-2",
        cabin_id=santiago.id,
        cabin_override_id=olivia_weekend.id,
        check_in=date(2026, 9, 1),
        check_out=date(2026, 9, 3),
        total_price=100.0,
    )
    db_session.add(booking)
    db_session.commit()

    run_data_fixes(db_session.get_bind())
    db_session.expire_all()

    booking = db_session.query(Booking).filter(Booking.external_id == "R-2").first()
    assert booking.cabin_override_id == olivia.id
    assert db_session.query(Cabin).filter(Cabin.name == "Olivia weekend").count() == 0


def test_run_data_fixes_is_a_no_op_when_no_phantom_cabin_exists(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.commit()

    run_data_fixes(db_session.get_bind())  # must not raise or delete the real Olivia
    db_session.expire_all()

    assert db_session.query(Cabin).filter(Cabin.name == "Olivia").count() == 1


def test_seed_cabin_extra_sections_adds_sim_and_links_sections_for_olivia_and_santiago(db_session):
    olivia = Cabin(name="Olivia")
    santiago = Cabin(name="Santiago")
    db_session.add_all([olivia, santiago])
    db_session.commit()

    seed_cabin_extra_sections(db_session.get_bind())
    db_session.expire_all()

    for cabin in (olivia, santiago):
        titles = {s.title for s in db_session.query(GuidebookSection).filter_by(cabin_id=cabin.id).all()}
        assert "Cartão SIM da cabana" in titles
        assert "Recursos úteis" in titles


def test_seed_cabin_extra_sections_appends_after_existing_sections(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.flush()
    db_session.add(GuidebookSection(cabin_id=olivia.id, title="Mais importante", position=0))
    db_session.commit()

    seed_cabin_extra_sections(db_session.get_bind())
    db_session.expire_all()

    sections = (
        db_session.query(GuidebookSection).filter_by(cabin_id=olivia.id).order_by(GuidebookSection.position).all()
    )
    assert [s.title for s in sections] == ["Mais importante", "Cartão SIM da cabana", "Recursos úteis"]
    assert [s.position for s in sections] == [0, 1, 2]


def test_seed_cabin_extra_sections_is_idempotent_and_respects_manual_deletion(db_session):
    olivia = Cabin(name="Olivia")
    db_session.add(olivia)
    db_session.commit()

    seed_cabin_extra_sections(db_session.get_bind())
    db_session.expire_all()
    sim_section = db_session.query(GuidebookSection).filter_by(cabin_id=olivia.id, title="Cartão SIM da cabana").one()
    db_session.delete(sim_section)  # owner decides they don't want this section
    db_session.commit()

    seed_cabin_extra_sections(db_session.get_bind())  # must not reinstate the deleted section
    db_session.expire_all()

    titles = {s.title for s in db_session.query(GuidebookSection).filter_by(cabin_id=olivia.id).all()}
    assert "Cartão SIM da cabana" not in titles
    assert "Recursos úteis" in titles  # the other seeded section is untouched


def test_seed_cabin_extra_sections_skips_cabins_it_does_not_know_about(db_session):
    other = Cabin(name="Guest House")
    db_session.add(other)
    db_session.commit()

    seed_cabin_extra_sections(db_session.get_bind())  # must not raise or add anything
    db_session.expire_all()

    assert db_session.query(GuidebookSection).filter_by(cabin_id=other.id).count() == 0


def test_seed_cabin_extra_sections_skips_missing_tables():
    engine = create_engine("sqlite:///:memory:")
    seed_cabin_extra_sections(engine)  # no tables at all -- must not raise
