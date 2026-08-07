from sqlalchemy import create_engine, inspect, text

from app.database import run_schema_migrations


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
