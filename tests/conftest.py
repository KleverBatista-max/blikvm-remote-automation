import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeBliKVM:
    """Imita la API del BliKVM: login con token, captura, ratón y pegar texto. Guarda lo que recibe."""

    def __init__(self, screenshot_png=b""):
        self.calls, self.screenshot_png, self.token = [], screenshot_png, "tok123"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.calls.append(("POST", self.path, body, self.headers.get("Authorization")))
                if self.path == "/api/login":
                    ok = body.get("password") == "good-pass"
                    return self._json(200 if ok else 401, {"data": {"token": outer.token}} if ok else {"msg": "bad"})
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    return self._json(401, {"msg": "no token"})
                self._json(200, {"ok": True})

            def do_GET(self):
                outer.calls.append(("GET", self.path, None, self.headers.get("Authorization")))
                if self.path != "/api/video/screenshot" or self.headers.get("Authorization") != f"Bearer {outer.token}":
                    return self._json(401, {"msg": "no"})
                self.send_response(200); self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(outer.screenshot_png))); self.end_headers(); self.wfile.write(outer.screenshot_png)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown(); self.srv.server_close()


@pytest.fixture
def fake():
    f = FakeBliKVM()
    yield f
    f.close()


def png_bytes(img):
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()
