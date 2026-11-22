import pytest
import requests

from blikvm import BliKVM


def client(fake, pw="good-pass"):
    return BliKVM(base=fake.url, user="admin", password=pw)


def test_login_sets_token_headers(fake):
    c = client(fake).login()
    assert c.s.headers["Authorization"] == "Bearer tok123" and c.s.headers["x-access-token"] == "tok123"


def test_bad_password_raises_and_sends_no_token(fake):
    with pytest.raises(requests.HTTPError):
        client(fake, "wrong").login()


def test_screenshot_is_saved(fake, tmp_path):
    fake.screenshot_png = b"\x89PNG-fake-bytes"
    out = client(fake).login().screenshot(str(tmp_path / "sub" / "shot.png"))
    assert open(out, "rb").read() == b"\x89PNG-fake-bytes"


def test_click_moves_then_clicks(fake):
    client(fake).login().click(847, 530, settle=0)
    posts = [c for c in fake.calls if c[1] == "/api/mouse/event"]
    assert posts[0][2] == {"x": 847, "y": 530, "action": "move"}
    assert posts[1][2] == {"x": 847, "y": 530, "button": "left", "action": "click"}
    assert all(c[3] == "Bearer tok123" for c in posts)


def test_paste_sends_text_and_layout(fake):
    client(fake).login().paste("hola", lang="es")
    assert [c for c in fake.calls if c[1] == "/api/hid/paste"][0][2] == {"text": "hola", "lang": "es"}


def test_credentials_come_from_the_environment(fake, monkeypatch):
    monkeypatch.setenv("BLIKVM_URL", fake.url); monkeypatch.setenv("BLIKVM_USER", "me"); monkeypatch.setenv("BLIKVM_PASS", "good-pass")
    c = BliKVM().login()
    assert c.base == fake.url and c.user == "me"
    assert [x for x in fake.calls if x[1] == "/api/login"][0][2]["username"] == "me"
