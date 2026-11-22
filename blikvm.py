"""Tiny client for the BliKVM web API (login, screenshot, mouse, paste).

Endpoints used (seen on a BliKVM v4):
  POST /api/login            {"username", "password"}  -> token
  GET  /api/video/screenshot                           -> image
  POST /api/mouse/event      {"x", "y", "button", "action"}
  POST /api/hid/paste        {"text", "lang"}

Config comes from the environment so no credentials live in the code:
  BLIKVM_URL (default https://blikvm.local), BLIKVM_USER (default admin), BLIKVM_PASS
"""
import os
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # the BliKVM uses a self-signed cert


class BliKVM:
    def __init__(self, base=None, user=None, password=None, verify=False, timeout=10):
        self.base = (base or os.environ.get("BLIKVM_URL", "https://blikvm.local")).rstrip("/")
        self.user = user or os.environ.get("BLIKVM_USER", "admin")
        self.password = password if password is not None else os.environ.get("BLIKVM_PASS", "")
        self.verify, self.timeout = verify, timeout
        self.s = requests.Session()

    def _post(self, path, payload):
        r = self.s.post(f"{self.base}{path}", json=payload, timeout=self.timeout, verify=self.verify)
        r.raise_for_status()
        return r

    def login(self):
        r = self._post("/api/login", {"username": self.user, "password": self.password})
        data = r.json()
        token = (data.get("data") or {}).get("token") or data.get("token")
        if not token:
            raise RuntimeError("login worked but no token in the response")
        self.s.headers.update({"Authorization": f"Bearer {token}", "x-access-token": token})
        return self

    def screenshot(self, path):
        r = self.s.get(f"{self.base}/api/video/screenshot", timeout=self.timeout + 2, verify=self.verify)
        r.raise_for_status()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(r.content)
        return path

    def mouse_move(self, x, y):
        return self._post("/api/mouse/event", {"x": x, "y": y, "action": "move"})

    def click(self, x, y, button="left", settle=0.1):
        self.mouse_move(x, y)
        time.sleep(settle)
        return self._post("/api/mouse/event", {"x": x, "y": y, "button": button, "action": "click"})

    def paste(self, text, lang="en"):
        return self._post("/api/hid/paste", {"text": text, "lang": lang})
