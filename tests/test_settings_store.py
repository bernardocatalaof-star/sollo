from app.settings_store import get_setting, set_setting


def test_get_setting_returns_none_when_missing(db_session):
    assert get_setting(db_session, "missing") is None


def test_set_and_get_setting_round_trips(db_session):
    set_setting(db_session, "foo", "bar")
    assert get_setting(db_session, "foo") == "bar"


def test_set_setting_overwrites_existing_value(db_session):
    set_setting(db_session, "foo", "bar")
    set_setting(db_session, "foo", "baz")
    assert get_setting(db_session, "foo") == "baz"
