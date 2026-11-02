# -*- coding: utf-8 -*-
"""TONE3000 の「選ぶ画面」(OAuth 2.0 + PKCE、prompt=select_tone)と、選んだ音のファイルのダウンロード(11/1)。

形は https://www.tone3000.com/api で確かめた:
  authorize: client_id(公開キー)・redirect_uri・response_type=code・code_challenge・code_challenge_method=S256・state・prompt
  callback: code・state・tone_id(canceled=true / error もありうる)
  token: POST application/x-www-form-urlencoded(grant_type, code, code_verifier, redirect_uri, client_id)→ access_token, refresh_token, expires_in
  models: GET /api/v1/models?tone_id= → data[] {id, name, size, model_url}。model_url は Bearer を付けて取る
  tone: GET /api/v1/tones/{id} → title, user {username, display_name, avatar_url}, images[](作者の表示はデザイン要件)
secret key は使わない(公開キーだけ)。トークンはこのフォルダの t3k_token.json(.gitignore)。
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API = "https://www.tone3000.com/api/v1"
CFG = json.loads((HERE / "t3k_config.json").read_text(encoding="utf-8"))
TOKEN_FILE = HERE / "t3k_token.json"
DL_DIR = Path.home() / "Downloads" / "TONE3000"      # 落としたファイルの控え(PC 側)
_pending: dict[str, tuple[str, float]] = {}              # state → (verifier, 期限)


def start_url() -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    now = time.time()
    for k in [k for k, (_, exp) in _pending.items() if exp < now]:
        _pending.pop(k, None)
    _pending[state] = (verifier, now + 600)                # 10 分で期限切れ・1 回だけ
    q = {"client_id": CFG["client_id"], "redirect_uri": CFG["redirect_uri"], "response_type": "code",
         "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
         "prompt": "select_tone", "format": "nam", "locale": "ja"}
    return f"{API}/oauth/authorize?" + urllib.parse.urlencode(q)


def finish(code: str, state: str) -> dict:
    verifier, exp = _pending.pop(state, (None, 0))
    if not verifier or exp < time.time():
        raise ValueError("やり直してください(時間切れか、ほかの画面から戻ってきました)")
    r = httpx.post(f"{API}/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                              "redirect_uri": CFG["redirect_uri"], "client_id": CFG["client_id"]}, timeout=30)
    r.raise_for_status()
    tok = r.json()
    tok["expires_at"] = time.time() + float(tok.get("expires_in", 3600))
    TOKEN_FILE.write_text(json.dumps(tok), encoding="utf-8")
    return tok


def token() -> str:
    tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    if tok.get("expires_at", 0) - 60 < time.time() and tok.get("refresh_token"):
        r = httpx.post(f"{API}/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                                  "client_id": CFG["client_id"]}, timeout=30)
        r.raise_for_status()
        new = r.json()
        new["expires_at"] = time.time() + float(new.get("expires_in", 3600))
        TOKEN_FILE.write_text(json.dumps(new), encoding="utf-8")
        tok = new
    return tok["access_token"]


def tone(tone_id: int) -> dict:
    h = {"Authorization": f"Bearer {token()}"}
    t = httpx.get(f"{API}/tones/{tone_id}", headers=h, timeout=30).json()
    m = httpx.get(f"{API}/models", params={"tone_id": tone_id, "page_size": 50}, headers=h, timeout=30)
    if m.status_code == 403:
        raise PermissionError("TONE3000 が音のファイルの取り出しを許していません(403)")
    m.raise_for_status()
    user = t.get("user") or {}
    return {"id": tone_id, "title": t.get("title", ""), "author": user.get("display_name") or user.get("username", ""),
            "avatar": user.get("avatar_url"), "image": (t.get("images") or [None])[0],
            "models": [{"id": x["id"], "name": x.get("name", ""), "size": x.get("size"), "url": x["model_url"]}
                       for x in m.json().get("data", [])]}


def download(tone_info: dict, model_id: int) -> Path:
    mdl = next(x for x in tone_info["models"] if x["id"] == model_id)
    DL_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in f'{tone_info["title"]} - {mdl["name"]}' if c not in '\\/:*?"<>|').strip()[:120]
    out = DL_DIR / (safe if safe.lower().endswith(".nam") else safe + ".nam")
    with httpx.stream("GET", mdl["url"], headers={"Authorization": f"Bearer {token()}"}, timeout=120,
                      follow_redirects=True) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    meta = {"tone_id": tone_info["id"], "title": tone_info["title"], "author": tone_info["author"], "model": mdl["name"],
            "source": f"https://www.tone3000.com/tones/{tone_info['id']}"}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")   # 作者の控え
    return out
