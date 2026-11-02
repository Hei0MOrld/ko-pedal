# -*- coding: utf-8 -*-
"""スマホのペダルアプリ(11/1)の、PiPedal とやりとりする部分。PC の上で動く(server.py が使う)。

PiPedal の websocket(ws://kopedal/pipedal、認証なし)に、pi/knob.py・pedal_ui.py と同じ形で話す。
メッセージの形は PiPedal のソース(src/PiPedalSocket.cpp)で確かめた:
  hello / plugins / currentPedalboard / getPresets / loadPreset(int64)/ setControl {clientId, instanceId, symbol, value}
  setPedalboardItemEnable {clientId, instanceId, enabled} / setOutputVolume(float)/ saveCurrentPreset
  updateCurrentPedalboard {clientId, pedalboard}(元に戻すで、まるごと送り直す)
安全(11/1 プロ 3 人): つまみは宣言された範囲の中だけ / 音量系は上限を低く・一度に上げる幅を制限 /
書く前に今の状態を控える(元に戻す 10 段)/ 書き込みは 1 本の鍵で順番に。SD への保存は「残す」を押したときだけ。
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import websocket

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

import os
ON_PI = os.path.exists("/var/pipedal")   # 11/1: ラズパイの上でも動く(会場では PC なしでペダル+スマホだけ)
URL = "ws://127.0.0.1/pipedal" if ON_PI else "ws://kopedal/pipedal"


def on_pedal(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """ペダルの上でコマンドを動かす(ラズパイならそのまま、PC なら ssh)。"""
    args = ["sh", "-c", cmd] if ON_PI else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "ko@kopedal", cmd]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NO_WINDOW)
UNDO_MAX = 10
LOUD = re.compile(r"(level|volume|gain|output|vol|master|trim)", re.I)   # 音量に効くつまみ
LOUD_STEP_MAX = 3.0        # dB のつまみを一度に上げてよい幅
OUT_VOLUME_MAX = 0.0       # 全体の出力音量(dB)の上限


class Pedal:
    def __init__(self, url: str = URL):
        self.url = url
        self.ws = None
        self.lock = threading.RLock()
        self.rid = 1
        self.client_id = None
        self.plugins: dict[str, dict] = {}
        self.undo: list[dict] = []

    # --- つなぐ・聞く ---------------------------------------------------------------------------
    def _connect(self):
        self.ws = websocket.create_connection(self.url, timeout=8)
        self.client_id = None
        self.client_id = self._ask("hello")
        self.plugins = {p["uri"]: p for p in (self._ask("plugins") or [])}

    def _ask(self, message, body=None, reply=True):
        self.rid += 1
        head = {"message": message}
        if reply:
            head["replyTo"] = self.rid
        self.ws.send(json.dumps([head] + ([body] if body is not None else [])))
        if not reply:
            return None
        t0 = time.time()
        while time.time() - t0 < 6:
            frame = json.loads(self.ws.recv())
            if frame and frame[0].get("reply") == self.rid:
                return frame[1] if len(frame) > 1 else None
        raise TimeoutError(f"PiPedal が {message} に答えない")

    def call(self, message, body=None, reply=True):
        """切れていたら 1 回だけつなぎ直してから送る。"""
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.ws is None:
                        self._connect()
                    return self._ask(message, body, reply)
                except (OSError, websocket.WebSocketException, TimeoutError):
                    self.ws = None
                    if attempt == 2:
                        raise

    # --- 読む -------------------------------------------------------------------------------
    def pedalboard(self) -> dict:
        return self.call("currentPedalboard") or {}

    def presets(self) -> dict:
        return self.call("getPresets") or {}

    def glossary(self) -> dict:
        """つまみの日本語名と説明(make_glossary.py が作る glossary.json)。ファイルが変わったら読み直す。"""
        f = Path(__file__).resolve().parent / "glossary.json"
        try:
            m = f.stat().st_mtime
        except OSError:
            return {}
        if getattr(self, "_gloss_m", None) != m:
            try:
                self._gloss, self._gloss_m = json.loads(f.read_text(encoding="utf-8")), m
            except ValueError:
                return getattr(self, "_gloss", {})
        return self._gloss

    def state(self) -> dict:
        """スマホの画面に出す形にまとめる(プリセット・並び・オン/オフ・主なつまみ)。"""
        gl = self.glossary()
        pb = self.pedalboard()
        pr = self.presets()
        items = []

        def walk(xs):
            for it in xs or []:
                uri = it.get("uri", "")
                info = self.plugins.get(uri)
                if info:
                    values = {c["key"]: c["value"] for c in it.get("controlValues", [])}
                    controls = []
                    for c in sorted(info.get("controls") or [], key=lambda c: c.get("index", 0)):
                        if c.get("is_input") and not c.get("not_on_gui") and c["symbol"] in values:
                            ja = (gl.get(uri) or {}).get(c["symbol"]) or {}
                            controls.append({"symbol": c["symbol"], "name": c.get("name", c["symbol"]),
                                             "ja": ja.get("ja", ""), "help": ja.get("help", ""),
                                             "value": values[c["symbol"]], "min": c.get("min_value", 0),
                                             "max": c.get("max_value", 1), "units": c.get("units") or "",
                                             "toggle": bool(c.get("toggled_property")),
                                             "choices": [{"label": s.get("label"), "value": s["value"]}
                                                         for s in c.get("scale_points") or []]
                                             if c.get("enumeration_property") else []})
                    file_props = {k: v for k, v in (it.get("pathProperties") or {}).items()}
                    items.append({"instanceId": it["instanceId"], "name": info.get("label") or info.get("name", ""),
                                  "title": it.get("title") or "", "uri": uri, "enabled": it.get("isEnabled", True),
                                  "controls": controls, "files": file_props})
                walk(it.get("topChain"))
                walk(it.get("bottomChain"))

        walk(pb.get("items"))
        factory = self.factory_names()
        presets = [{"id": p["instanceId"], "name": p["name"], "factory": p["name"] in factory} for p in pr.get("presets", [])]
        top = [it.get("instanceId") for it in pb.get("items") or []]
        for it in items:
            it["top"] = it["instanceId"] in top                   # 分岐の中のものは並べ替えない
            it["switch"] = next((self.SWITCH_CCS.index(b["control"]) + 1 for src in [pb.get("items") or []]
                                 for x in src if x.get("instanceId") == it["instanceId"]
                                 for b in x.get("midiBindings") or [] if b.get("symbol") == "__bypass" and b.get("control") in self.SWITCH_CCS), None)
            mf = it["files"].get("http://two-play.com/plugins/toob-nam#modelFile")
            if mf:
                try:
                    it["model"] = json.loads(mf).get("value", "").rsplit("/", 1)[-1].removesuffix(".nam")
                except ValueError:
                    pass
        return {"preset": pb.get("name", ""), "presetId": pr.get("selectedInstanceId"), "presets": presets,
                "items": items, "canUndo": len(self.undo)}

    # --- 書く(全部、書く前に控える)---------------------------------------------------------
    def _remember(self):
        pb = self.pedalboard()
        if pb:
            self.undo.append(copy.deepcopy(pb))
            del self.undo[:-UNDO_MAX]

    def _control_info(self, instance_id: int, symbol: str) -> tuple[dict, float]:
        pb = self.pedalboard()

        def find(xs):
            for it in xs or []:
                if it.get("instanceId") == instance_id:
                    return it
                hit = find(it.get("topChain")) or find(it.get("bottomChain"))
                if hit:
                    return hit
        it = find(pb.get("items"))
        if not it:
            raise ValueError("そのエフェクトは今の並びにない")
        info = self.plugins.get(it.get("uri", ""), {})
        c = next((c for c in info.get("controls") or [] if c["symbol"] == symbol and c.get("is_input")), None)
        if not c:
            raise ValueError("そのつまみは無い")
        now = next((v["value"] for v in it.get("controlValues", []) if v["key"] == symbol), c.get("default_value", 0))
        return c, float(now)

    def safe_value(self, instance_id: int, symbol: str, value: float) -> float:
        c, now = self._control_info(instance_id, symbol)
        lo, hi = float(c.get("min_value", 0)), float(c.get("max_value", 1))
        v = max(lo, min(hi, float(value)))
        if LOUD.search(symbol) or LOUD.search(c.get("name", "")):
            if (c.get("units") or "").lower() == "db":
                v = min(v, now + LOUD_STEP_MAX)                    # 音量は一度に +3dB まで
            else:
                v = min(v, now + (hi - lo) * 0.15)                 # dB 以外の音量つまみは範囲の 15% まで
        return v

    def set_control(self, instance_id: int, symbol: str, value: float, remember: bool = True) -> float:
        with self.lock:
            v = self.safe_value(instance_id, symbol, value)
            if remember:
                self._remember()
            self.call("setControl", {"clientId": self.client_id, "instanceId": instance_id, "symbol": symbol,
                                     "value": v}, reply=False)
            return v

    def set_enabled(self, instance_id: int, enabled: bool):
        with self.lock:
            self._remember()
            self.call("setPedalboardItemEnable", {"clientId": self.client_id, "instanceId": instance_id,
                                                  "enabled": bool(enabled)}, reply=False)

    def load_preset(self, preset_id: int):
        with self.lock:
            self._remember()
            self.call("loadPreset", int(preset_id), reply=False)

    def set_output_volume(self, db: float):
        self.call("setOutputVolume", float(min(OUT_VOLUME_MAX, db)), reply=False)

    def undo_last(self) -> bool:
        with self.lock:
            if not self.undo:
                return False
            pb = self.undo.pop()
            self.call("updateCurrentPedalboard", {"clientId": self.client_id, "pedalboard": pb}, reply=False)
            return True

    # --- 並びを組み立てる(11/1 KO「エフェクターのつながりが見えない・追加・並べ方・プリセットを自分で作りたい」)------
    # 並びは pedalboard の items(上の段だけ扱う。分岐(Split)は 1 ブロックとして動かすだけ)。変えたら updateCurrentPedalboard で丸ごと送る。
    # 足元のスイッチ 1/2/3 = CC80/81/82(__bypass の割り当て、TUNER は CC83)。並べ替えのたびに、最初の 3 つ(チューナー・ゲートを除く)へ付け直す
    # → ペダル本体の画面の 3 つのマスに出る(本体の画面はスイッチに割り当てたエフェクトだけを出す作り)。
    SWITCH_CCS = (80, 81, 82)
    NO_SWITCH = ("tuner", "noise-gate", "Split")

    def catalog(self) -> list[dict]:
        groups = [("アンプ・歪み", ("AmplifierPlugin",)), ("キャビ", ("SimulatorPlugin",)), ("EQ・音色", ("EQPlugin", "ParaEQPlugin", "MultiEQPlugin")),
                  ("空間系", ("ReverbPlugin", "DelayPlugin")), ("揺れ系", ("ChorusPlugin", "FlangerPlugin", "PhaserPlugin", "ModulatorPlugin")),
                  ("その他", ("UtilityPlugin", "MixerPlugin", "AnalyserPlugin"))]
        skip = ("loop", "record", "file player", "spectrum", "mix")
        out = []
        for title, types in groups:
            xs = []
            for p in self.plugins.values():
                name = p.get("label") or p.get("name", "")
                if p.get("plugin_type") in types and not any(s in name.lower() for s in skip):
                    stereo = (p.get("audio_inputs") or 0) > 1 or "Stereo" in name
                    xs.append({"uri": p["uri"], "name": name.replace("TooB ", "") + ("(ステレオ)" if stereo and "Stereo" not in name else ""),
                               "stereo": stereo})
            out.append({"title": title, "items": sorted(xs, key=lambda x: (x["stereo"], x["name"]))})
        return out

    def _new_item(self, uri: str, iid: int) -> dict:
        p = self.plugins[uri]
        values = [{"key": c["symbol"], "value": c.get("default_value", c.get("min_value", 0))}
                  for c in p.get("controls") or [] if c.get("is_input")]
        return {"instanceId": iid, "uri": uri, "isEnabled": True, "controlValues": values, "pluginName": p.get("name", ""),
                "midiBindings": [], "midiChannelBinding": None, "stateUpdateCount": 0, "lv2State": [False, {}],
                "lilvPresetUri": "", "pathProperties": {}, "title": "", "useModUi": False, "iconColor": "", "sideChainInputId": -1}

    def _assign_switches(self, pb: dict):
        n = 0
        for it in pb.get("items") or []:
            keep = [b for b in it.get("midiBindings") or [] if not (b.get("symbol") == "__bypass" and b.get("control") in self.SWITCH_CCS)]
            if n < 3 and not any(s in it.get("uri", "") for s in self.NO_SWITCH):
                keep.append({"channel": -1, "symbol": "__bypass", "bindingType": 2, "note": 72, "control": self.SWITCH_CCS[n],
                             "minControlValue": 0, "maxControlValue": 127, "minValue": 0, "maxValue": 1, "rotaryScale": 1,
                             "linearControlType": 0, "switchControlType": 1})
                n += 1
            it["midiBindings"] = keep

    def _edit(self, fn):
        with self.lock:
            self._remember()
            pb = copy.deepcopy(self.pedalboard())
            fn(pb)
            self._assign_switches(pb)
            self.call("updateCurrentPedalboard", {"clientId": self.client_id, "pedalboard": pb}, reply=False)
            time.sleep(0.3)

    def add_effect(self, uri: str, after: int | None = None):
        if uri not in self.plugins:
            raise ValueError("そのエフェクトはペダルに入っていません")

        def fn(pb):
            ids = []

            def walk(xs):
                for it in xs or []:
                    ids.append(int(it.get("instanceId") or 0))
                    walk(it.get("topChain")); walk(it.get("bottomChain"))
            walk(pb.get("items"))
            # 11/1: nextInstanceId が古く、足したものが NAM と同じ番号になった → 今ある一番大きい番号の次を使う
            iid = max([int(pb.get("nextInstanceId") or 0)] + [i + 1 for i in ids] + [1000])
            pb["nextInstanceId"] = iid + 1
            items = pb.setdefault("items", [])
            pos = next((k + 1 for k, it in enumerate(items) if it.get("instanceId") == after), len(items))
            items.insert(pos, self._new_item(uri, iid))
        self._edit(fn)

    def remove_effect(self, iid: int):
        self._edit(lambda pb: pb.__setitem__("items", [it for it in pb.get("items") or [] if it.get("instanceId") != iid]))

    def move_effect(self, iid: int, delta: int):
        def fn(pb):
            items = pb.get("items") or []
            k = next(k for k, it in enumerate(items) if it.get("instanceId") == iid)
            j = max(0, min(len(items) - 1, k + delta))
            items.insert(j, items.pop(k))
        self._edit(fn)

    def set_order(self, order: list[int]):
        """上の段の並びを、渡された instanceId の順にする(ドラッグでの並べ替え。11/1 KO「前後を簡単に入れ替えたい」)。"""
        def fn(pb):
            items = pb.get("items") or []
            pos = {iid: k for k, iid in enumerate(order)}
            items.sort(key=lambda it: pos.get(it.get("instanceId"), len(order)))
        self._edit(fn)

    def factory_names(self) -> set[str]:
        """最初から入っていたプリセット(Factory+Presets.bank)の名前。画面では隠す(消さない)。"""
        if getattr(self, "_factory", None) is None:
            try:
                if ON_PI:
                    data = json.load(open("/var/pipedal/presets/Factory+Presets.bank", encoding="utf-8"))
                    self._factory = {p["preset"]["name"] for p in data["presets"]}
                else:
                    r = on_pedal("python3 -c \"import json;print(json.dumps([p['preset']['name'] for p in json.load(open('/var/pipedal/presets/Factory+Presets.bank'))['presets']]))\"", 30)
                    self._factory = set(json.loads(r.stdout))
            except Exception:
                self._factory = set()
        return self._factory

    def new_preset(self, name: str):
        """空のプリセットを作って選ぶ → 名前を付けて今の位置の後ろに保存する。"""
        with self.lock:
            self._remember()
            cur = (self.presets() or {}).get("selectedInstanceId", -1)
            pid = self.call("newPreset")
            if pid:
                self.call("loadPreset", int(pid), reply=False)
                time.sleep(0.3)
            self.call("saveCurrentPresetAs", {"clientId": self.client_id, "bankInstanceId": -1, "name": name[:40],
                                              "saveAfterInstanceId": cur})

    def save_as(self, name: str):
        with self.lock:
            cur = (self.presets() or {}).get("selectedInstanceId", -1)
            self.call("saveCurrentPresetAs", {"clientId": self.client_id, "bankInstanceId": -1, "name": name[:40],
                                              "saveAfterInstanceId": cur})
        self.persist()

    def persist(self) -> str:
        r = on_pedal("sudo -n /usr/local/bin/pedal-persist")
        return (r.stdout or r.stderr).strip()

    def load_nam(self, pi_path: str) -> str:
        """今の並びの NAM に、ペダルの中のモデルファイルを読み込む。耳を守るため出力を 12dB 下げてから 2 秒で戻す(11/1 プロ)。
        NAM のモデルはパスのプロパティ(toob-nam#modelFile、値は {"otype_": "Path", "value": ...})で setPatchProperty。"""
        with self.lock:
            pb = self.pedalboard()

            def find(xs):
                for it in xs or []:
                    if "toob-nam" in it.get("uri", ""):
                        return it
                    hit = find(it.get("topChain")) or find(it.get("bottomChain"))
                    if hit:
                        return hit
            it = find(pb.get("items"))
            if not it:
                raise ValueError("今のプリセットに NAM(Neural Amp Modeler)がありません。NAM の入ったプリセットにしてから選んでください")
            inst = it["instanceId"]
            out = next((float(v["value"]) for v in it.get("controlValues", []) if v["key"] == "outputGain"), 0.0)
            self._remember()
            send = lambda v: self.call("setControl", {"clientId": self.client_id, "instanceId": inst,   # noqa: E731
                                                      "symbol": "outputGain", "value": float(v)}, reply=False)
            if out <= -30:                           # 前の失敗で下がったままのときは 0dB を元の値とみなす(11/1 -40dB で無音になった)
                out = 0.0
            send(max(-40.0, out - 12))
            try:
                # 返事は待たない(11/1: 大きいモデルは読み込みに時間がかかり、返事待ちで時間切れになった。値はちゃんと入る)
                self.call("setPatchProperty", {"instanceId": inst, "propertyUri": "http://two-play.com/plugins/toob-nam#modelFile",
                                               "value": {"otype_": "Path", "value": pi_path}}, reply=False)
            except Exception:
                send(out)                            # 失敗しても出力は元に戻す
                raise
        time.sleep(1.0)                              # 読み込みの間は小さいまま
        for k in (1, 2, 3, 4):                       # 2 秒で元の出力へ(鍵は放して、ほかの操作を止めない)
            time.sleep(0.5)
            send(out - 12 + 12 * k / 4)
        return it.get("title") or "NAM"

    def keep(self) -> str:
        """「残す」: 今の音をプリセットに上書きして、SD 本体にも書く(pedal-persist)。"""
        with self.lock:
            self.call("saveCurrentPreset", reply=False)
        time.sleep(1.0)
        return self.persist()


if __name__ == "__main__":   # 試し: 今の状態を読むだけ(何も変えない)
    st = Pedal().state()
    print("プリセット:", st["preset"], "/", len(st["presets"]), "個")
    for it in st["items"]:
        print(" ", "ON " if it["enabled"] else "OFF", it["name"], [c["name"] for c in it["controls"]][:6])
