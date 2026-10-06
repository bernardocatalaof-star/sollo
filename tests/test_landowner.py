from app.landowner import clamp_to_landowner_floor, get_or_create_landowner_token, regenerate_landowner_token


def test_get_or_create_landowner_token_generates_one_when_missing(db_session):
    token = get_or_create_landowner_token(db_session)
    assert token


def test_get_or_create_landowner_token_is_stable_across_calls(db_session):
    first = get_or_create_landowner_token(db_session)
    second = get_or_create_landowner_token(db_session)
    assert first == second


def test_regenerate_landowner_token_changes_the_token(db_session):
    first = get_or_create_landowner_token(db_session)
    second = regenerate_landowner_token(db_session)
    assert second != first
    assert get_or_create_landowner_token(db_session) == second


def test_clamp_to_landowner_floor_pulls_earlier_months_forward():
    assert clamp_to_landowner_floor(2026, 8) == (2026, 9)
    assert clamp_to_landowner_floor(2025, 12) == (2026, 9)
    assert clamp_to_landowner_floor(2020, 1) == (2026, 9)


def test_clamp_to_landowner_floor_leaves_september_2026_onward_untouched():
    assert clamp_to_landowner_floor(2026, 9) == (2026, 9)
    assert clamp_to_landowner_floor(2026, 10) == (2026, 10)
    assert clamp_to_landowner_floor(2027, 1) == (2027, 1)
