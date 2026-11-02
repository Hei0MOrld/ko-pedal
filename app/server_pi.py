# -*- coding: utf-8 -*-
"""スマホのペダルアプリの、ラズパイ版のサーバー(11/1 KO「ラズパイを入れた本体とスマホだけで完結できるように」)。

Python に最初から入っている http.server だけで動く(SD の保護を外して何かを入れる必要がない)。ポート 8080。
  スマホ: 家の Wi-Fi なら http://<ペダルの IP>:8080/ 、会場ではペダルが出す Wi-Fi につないで同じく :8080
できること: プリセット・オン/オフ・並べ替え・足す/外す・つまみ(日本語の説明つき)・元に戻す・保存。
「音を探す(TONE3000)」「AI に頼む」は、ネットと PC が要るので PC 版(https://<PC名>.<tailnet>.ts.net/)へのリンクにする。
systemd: pedal-app.service(/home/ko/pedal/app/server_pi.py)。
"""
from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pedal import Pedal

HERE = Path(__file__).resolve().parent
PORT = 8080
pedal = Pedal()
lock = threading.Lock()


def handle(path: str, body: dict):
    """API の本体。戻り値は JSON にできるもの。"""
    p = pedal
    if path == "/api/state":
        return p.state()
    if path == "/api/catalog":
        return p.catalog()
    if path == "/api/preset":
        p.load_preset(int(body["id"]))
    elif path == "/api/enable":
        p.set_enabled(int(body["instanceId"]), bool(body["enabled"]))
    elif path == "/api/control":
        return {"value": p.set_control(int(body["instanceId"]), str(body["symbol"]), float(body["value"]))}
    elif path == "/api/add":
        p.add_effect(str(body["uri"]), body.get("after"))
    elif path == "/api/remove":
        p.remove_effect(int(body["instanceId"]))
    elif path == "/api/move":
        p.move_effect(int(body["instanceId"]), int(body["delta"]))
    elif path == "/api/order":
        p.set_order([int(x) for x in body["order"]])
    elif path == "/api/newpreset":
        p.new_preset(str(body.get("name") or "自分の音"))
    elif path == "/api/saveas":
        p.save_as(str(body.get("name") or "自分の音"))
    elif path == "/api/undo":
        ok = p.undo_last()
        return {"undone": ok, **p.state()}
    elif path == "/api/keep":
        return {"saved": p.keep()}
    else:
        raise KeyError(path)
    return p.state()


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, data: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _api(self, body: dict):
        try:
            with lock:
                self._json(200, handle(self.path.split("?")[0], body))
        except KeyError:
            self._json(404, {"detail": "ありません"})
        except Exception as e:   # ペダルが切れている等。音は変わっていない
            self._json(503, {"detail": f"ペダルにつながりません(音はそのままです): {type(e).__name__}: {e}"[:200]})

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            return self._api({})
        if path in ("/", "/index.html"):
            html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
            html = html.replace("<head>", "<head>\n<script>window.ON_PI = true;</script>", 1)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        f = (HERE / path.lstrip("/")).resolve()
        if f.is_file() and HERE in f.parents:
            return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        self._api(body)

    def log_message(self, *a):   # 1 秒ごとの読み直しで記録が埋まらないように
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
