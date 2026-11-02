# -*- coding: utf-8 -*-
"""スマホのペダルアプリのサーバー(11/1)。PC の 127.0.0.1:8740 で待ち、tailscale serve で KO の機器だけに https で出す。

  python server.py            (tailscale serve --bg 8740 で https://<PC名>.<tailnet>.ts.net/ に出る)

画面は static/index.html(日本語の 1 枚)。ペダルとのやりとりは pedal.py、AI は ai.py。
tailscale serve 経由の要求には Tailscale-User-Login が付く。付いていて KO 以外なら断る(Funnel は使わない)。
書き込みは POST だけ。Origin が自分以外なら断る。
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import ai
from pedal import Pedal

HERE = Path(__file__).resolve().parent
ALLOWED_LOGINS = {s for s in os.environ.get("PEDAL_APP_LOGINS", "").split(",") if s}   # 空なら tailnet の誰でも(KO だけの tailnet)
app = FastAPI()
pedal = Pedal()


@app.middleware("http")
async def guard(request: Request, call_next):
    login = request.headers.get("tailscale-user-login")
    if login and ALLOWED_LOGINS and login not in ALLOWED_LOGINS:
        return JSONResponse({"error": "この機器からは使えません"}, status_code=403)
    if request.method == "POST":
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin and not origin.endswith("//" + host):
            return JSONResponse({"error": "よその画面からは操作できません"}, status_code=403)
    return await call_next(request)


def run(fn, *a):
    try:
        return fn(*a)
    except Exception as e:   # ペダルが切れている等は画面に一行で出す(音は変わっていない)
        raise HTTPException(503, f"ペダルにつながりません(音はそのままです): {type(e).__name__}")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/state")
def state():
    return run(pedal.state)


@app.post("/api/preset")
async def preset(req: Request):
    body = await req.json()
    run(pedal.load_preset, int(body["id"]))
    return run(pedal.state)


@app.post("/api/enable")
async def enable(req: Request):
    body = await req.json()
    run(pedal.set_enabled, int(body["instanceId"]), bool(body["enabled"]))
    return run(pedal.state)


@app.post("/api/control")
async def control(req: Request):
    body = await req.json()
    v = run(pedal.set_control, int(body["instanceId"]), str(body["symbol"]), float(body["value"]))
    return {"value": v}


@app.get("/api/catalog")
def catalog():
    return run(pedal.catalog)


@app.post("/api/add")
async def add(req: Request):
    body = await req.json()
    run(pedal.add_effect, str(body["uri"]), body.get("after"))
    return run(pedal.state)


@app.post("/api/remove")
async def remove(req: Request):
    body = await req.json()
    run(pedal.remove_effect, int(body["instanceId"]))
    return run(pedal.state)


@app.post("/api/move")
async def move(req: Request):
    body = await req.json()
    run(pedal.move_effect, int(body["instanceId"]), int(body["delta"]))
    return run(pedal.state)


@app.post("/api/order")
async def order(req: Request):
    body = await req.json()
    run(pedal.set_order, [int(x) for x in body["order"]])
    return run(pedal.state)


@app.post("/api/newpreset")
async def newpreset(req: Request):
    body = await req.json()
    run(pedal.new_preset, str(body.get("name") or "自分の音"))
    return run(pedal.state)


@app.post("/api/saveas")
async def saveas(req: Request):
    body = await req.json()
    run(pedal.save_as, str(body.get("name") or "自分の音"))
    return run(pedal.state)


@app.post("/api/undo")
def undo():
    ok = run(pedal.undo_last)
    return {"undone": ok, **run(pedal.state)}


@app.post("/api/keep")
def keep():
    return {"saved": run(pedal.keep)}


@app.post("/api/ai")
async def ask_ai(req: Request):
    body = await req.json()
    text = str(body.get("text", "")).strip()[:300]
    if not text:
        raise HTTPException(400, "頼みを書いてください")
    st = run(pedal.state)
    try:
        plan = ai.ask(text, st, "guitar" if body.get("instrument") == "guitar" else "bass")
    except Exception as e:
        raise HTTPException(502, f"AI が答えられませんでした(音はそのままです): {e}")
    applied = []
    pedal.undo.append(run(pedal.pedalboard))          # AI の変更はまとめて 1 回で戻せるように
    for e in plan["enable"]:
        run(pedal.call, "setPedalboardItemEnable", {"clientId": pedal.client_id, "instanceId": e["instanceId"],
                                                   "enabled": bool(e["enabled"])}, False)
    for c in plan["changes"]:
        before = next((x["value"] for it in st["items"] if it["instanceId"] == c["instanceId"]
                       for x in it["controls"] if x["symbol"] == c["symbol"]), None)
        v = run(pedal.set_control, c["instanceId"], c["symbol"], float(c["value"]), False)
        name = next((x["name"] for it in st["items"] if it["instanceId"] == c["instanceId"]
                     for x in it["controls"] if x["symbol"] == c["symbol"]), c["symbol"])
        applied.append({"name": name, "before": before, "after": v})
    return {"say": plan.get("say", ""), "applied": applied, **run(pedal.state)}


# ---- 音を探す(TONE3000 の選ぶ画面 → 戻る → 音のファイルを選ぶ → ペダルへ)----------------------------------
import sys                                                        # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse      # noqa: E402

import t3k                                                        # noqa: E402

sys.path.insert(0, str(HERE.parent / "tools"))
import add_nam                                                    # noqa: E402

_tones: dict[int, dict] = {}


@app.get("/t3k/start")
def t3k_start():
    return RedirectResponse(t3k.start_url())


@app.get("/t3k/callback")
def t3k_callback(code: str = "", state: str = "", tone_id: int = 0, canceled: str = "", error: str = ""):
    if canceled or error or not code:
        return RedirectResponse("/?msg=" + ("やめました" if canceled else "TONE3000 でエラー: " + error))
    try:
        t3k.finish(code, state)
        info = t3k.tone(tone_id)
    except Exception as e:
        return RedirectResponse("/?msg=" + f"TONE3000 から受け取れませんでした(音はそのままです): {e}")
    _tones[tone_id] = info
    return RedirectResponse(f"/?tone={tone_id}")


@app.get("/api/tone/{tone_id}")
def get_tone(tone_id: int):
    info = _tones.get(tone_id) or t3k.tone(tone_id)
    _tones[tone_id] = info
    return {k: v for k, v in info.items() if k != "models"} | {"models": [{k: m[k] for k in ("id", "name", "size")} for m in info["models"]]}


@app.post("/api/tone/install")
async def install_tone(req: Request):
    body = await req.json()
    tone_id, model_id = int(body["toneId"]), int(body["modelId"])
    info = _tones.get(tone_id) or t3k.tone(tone_id)
    try:
        local = t3k.download(info, model_id)
        add_nam.send(local)                                       # ペダルへ(SD 本体にも)
        name = run(pedal.load_nam, f"{add_nam.DEST}/{local.name}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"入れられませんでした(音はそのままです): {e}")
    return {"loaded": local.stem, "into": name, "author": info["author"], **run(pedal.state)}


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

if __name__ == "__main__":
    if sys.stdout is None:   # pythonw(画面なし)では出力先が無く uvicorn が落ちる → ファイルへ
        sys.stdout = sys.stderr = open(HERE / "server.log", "a", encoding="utf-8", buffering=1)
    uvicorn.run(app, host="127.0.0.1", port=8740, log_level="warning", log_config=None)
