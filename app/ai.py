# -*- coding: utf-8 -*-
"""「AI に頼む」(11/1)。今のエフェクトとつまみの範囲を渡して、変えるつまみだけを JSON で返させる。

AI は Claude Code の非対話実行(claude -p)。返った値は pedal.Pedal.set_control が範囲・音量の上限で切る。
決まり(11/1 ベーシストのプロ): 低音を削らない / 急に音量を上げない / 無いエフェクト・つまみを出さない /
変えるのは多くて 4 つ / 「再現しました」と言い切らない(「近づけた」まで)。
"""
from __future__ import annotations

import json
import re
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RULES = """あなたは{inst}の音作りを手伝うエンジニアです。ユーザーの頼みに合わせて、今のエフェクトのつまみを少しだけ変えます。
決まり:
- 下の一覧にあるエフェクト(instanceId)とつまみ(symbol)だけを使う。値は必ず min〜max の中。
- 変えるつまみは多くて 4 つ。オン/オフを変えてもよい(enabled)。
- {care}音量・出力・ゲイン系を大きく上げない。
- 日本語の一言の説明を付ける。そっくりにできたと言い切らず「近づけた」「〜寄りにした」まで。
答えは次の JSON だけ(前後に文章を書かない):
{"say": "一言", "changes": [{"instanceId": 1, "symbol": "drive", "value": 0.6}], "enable": [{"instanceId": 2, "enabled": true}]}
"""


CARE = {"bass": ("ベース", "低音を削らない(ローカット・ハイパスを強くしない)。"),
        "guitar": ("ギター", "耳に痛い高音(4kHz より上)を強くしすぎない。歪みの中で低音がぼやけないようにする。")}   # 11/1 KO「ギターでもベースでも使う」


def ask(request: str, state: dict, instrument: str = "bass") -> dict:
    effects = [{"instanceId": it["instanceId"], "name": it["name"], "enabled": it["enabled"],
                "controls": [{k: c[k] for k in ("symbol", "name", "value", "min", "max", "units")}
                             for c in it["controls"] if not c["toggle"]][:12]}
               for it in state["items"]]
    prompt = (RULES + "\n今のプリセット: " + state.get("preset", "") + "\n今のエフェクト:\n"
              + json.dumps(effects, ensure_ascii=False) + "\n\nユーザーの頼み: " + request)
    r = subprocess.run(["claude", "-p", "--model", "sonnet", prompt], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180, creationflags=NO_WINDOW)
    m = re.search(r"\{.*\}", r.stdout or "", re.S)
    if not m:
        raise RuntimeError("AI の答えが読めなかった: " + (r.stdout or r.stderr)[:200])
    out = json.loads(m.group(0))
    ids = {it["instanceId"]: {c["symbol"] for c in it["controls"]} for it in state["items"]}
    out["changes"] = [c for c in out.get("changes", [])[:4]
                      if c.get("instanceId") in ids and c.get("symbol") in ids[c["instanceId"]]]
    out["enable"] = [e for e in out.get("enable", [])[:2] if e.get("instanceId") in ids]
    return out
