# -*- coding: utf-8 -*-
"""Pico の LED を PiPedal の ON/OFF に合わせる(2026-10-09、Pi の上で常駐)。

困っていたこと: Pico を挿し直すと LED は全部 OFF から始まるのに、PiPedal 側は ON のまま、などでずれる。
スナップショット(長押し)で ON/OFF がまとめて変わったときも、Pico はそれを知らない。
PiPedal は MIDI で状態を送り返さない(ソースで確認、10/9)が、画面とのやり取り(WebSocket ws://<pi>/pipedal)で
onItemEnabledChanged などを全員に知らせている。それを受けて、Pico に CC80〜82 を送る(127 = ON、0 = OFF)。

- どのエフェクターがどのボタンかは、PiPedal のプリセットの MIDI 割り当て(__bypass に付けた CC)から読む
- Pico の挿し直し・プログラムの読み直しに備え、RESYNC_SEC ごとに今の状態を送り直す(1 回 3 個の小さな MIDI)
- MIDI の送信は amidi(ALSA の標準コマンド)。PiPedal が Pico の入力側を使っていても、出力側は使える(10/9 確認)

systemd の pedal-ledsync.service から起動。ログ: journalctl -u pedal-ledsync
"""
import json
import subprocess
import threading
import time

import websocket

URL = "ws://127.0.0.1/pipedal"
PICO_NAME = "Pico"
CCS = (80, 81, 82, 83)   # 1 / 2 / 3 / TUNER(PiPedal は 84〜90 を選べない)(BYPASS の CC85 は Pico とリレーだけで完結させるので送らない)
RESYNC_SEC = 5
WATCH = {"onItemEnabledChanged", "onPedalboardChanged", "onSelectedSnapshotChanged", "onPresetChanged",
         "onPresetsChanged", "onSnapshotModified", "currentPedalboard"}

states = {}
lock = threading.Lock()


def pico_port():
    out = subprocess.run(["amidi", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if PICO_NAME in line:
            return line.split()[1]
    return None


def send_states():
    port = pico_port()
    if not port:
        return
    with lock:
        msg = " ".join(f"B0 {cc:02X} {127 if on else 0:02X}" for cc, on in sorted(states.items()))
    if msg:
        subprocess.run(["amidi", "-p", port, "-S", msg], capture_output=True, timeout=5)


def read_states(pedalboard):
    found = {}

    def walk(items):
        for it in items or []:
            for b in it.get("midiBindings") or []:
                if b.get("symbol") == "__bypass" and b.get("bindingType") == 2 and b.get("control") in CCS:
                    found[b["control"]] = bool(it.get("isEnabled"))
            walk(it.get("topChain"))
            walk(it.get("bottomChain"))

    walk(pedalboard.get("items"))
    return found


class Client:
    def __init__(self):
        self.ws = None
        self.next_id = 1

    def request(self, message):
        self.next_id += 1
        self.ws.send(json.dumps([{"message": message, "replyTo": self.next_id}]))

    def on_open(self, ws):
        self.request("hello")
        self.request("currentPedalboard")

    def on_message(self, ws, text):
        try:
            frame = json.loads(text)
        except ValueError:
            return
        head = frame[0] if frame else {}
        name = head.get("message")
        if name not in WATCH:
            return
        body = frame[1] if len(frame) > 1 else None
        if name in ("currentPedalboard", "onPedalboardChanged") and isinstance(body, dict):
            pb = body.get("pedalboard", body)
            new = read_states(pb)
            with lock:
                changed = new != states
                states.clear()
                states.update(new)
            if changed:
                print("状態:", {cc: ("ON" if on else "OFF") for cc, on in sorted(new.items())}, flush=True)
                send_states()
        else:
            self.request("currentPedalboard")   # 細かい通知は、今の全体を聞き直して合わせる

    def run(self):
        while True:
            self.ws = websocket.WebSocketApp(URL, on_open=self.on_open, on_message=self.on_message)
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            print("PiPedal との接続が切れました。5 秒後につなぎ直します", flush=True)
            time.sleep(5)


def resync_loop():
    while True:
        time.sleep(RESYNC_SEC)
        try:
            send_states()
        except Exception as e:  # noqa: BLE001  常駐なので止まらない
            print("送り直しに失敗:", e, flush=True)


if __name__ == "__main__":
    threading.Thread(target=resync_loop, daemon=True).start()
    Client().run()
