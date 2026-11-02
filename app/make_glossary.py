# -*- coding: utf-8 -*-
"""つまみの日本語名と説明(上げると/下げると)を作って glossary.json に保存する(11/1 KO「スタートオフセット・ストレッチ・Sag Out とか
わからない。(訳)とか、いじるとどうなるのか見られるとありがたい」)。

入力 = ペダルに入っているエフェクトのつまみ(名前・単位・範囲・英語の説明 comment)。AI = claude -p(1 エフェクトずつ)。
作り直すときは glossary.json を消してから: python make_glossary.py
"""
import json
import re
import subprocess
from pathlib import Path

from pedal import Pedal

HERE = Path(__file__).resolve().parent
OUT = HERE / "glossary.json"
ASK = """ベース・ギター用エフェクトのつまみを、初心者にわかる日本語にしてください。
エフェクト: {plugin}(説明: {desc})
つまみの一覧(JSON): {controls}
各つまみについて、次の JSON を返してください(前後に文章を書かない)。
{{"<symbol>": {{"ja": "短い日本語名(8 文字くらいまで)", "help": "1〜2 文。『上げると〜、下げると〜』の形で、音がどう変わるかを具体的に"}} , ...}}
オン/オフのつまみは「オンにすると〜」。選択肢のつまみは選ぶと何が変わるか。専門用語は短く言い換える。"""


def main():
    g = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    p = Pedal()
    p.call("hello")
    for uri, info in p.plugins.items():
        if g.get(uri):   # 空(前回の失敗)は作り直す
            continue
        cs = [{"symbol": c["symbol"], "name": c.get("name"), "units": c.get("units"), "min": c.get("min_value"),
               "max": c.get("max_value"), "comment": (c.get("comment") or "")[:200],
               "choices": [s.get("label") for s in c.get("scale_points") or []] if c.get("enumeration_property") else []}
              for c in info.get("controls") or [] if c.get("is_input") and not c.get("not_on_gui")]
        if not cs:
            continue
        prompt = ASK.format(plugin=info.get("label") or info.get("name"), desc=(info.get("description") or "").strip()[:400],
                            controls=json.dumps(cs, ensure_ascii=False))
        r = subprocess.run(["claude", "-p", "--model", "sonnet", prompt], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        m = re.search(r"\{.*\}", r.stdout or "", re.S)
        try:
            g[uri] = json.loads(m.group(0)) if m else {}
        except ValueError:
            print("読めなかった:", info.get("label")); continue
        OUT.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        print("ok", info.get("label"), len(g[uri]))


if __name__ == "__main__":
    main()
