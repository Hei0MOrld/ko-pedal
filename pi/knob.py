# -*- coding: utf-8 -*-
"""本体のつまみと左右ボタンで PiPedal の音作りを変える(2026-10-14、Pi の上で常駐する予定)。

Pico v6 が送るもの: つまみを回す = CC102(右 65 / 左 63)、つまみを押す = CC103、左ボタン = CC104、右ボタン = CC105
(押すと 127、離すと 0)。PiPedal は Pico を ALSA シーケンサーで受けているので(10/14 確認: Client 128 "PiPedal" が
16:0 に接続)、ここでも aseqdump で同じポートを聞ける。PiPedal へは画面と同じ websocket の setControl で値を送る
(10/14 実機で確認: chorus の depth を 1 → 1.1 → 1 に変えて戻せた)。

- 左右ボタン: 動かすつまみを前 / 次へ(エフェクトをまたいで、ペダルボードの並び順に。チューナーは飛ばす)
- 回す: 値を上げ下げ。押すたびに「細かく(範囲の 1/100)」と「大きく(1/20)」を切り替える
  整数・選択肢のつまみは 1 段ずつ、ON/OFF のつまみは回すと切り替わる
- 今の状態を STATE_FILE に書く(3.5 インチ画面ができたら、それを表示する)
- スマホでつまみを動かした分は、プリセット・スナップショットを変えたときに読み直すまで反映しない(試作の割り切り)

    python3 knob.py            # 常駐(Pico が無いあいだは待つ)
    python3 knob.py --test 105 105 102:65 102:65 103 102:63   # Pico なしで動きを確かめる
"""
import json
import math
import re
import subprocess
import sys
import threading
import time

import websocket

URL = "ws://127.0.0.1/pipedal"
PICO_NAME = "Pico"
CC_TURN, CC_PUSH, CC_LEFT, CC_RIGHT = 102, 103, 104, 105
SKIP_URI = ("toob-tuner",)           # チューナーは TUNER スイッチで使う
STATE_FILE = "/run/pedal-knob.json"
LINE = re.compile(r"Control change\s+\d+,\s*controller\s+(\d+),\s*value\s+(\d+)")
RELOAD_ON = ("onPedalboardChanged", "onPresetChanged", "onSelectedSnapshotChanged", "onPresetsChanged")


class Editor:
    def __init__(self):
        self.ws = None
        self.wslock = threading.Lock()   # つまみの処理と、プリセット変更の読み直しが同じ接続を使う
        self.rid = 1
        self.client_id = None
        self.plugins = {}             # uri -> {"name", "controls"}
        self.params = []              # [[instanceId, plugin name, control info, value]]
        self.pos = 0
        self.coarse = False

    # --- PiPedal との会話 -------------------------------------------------------------------
    def connect(self):
        self.ws = websocket.create_connection(URL, timeout=10)
        self.client_id = self.ask("hello")
        for p in self.ask("plugins") or []:
            self.plugins[p["uri"]] = {"name": p.get("label") or p.get("name", ""), "controls": p.get("controls") or []}
        self.reload()

    def ask(self, message, body=None):
        with self.wslock:
            self.rid += 1
            self.ws.send(json.dumps([{"message": message, "replyTo": self.rid}] + ([body] if body is not None else [])))
            t0 = time.time()
            while time.time() - t0 < 5:
                frame = json.loads(self.ws.recv())
                if frame and frame[0].get("reply") == self.rid:
                    return frame[1] if len(frame) > 1 else None
        return None

    def reload(self):
        """ペダルボードの並び順で、画面に出るつまみを並べ直す(今の値も)。選んでいたつまみはなるべく保つ。"""
        pb = self.ask("currentPedalboard") or {}
        keep = self.current_key()
        params = []

        def walk(items):
            for it in items or []:
                uri = it.get("uri", "")
                info = self.plugins.get(uri)
                if info and not any(s in uri for s in SKIP_URI):
                    values = {c["key"]: c["value"] for c in it.get("controlValues", [])}
                    for c in sorted(info["controls"], key=lambda c: c.get("index", 0)):
                        if c.get("is_input") and not c.get("not_on_gui") and c["symbol"] in values:
                            params.append([it["instanceId"], info["name"], c, values[c["symbol"]]])
                walk(it.get("topChain"))
                walk(it.get("bottomChain"))

        walk(pb.get("items"))
        self.params = params
        keys = [(p[0], p[2]["symbol"]) for p in params]
        self.pos = keys.index(keep) if keep in keys else min(self.pos, max(0, len(params) - 1))
        self.show()

    def current_key(self):
        if not self.params:
            return None
        p = self.params[self.pos]
        return (p[0], p[2]["symbol"])

    # --- つまみとボタン -----------------------------------------------------------------------
    def on_cc(self, cc, value):
        if not self.params:
            return
        if cc in (CC_LEFT, CC_RIGHT) and value >= 64:
            self.pos = (self.pos + (1 if cc == CC_RIGHT else -1)) % len(self.params)
        elif cc == CC_PUSH and value >= 64:
            self.coarse = not self.coarse
        elif cc == CC_TURN and value != 64:
            self.turn(1 if value > 64 else -1)
        else:
            return
        self.show()

    def turn(self, d):
        p = self.params[self.pos]
        inst, _, c, v = p
        lo, hi = float(c.get("min_value", 0)), float(c.get("max_value", 1))
        steps = c.get("range_steps") or 0
        if c.get("toggled_property"):
            new = hi if v <= lo else lo
        elif c.get("enumeration_property") and c.get("scale_points"):
            pts = sorted(float(s["value"]) for s in c["scale_points"])
            i = min(range(len(pts)), key=lambda k: abs(pts[k] - v))
            new = pts[max(0, min(len(pts) - 1, i + d))]
        elif c.get("integer_property") or 1 < steps <= 20:
            new = v + d * (1 if c.get("integer_property") else (hi - lo) / (steps - 1))
        elif c.get("is_logarithmic") and lo > 0:
            k = (math.log(hi) - math.log(lo)) / (20 if self.coarse else 100)
            new = math.exp(math.log(max(v, lo)) + d * k)
        else:
            new = v + d * (hi - lo) / (20 if self.coarse else 100)
        new = max(lo, min(hi, new))
        p[3] = new
        with self.wslock:
            self.ws.send(json.dumps([{"message": "setControl"},
                                     {"clientId": self.client_id, "instanceId": inst, "symbol": c["symbol"], "value": new}]))

    def show(self):
        if not self.params:
            return
        inst, plugin, c, v = self.params[self.pos]
        unit = c.get("units") or ""
        unit = "" if unit in ("none", "unknown") else unit
        text = f"{plugin} ▶ {c.get('name', c['symbol'])} = {v:.3g}{unit}" + ("（大きく）" if self.coarse else "")
        print(f"[{self.pos + 1}/{len(self.params)}] {text}", flush=True)
        state = {"index": self.pos, "count": len(self.params), "plugin": plugin, "name": c.get("name", c["symbol"]),
                 "value": v, "min": c.get("min_value"), "max": c.get("max_value"), "coarse": self.coarse}
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except OSError:
            pass                      # /run に書けない(root でない試運転)ときは画面用ファイルは省く


def pico_seq_port():
    out = subprocess.run(["aseqdump", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if PICO_NAME in line:
            return line.split()[0]       # "16:0"
    return None


def listen(ed):
    """aseqdump で Pico の CC を聞き続ける。Pico が抜けたら待ってつなぎ直す。"""
    while True:
        port = pico_seq_port()
        if not port:
            time.sleep(3)
            continue
        print("Pico を聞いています:", port, flush=True)
        proc = subprocess.Popen(["aseqdump", "-p", port], stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            m = LINE.search(line)
            if m:
                try:
                    ed.on_cc(int(m.group(1)), int(m.group(2)))
                except Exception as e:  # noqa: BLE001  常駐なので止まらない
                    print("つまみの処理で失敗:", e, flush=True)
        print("Pico の入力が途切れました。つなぎ直します", flush=True)
        time.sleep(2)


def watch_presets(ed):
    """プリセット・スナップショットを変えたら、つまみの一覧を作り直す(画面と同じ通知を別の接続で聞く)。"""
    def on_message(ws, text):
        try:
            name = json.loads(text)[0].get("message")
        except (ValueError, IndexError, AttributeError):
            return
        if name in RELOAD_ON:
            try:
                ed.reload()
            except Exception as e:  # noqa: BLE001
                print("読み直しに失敗:", e, flush=True)

    def on_open(ws):
        ws.send(json.dumps([{"message": "hello", "replyTo": 1}]))

    while True:
        websocket.WebSocketApp(URL, on_open=on_open, on_message=on_message).run_forever(ping_interval=20, ping_timeout=10)
        time.sleep(5)


if __name__ == "__main__":
    ed = Editor()
    while True:
        try:
            ed.connect()
            break
        except Exception as e:  # noqa: BLE001  PiPedal の起動待ち
            print("PiPedal につながりません。5 秒後にもう一度:", e, flush=True)
            time.sleep(5)
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        for tok in sys.argv[2:]:
            cc, _, val = tok.partition(":")
            ed.on_cc(int(cc), int(val or 127))
            time.sleep(0.3)
        sys.exit(0)
    threading.Thread(target=watch_presets, args=(ed,), daemon=True).start()
    listen(ed)
