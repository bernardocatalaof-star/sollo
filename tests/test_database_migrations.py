from datetime import date

from sqlalchemy import create_engine, inspect, text

from app.database import run_data_fixes, run_schema_migrations
from app.models import Booking, Cabin, Expense


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


def test_run_schema_migrations_is_a_no_op_on_a_fresh_database(db_session):
    # db_session's engine already has booked_at via create_all() -- re-running the
    # migration must not error or duplicate the column.
    run_schema_migrations(db_session.get_bind())


def test_run_schema_migrations_skips_missing_tables():
    engine = create_engine("sqlite:///:memory:")
    run_schema_migrations(engine)  # no "bookings" table at all -- must not raise


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
