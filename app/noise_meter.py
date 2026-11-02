# -*- coding: utf-8 -*-
"""弾いていないときのノイズを測る(11/1。pi/noise.py が時間切れで動かなくなったので PC 側で書き直し)。
並びの最初のエフェクトの「入力」と、最後のエフェクトの「出力」のピークを dBFS で出す。測っている間は弦を押さえて音量 0。
  python noise_meter.py [秒]
"""
import json
import math
import statistics
import sys
import time

import websocket

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
ws = websocket.create_connection("ws://kopedal/pipedal", timeout=20)
rid = [10]


def ask(msg, body=None):
    rid[0] += 1
    ws.send(json.dumps([{"message": msg, "replyTo": rid[0]}] + ([body] if body is not None else [])))
    while True:
        f = json.loads(ws.recv())
        if f and f[0].get("reply") == rid[0]:
            return f[1] if len(f) > 1 else None


db = lambda x: 20 * math.log10(x) if x > 0 else -120.0   # noqa: E731
ask("hello")
pb = ask("currentPedalboard")
items = [it for it in pb["items"] if it.get("isEnabled", True)] or pb["items"]
first, last = items[0], items[-1]
IN_ID, OUT_ID = -2, -3   # PiPedal の「入力」「出力」(本体の画面のメーターと同じ。エフェクトの番号だと届かなかった)
h1 = ask("addVuSubscription", IN_ID)
h2 = ask("addVuSubscription", OUT_ID)
ins, outs = [], []
t0 = time.time()
while time.time() - t0 < SECONDS:
    f = json.loads(ws.recv())
    head = f[0] if f else {}
    if head.get("message") == "onVuUpdate":
        if head.get("replyTo") is not None:   # 返事をしないと次が来ない
            ws.send(json.dumps([{"reply": head["replyTo"], "message": "onVuUpdate"}, True]))
        b = f[1]
        if b.get("instanceId") == IN_ID:
            ins.append(db(max(b.get("outputMaxValueL", 0), b.get("outputMaxValueR", 0), b.get("inputMaxValueL", 0))))
        if b.get("instanceId") == OUT_ID:
            outs.append(db(max(b.get("outputMaxValueL", 0), b.get("outputMaxValueR", 0))))
for h in {h1, h2}:
    ws.send(json.dumps([{"message": "removeVuSubscription"}, h]))
show = lambda xs: f"中央値 {statistics.median(xs):.1f} dBFS / 最大 {max(xs):.1f}" if xs else "読めなかった"   # noqa: E731
print("入口(UR12 から入った音):", show(ins))
print("出口(全部のエフェクトを通った音):", show(outs))
