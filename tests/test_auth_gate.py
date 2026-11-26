from app.auth_gate import _safe_next, is_public_path


def test_public_paths_stay_open():
    assert is_public_path("/guide/abc")
    assert is_public_path("/landowner/abc/monthly")
    assert is_public_path("/stock/p/abc")
    assert is_public_path("/static/style.css")
    assert is_public_path("/login")


def test_private_paths_need_login():
    for path in ["/", "/tarefas", "/stock", "/bookings", "/landowner-link/regenerate", "/monthly"]:
        assert not is_public_path(path), path


def test_safe_next_blocks_offsite_redirects():
    assert _safe_next("/tarefas?quem=Leo") == "/tarefas?quem=Leo"
    assert _safe_next("//evil.com") == "/"
    assert _safe_next("https://evil.com") == "/"
    assert _safe_next(None) == "/"
