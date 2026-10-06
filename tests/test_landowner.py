from app.landowner import get_or_create_landowner_token, regenerate_landowner_token


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
