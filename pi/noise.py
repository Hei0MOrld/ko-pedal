"""弾いていないときの入口のノイズを測る(チェーンの最初のエフェクトの入力 VU)。

使い方: python3 noise.py [秒数] [チェーンの何番目か(0 から)]  → 入力ピークの中央値と最大を dBFS で出す。
測っている間はベースに触らない。
"""
import json
import math
import statistics
import sys
import time

import websocket

URL = "ws://127.0.0.1/pipedal"
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0


def db(x):
    return 20 * math.log10(x) if x > 0 else -120.0


ws = websocket.create_connection(URL, timeout=5)
ws.send(json.dumps([{"message": "hello", "replyTo": 1}]))
ws.send(json.dumps([{"message": "currentPedalboard", "replyTo": 2}]))
first = None
values = []
end = None
while end is None or time.time() < end:
    frame = json.loads(ws.recv())
    head = frame[0] if frame else {}
    body = frame[1] if len(frame) > 1 else None
    msg = head.get("message")
    if head.get("reply") == 2 and isinstance(body, dict):
        items = body.get("items") or []
        first = items[int(sys.argv[2]) if len(sys.argv) > 2 else 0]   # 2 つ目の引数 = チェーンの何番目か
        print("測る場所:", first.get("pluginName"), "の入力 (instanceId", first.get("instanceId"), ")", flush=True)
        ws.send(json.dumps([{"message": "addVuSubscription", "replyTo": 3}, first["instanceId"]]))
        end = time.time() + SECONDS
    if msg == "onVuUpdate" and head.get("replyTo") is not None:
        # 返事をしないと PiPedal は次を送ってこない
        ws.send(json.dumps([{"reply": head["replyTo"], "message": msg}, True]))
        if isinstance(body, dict) and first and body.get("instanceId") == first["instanceId"]:
            values.append(max(body.get("inputMaxValueL", 0), body.get("inputMaxValueR", 0)))
ws.close()
if not values:
    print("VU が来なかった")
    sys.exit(1)
print(f"{len(values)} 回: 中央値 {db(statistics.median(values)):.1f} dBFS / 最大 {db(max(values)):.1f} dBFS")
