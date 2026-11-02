# -*- coding: utf-8 -*-
"""ペダルの画面とつまみ(2026-10-20、手順 E-3。ledsync.py の役目もここに入れた)。

プロ 3 人(床置きマルチの UI・ベーシスト・組み込み音響)と決めた v1:
- HOME: 上にプリセット名、その下に VOL、下に 1/2/3 のエフェクトの札(リングと同じ色、ON で塗りつぶし)。
  つまみを回す = 全体の音量(0.5 dB/クリック、プリセットの値 +3 dB まで。10 秒触っていないと最初の 1 クリックは表示だけ)。
  左右ボタン = 札の選択(最後に踏んだスイッチが選ばれる)。つまみを押す = 選んだエフェクトの編集へ。
- EDIT: 回す = 値、左右 = つまみの切り替え、押す = HOME へ(8 秒触らなくても戻る)。
- 値を変えたら「● 編集」。HOME でつまみを 2 秒長押し → 確認(押す = 保存 / 左右 = やめる)→ 今のプリセットに上書き(10/21)。
  SD は保護中なので、PiPedal が保存したあと pedal-persist(sudo)でプリセットのファイルだけ SD 本体へ写す。
- TUNER / BYPASS 中は画面全体で知らせる。
- Pico の LED 用に CC80〜83 の状態を 5 秒ごとに送り直す(これが止まると Pico はリレーを素通りに戻す)。

MIDI は ALSA シーケンサー経由(mido + python-rtmidi)。PiPedal も同じ Pico の出力を聞いているが、シーケンサーは全員に配るので取り合わない。
画面は spidev で、前の絵と違う四角だけ送る。systemd の pedal-ui.service から起動、ログは journalctl -u pedal-ui。
"""
import json
import math
import queue
import subprocess
import threading
import time

import gpiod
import mido
import spidev
import websocket
from gpiod.line import Direction, Value
from PIL import Image, ImageChops, ImageDraw, ImageFont

URL = "ws://127.0.0.1/pipedal"
PICO_NAME = "Pico 2"
W, H = 480, 320
DC, RST = 24, 25
SPI_HZ = 16_000_000

SWITCH_CCS = (80, 81, 82)
TUNER_CC, BYPASS_CC = 83, 85
ENC_CC, PUSH_CC, LEFT_CC, RIGHT_CC = 102, 103, 104, 105
RESYNC_SEC = 5
WAKE_SEC = 10            # これだけ触っていないと、最初の 1 クリックは音量を変えずに表示だけ
EDIT_IDLE_SEC = 8
OVERLAY_SEC = 1.5
VOL_STEP, VOL_MIN, VOL_HEADROOM = 0.5, -40.0, 3.0
PREVIEW_EVERY, COMMIT_AFTER = 0.025, 0.3
FAST_CLICK = 0.04        # これより短い間隔のクリックは 4 倍進む
SAVE_HOLD = 2.0          # HOME でつまみをこれだけ押し続けると保存の確認
SAVE_TIMEOUT = 5.0       # PiPedal の「保存した」が来なければ失敗にする
RESULT_SEC = 2.0
PERSIST = "/usr/local/bin/pedal-persist"

FONT_JP = "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf"
FONT_NUM = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

RING = {0: (0, 200, 80), 1: (40, 110, 255), 2: (230, 40, 40)}   # Pico のリングと同じ色(1 緑・2 青・3 赤)
GREY, DARK, ORANGE = (150, 150, 150), (28, 28, 28), (255, 150, 0)

# つまみに出すもの(プロの案。範囲は ToobAmp の .ttl から)。(symbol, 表示名, 単位, 1 クリック, 最小, 最大)
PARAMS = {
    "http://two-play.com/plugins/toob-nam": ("AMP", [
        ("gate", "ゲート", "dB", 2, -120, 0),
        ("inputGain", "ドライブ", "dB", 0.5, -40, 40),
        ("mid", "ミドル", "", 0.25, 0, 10),
        ("bass", "ベース", "", 0.25, 0, 10),
        ("treble", "トレブル", "", 0.25, 0, 10),
        ("outputGain", "出力", "dB", 0.5, -40, 40),
    ]),
    "http://two-play.com/plugins/toob-delay": ("DELAY", [
        ("delay", "タイム", "ms", 10, 5, 3000),
        ("feedback", "フィードバック", "%", 5, 0, 100),
        ("level", "ミックス", "%", 5, 0, 100),
    ]),
    "http://two-play.com/plugins/toob-convolution-reverb-stereo": ("REVERB", [
        ("reverb_mix", "リバーブ量", "dB", 1, -40, 40),
        ("time", "長さ", "s", 0.5, 0.1, 30),
    ]),
    "http://two-play.com/plugins/toob-convolution-reverb": ("REVERB", [
        ("reverb_mix", "リバーブ量", "dB", 1, -40, 40),
        ("time", "長さ", "s", 0.5, 0.1, 30),
    ]),
    "http://two-play.com/plugins/toob-parametric-eq": ("EQ", [
        ("lfLevel", "ロー", "dB", 0.5, -15, 15),
        ("lmfLevel", "ローミッド", "dB", 0.5, -15, 15),
        ("hmfLevel", "ハイミッド", "dB", 0.5, -15, 15),
        ("hfLevel", "ハイ", "dB", 0.5, -15, 15),
        ("hiCut", "ハイカット", "kHz", 0.25, 1, 21),
        ("loCut", "ローカット", "Hz", 5, 20, 350),
    ]),
}
TILE_PARAM = {"AMP": "inputGain"}   # 札に出す値(ほかは 1 番目)


def model_short(path_props: dict) -> str:
    """NAM のモデルファイル名から札に出す短い名前(例: 「Ibanez TS9 Tube Screamer - … Drive 7」→「TS9」)。11/1"""
    raw = path_props.get("http://two-play.com/plugins/toob-nam#modelFile")
    try:
        name = json.loads(raw).get("value", "") if isinstance(raw, str) else ""
    except ValueError:
        return ""
    name = name.rsplit("/", 1)[-1].removesuffix(".nam").split(" - ")[0]
    words = [w for w in name.replace("_", " ").split() if w.lower() not in ("boss", "ibanez", "fender", "the", "pedal", "amp")]
    short = next((w for w in words if any(ch.isdigit() for ch in w)), words[0] if words else "")
    return short[:8]
EQ_URI = "http://two-play.com/plugins/toob-parametric-eq"
NAM_URI = "http://two-play.com/plugins/toob-nam"
OUT_ID = -3              # PiPedal の「出力」の instanceId(メーター用)
METER_FLOOR, CLIP_HOLD = -48.0, 1.0
NOTE_NAMES = ["C", "C#", "D", "E♭", "E", "F", "F#", "G", "A♭", "A", "B♭", "B"]   # PiPedal のチューナーと同じ


def fmt(v, unit):
    if unit in ("ms", "Hz", "%"):
        return f"{v:.0f} {unit}"
    if unit == "dB":
        return f"{v:+.1f} dB"
    if unit in ("s", "kHz"):
        return f"{v:.2f} {unit}"
    return f"{v:.2f}"


# ---------------- 画面 ----------------
class Lcd:
    def __init__(self):
        self.req = gpiod.request_lines("/dev/gpiochip0", consumer="pedal-ui", config={
            (DC, RST): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)})
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = SPI_HZ
        self.spi.mode = 0
        self.shown = None

    def cmd(self, c, data=b""):
        self.req.set_value(DC, Value.INACTIVE)
        self.spi.writebytes([c])
        if data:
            self.req.set_value(DC, Value.ACTIVE)
            self.spi.writebytes2(bytes(data))

    def init(self):
        self.req.set_value(RST, Value.INACTIVE)
        time.sleep(0.02)
        self.req.set_value(RST, Value.ACTIVE)
        time.sleep(0.15)
        for c, d in ((0xC0, [0x17, 0x15]), (0xC1, [0x41]), (0xC5, [0x00, 0x12, 0x80]), (0x36, [0x28]),
                     (0x3A, [0x66]), (0xB0, [0x00]), (0xB1, [0xA0]), (0xB4, [0x02]), (0xB6, [0x02, 0x02, 0x3B]),
                     (0xE9, [0x00]), (0xF7, [0xA9, 0x51, 0x2C, 0x82])):
            self.cmd(c, d)
        self.cmd(0x11)
        time.sleep(0.12)
        self.cmd(0x29)
        self.shown = None

    def show(self, img):
        """前に出した絵と違う四角だけ送る(全面は 0.29 秒かかるため)"""
        box = (0, 0, W, H) if self.shown is None else ImageChops.difference(img, self.shown).getbbox()
        if not box:
            return
        x0, y0, x1, y1 = box
        self.cmd(0x2A, [x0 >> 8, x0 & 0xFF, (x1 - 1) >> 8, (x1 - 1) & 0xFF])
        self.cmd(0x2B, [y0 >> 8, y0 & 0xFF, (y1 - 1) >> 8, (y1 - 1) & 0xFF])
        self.cmd(0x2C, img.crop(box).tobytes())
        self.shown = img.copy()


_fonts = {}


def font(size, jp=True):
    k = (size, jp)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(FONT_JP if jp else FONT_NUM, size)
    return _fonts[k]


def fit(d, text, size, maxw, jp=True):
    """幅に収まるまで文字を小さくする"""
    while size > 16 and d.textlength(text, font=font(size, jp)) > maxw:
        size -= 2
    return font(size, jp)


# ---------------- 状態 ----------------
class Ui:
    def __init__(self):
        self.q = queue.Queue()
        self.ws = None
        self.client_id = None
        self.hello_id = None
        self.next_id = 1
        self.connected = False
        self.name = ""
        self.items = {}          # instanceId → {"uri", "name", "enabled", "values": {symbol: value}}
        self.switch = {}         # 0/1/2(スイッチ 1/2/3)→ instanceId
        self.tuner_id = None
        self.out_vol = 0.0
        self.base = {}           # 「● 編集」の比べる元(プリセットを読んだときの値)
        self.base_vol = 0.0
        self.reset_next = True
        self.bypass = False
        self.mode = "home"
        self.sel = 0             # 選んでいる札(0〜2)
        self.param = 0
        self.last_touch = 0.0
        self.overlay_until = 0.0
        self.last_click = 0.0
        self.pending = {}        # (instanceId, symbol) → 値(まだ setControl していない)
        self.pending_vol = None
        self.last_preview = 0.0
        self.last_turn = 0.0
        self.midi_in = self.midi_out = None
        self.last_led = 0.0
        self.meter_db = METER_FLOOR  # 出力の大きさ(2 dB きざみ)
        self.clip_until = 0.0
        self.tuner_note = None       # チューナーの音(MIDI ノート番号、小数つき)。None = 音が来ていない
        self.tuner_req = self.tuner_handle = None
        self.push_at = None          # HOME でつまみを押した時刻(離したら編集へ、2 秒で保存の確認)
        self.save_started = 0.0
        self.result = None           # 保存の結果 (うまくいったか, 消す時刻)

    # ---- PiPedal ----
    def request(self, message, body=None):
        self.next_id += 1
        frame = [{"message": message, "replyTo": self.next_id}] + ([body] if body is not None else [])
        try:
            self.ws.send(json.dumps(frame))
        except Exception as e:  # noqa: BLE001  つなぎ直しは ws のスレッドがやる
            print("送れなかった:", message, e, flush=True)
        return self.next_id

    def send(self, message, body):
        try:
            self.ws.send(json.dumps([{"message": message}, body]))
        except Exception as e:  # noqa: BLE001
            print("送れなかった:", message, e, flush=True)

    def ws_loop(self):
        while True:
            self.ws = websocket.WebSocketApp(
                URL, on_open=lambda ws: self.q.put(("ws_open", None)),
                on_message=lambda ws, text: self.q.put(("ws", text)))
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            self.q.put(("ws_closed", None))
            time.sleep(2)

    def load_pedalboard(self, pb):
        reset = self.reset_next or pb.get("name", "") != self.name
        self.reset_next = False
        self.name = pb.get("name", "")
        if self.pending_vol is None:
            self.out_vol = float(pb.get("output_volume_db", 0.0))
        self.items, self.switch, self.tuner_id = {}, {}, None

        def walk(xs):
            for it in xs or []:
                iid = it.get("instanceId")
                self.items[iid] = {"uri": it.get("uri", ""), "name": it.get("pluginName", ""),
                                   "enabled": bool(it.get("isEnabled")),
                                   "values": {c["key"]: c["value"] for c in it.get("controlValues", [])},
                                   "model": model_short(it.get("pathProperties") or {})}
                for b in it.get("midiBindings") or []:
                    if b.get("symbol") == "__bypass" and b.get("bindingType") == 2:
                        cc = b.get("control")
                        if cc in SWITCH_CCS:
                            self.switch[SWITCH_CCS.index(cc)] = iid
                        elif cc == TUNER_CC:
                            self.tuner_id = iid
                walk(it.get("topChain"))
                walk(it.get("bottomChain"))

        walk(pb.get("items"))
        if reset:
            self.base = {(i, s): v for i, it in self.items.items() for s, v in it["values"].items()}
            self.base_vol = self.out_vol
        self.send_leds()

    def on_ws(self, text):
        """PiPedal からの 1 通を処理する。画面を描き直す必要があれば True"""
        try:
            frame = json.loads(text)
        except ValueError:
            return False
        head = frame[0] if frame else {}
        body = frame[1] if len(frame) > 1 else None
        msg = head.get("message")
        if msg in ("onVuUpdate", "onMonitorPortOutput") and head.get("replyTo") is not None:
            # 返事をしないと PiPedal は次を送ってこない(Web 画面と同じやり方)
            try:
                self.ws.send(json.dumps([{"reply": head["replyTo"], "message": msg}, True]))
            except Exception:  # noqa: BLE001
                pass
        if head.get("reply") == self.hello_id and isinstance(body, int):
            self.client_id = body
            return False
        if head.get("reply") == self.tuner_req and self.tuner_req is not None:
            self.tuner_handle, self.tuner_req = body, None
            return False
        if msg == "onVuUpdate" and isinstance(body, dict):
            peak = max(body.get("outputMaxValueL", 0), body.get("outputMaxValueR", 0))
            if peak >= 0.999:
                self.clip_until = time.monotonic() + CLIP_HOLD
            db = max(METER_FLOOR, 20 * math.log10(peak)) if peak > 0 else METER_FLOOR
            q = round(db / 2) * 2
            changed = q != self.meter_db
            self.meter_db = q
            return "slow" if changed and self.mode == "home" else False
        if msg == "onMonitorPortOutput" and isinstance(body, dict):
            if body.get("subscriptionHandle") != self.tuner_handle:
                return False
            v = body.get("value", -1)
            note = round(v * 50) / 50 if v > 0 else None   # 2 セントきざみ
            changed = note != self.tuner_note
            self.tuner_note = note
            return changed
        if msg in ("currentPedalboard", "onPedalboardChanged") and isinstance(body, dict):
            self.load_pedalboard(body.get("pedalboard", body))
        elif msg == "onControlChanged" and isinstance(body, dict):
            if body.get("clientId") == self.client_id:
                return                              # 自分が送った値の折り返し
            it = self.items.get(body.get("instanceId"))
            if it is not None and (body.get("instanceId"), body.get("symbol")) not in self.pending:
                it["values"][body.get("symbol")] = body.get("value")
        elif msg == "onItemEnabledChanged" and isinstance(body, dict):
            it = self.items.get(body.get("instanceId"))
            if it is not None:
                it["enabled"] = bool(body.get("enabled"))
                self.send_leds()
        elif msg == "onOutputVolumeChanged" and isinstance(body, (int, float)):
            if self.pending_vol is None:
                self.out_vol = float(body)
        elif msg and "PatchProperty" in msg:              # 11/1: NAM のモデルが変わった(スマホのアプリ)→ 札の名前を読み直す
            self.request("currentPedalboard")
        elif msg in ("onPresetChanged", "onSelectedSnapshotChanged", "onPresetsChanged"):
            if msg != "onPresetChanged" or body is False:   # false = 読み込んだ・保存した直後
                self.reset_next = True
            if msg == "onPresetChanged" and body is False and self.mode == "saving":
                threading.Thread(target=self.persist, daemon=True).start()
            self.request("currentPedalboard")
        return True

    def save(self, now):
        """今のプリセットに上書き。PiPedal が書き終わったら(onPresetChanged false)persist へ"""
        if not self.connected or self.client_id is None:
            self.finish_save(False, now)
            return
        self.mode, self.save_started = "saving", now
        self.send("saveCurrentPreset", self.client_id)

    def persist(self):
        try:
            r = subprocess.run(["sudo", "-n", PERSIST], capture_output=True, text=True, timeout=30)
            print("保存:", r.returncode, r.stdout.strip(), r.stderr.strip(), flush=True)
            self.q.put(("saved", r.returncode == 0))
        except Exception as e:  # noqa: BLE001
            print("保存できなかった:", e, flush=True)
            self.q.put(("saved", False))

    def finish_save(self, ok, now):
        self.mode = "home"
        self.result = (ok, now + RESULT_SEC)

    def tuner_on(self):
        return self.tuner_id in self.items and self.items[self.tuner_id]["enabled"]

    def update_tuner_sub(self):
        """チューナーが ON の間だけ音の高さを受け取る"""
        if not self.connected:
            return
        if self.tuner_on() and self.tuner_handle is None and self.tuner_req is None:
            self.tuner_req = self.request("monitorPort", {"instanceId": self.tuner_id, "key": "FREQ",
                                                          "updateRate": 1 / 30})
        elif not self.tuner_on() and self.tuner_handle is not None:
            self.send("unmonitorPort", self.tuner_handle)
            self.tuner_handle, self.tuner_note = None, None

    # ---- Pico ----
    def midi_check(self):
        names = [n for n in mido.get_input_names() if PICO_NAME in n]
        if self.midi_in is not None and self.midi_in.name not in names:
            print("Pico が外れた", flush=True)
            self.midi_in.close()
            self.midi_in = None
            if self.midi_out is not None:
                self.midi_out.close()
                self.midi_out = None
        if self.midi_in is None and names:
            self.midi_in = mido.open_input(names[0], callback=lambda m: self.q.put(("midi", m)))
            outs = [n for n in mido.get_output_names() if PICO_NAME in n]
            self.midi_out = mido.open_output(outs[0]) if outs else None
            print("Pico につないだ:", names[0], flush=True)
            self.send_leds()

    def send_leds(self):
        """CC80〜83 の今の状態を Pico へ(LED と、リレーの「ラズパイが生きている」合図)"""
        if self.midi_out is None or not self.connected:
            return
        states = {SWITCH_CCS[k]: self.items[i]["enabled"] for k, i in self.switch.items() if i in self.items}
        if self.tuner_id in self.items:
            states[TUNER_CC] = self.items[self.tuner_id]["enabled"]
        try:
            for cc, on in sorted(states.items()):
                self.midi_out.send(mido.Message("control_change", control=cc, value=127 if on else 0))
        except Exception as e:  # noqa: BLE001
            print("Pico へ送れなかった:", e, flush=True)
        self.last_led = time.monotonic()

    def on_midi(self, m):
        if m.type != "control_change":
            return
        now = time.monotonic()
        cc, v = m.control, m.value
        if cc in SWITCH_CCS:
            self.sel = SWITCH_CCS.index(cc)              # 最後に踏んだスイッチを選ぶ
        elif cc == BYPASS_CC:
            self.bypass = v >= 64
        elif cc == ENC_CC:
            self.turn(1 if v == 65 else -1 if v == 63 else v - 64, now)
        elif cc == PUSH_CC:
            self.touch(now)
            if v == 127:
                if self.mode == "home":
                    self.push_at = now                  # 離したときに編集へ(長押しなら保存の確認)
                elif self.mode == "confirm":
                    self.save(now)
                elif self.mode == "edit":
                    self.mode = "home"
            elif self.push_at is not None:
                self.push_at = None
                if self.mode == "home" and self.switch.get(self.sel) in self.items:
                    self.mode, self.param = "edit", 0
        elif cc in (LEFT_CC, RIGHT_CC) and v == 127:
            self.touch(now)
            d = 1 if cc == RIGHT_CC else -1
            if self.mode == "confirm":
                self.mode = "home"                      # やめる
            elif self.mode == "home":
                self.sel = (self.sel + d) % 3
            else:
                n = len(self.edit_params())
                if n:
                    self.param = (self.param + d) % n

    def touch(self, now):
        self.last_touch = now

    def edit_item(self):
        iid = self.switch.get(self.sel)
        return iid, self.items.get(iid)

    def edit_params(self):
        """編集画面で回すつまみの一覧 [(instanceId, symbol, 表示名, 単位, 1 クリック, 最小, 最大)]。
        アンプのあとに、同じプリセットの EQ も続ける(音作りはアンプと EQ でするため)"""
        iid, it = self.edit_item()
        if not it:
            return []
        out = [(iid, *p) for p in PARAMS.get(it["uri"], ("", []))[1]]
        if it["uri"] == NAM_URI:
            for eid, e in self.items.items():
                if e["uri"] == EQ_URI:
                    out += [(eid, *p) for p in PARAMS[EQ_URI][1]]
        return out

    def turn(self, clicks, now):
        fast = now - self.last_click < FAST_CLICK
        self.last_click = now
        idle = now - self.last_touch > WAKE_SEC
        self.touch(now)
        if self.mode == "home":
            self.overlay_until = now + OVERLAY_SEC
            self.push_at = None                         # 押しながら回したら長押しにしない
            if idle:
                return                                  # ぶつけた 1 クリックで音量が変わらないように
            v = self.out_vol + clicks * VOL_STEP
            v = max(VOL_MIN, min(self.base_vol + VOL_HEADROOM, v))
            self.pending_vol = self.out_vol = v
        elif self.mode == "edit":
            params = self.edit_params()
            if not params:
                return
            iid, sym, _, _, step, lo, hi = params[self.param % len(params)]
            it = self.items[iid]
            cur = it["values"].get(sym, lo)
            v = max(lo, min(hi, cur + clicks * step * (4 if fast else 1)))
            v = round(v / step) * step if step >= 1 else round(v, 3)
            it["values"][sym] = v
            self.pending[(iid, sym)] = v
        self.last_turn = now

    def flush_edits(self, now):
        """回している間は previewControl を間引いて送り、止まったら setControl を 1 回"""
        if not self.pending and self.pending_vol is None:
            return
        done = now - self.last_turn > COMMIT_AFTER
        if not done and now - self.last_preview < PREVIEW_EVERY:
            return
        self.last_preview = now
        kind = "set" if done else "preview"
        for (iid, sym), v in self.pending.items():
            self.send(kind + "Control", {"clientId": self.client_id, "instanceId": iid, "symbol": sym, "value": v})
        if self.pending_vol is not None:
            self.send(kind + "OutputVolume", self.pending_vol)
        if done:
            self.pending.clear()
            self.pending_vol = None

    def edited(self):
        if abs(self.out_vol - self.base_vol) > 1e-6:
            return True
        return any(isinstance(v, (int, float)) and abs(v - self.base.get((i, s), v)) > 1e-6
                   for i, it in self.items.items() for s, v in it["values"].items())

    # ---- 絵 ----
    def draw(self, now):
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        if not self.connected:
            d.text((24, 130), "PiPedal を待っています", font=font(36), fill=GREY)
        elif self.bypass:
            d.rectangle([0, 0, W, H], fill=(200, 0, 0))
            d.text((W // 2, H // 2), "BYPASS", font=font(96, False), fill="white", anchor="mm")
        elif self.tuner_on():
            self.draw_tuner(d)
        elif self.mode == "edit":
            self.draw_edit(d)
        elif self.mode in ("confirm", "saving"):
            self.draw_save(d)
        else:
            self.draw_home(d, now)
        return img

    def draw_save(self, d):
        name = self.name or "(名前なし)"
        d.text((W // 2, 50), name, font=fit(d, name, 40, W - 20), fill="white", anchor="mm")
        if self.mode == "saving":
            d.text((W // 2, 170), "保存しています…", font=font(48), fill=ORANGE, anchor="mm")
            return
        d.text((W // 2, 140), "上書き保存する?", font=font(52), fill=ORANGE, anchor="mm")
        d.text((W // 2, 230), "押す = 保存", font=font(34), fill="white", anchor="mm")
        d.text((W // 2, 280), "◀ ▶ = やめる", font=font(30), fill=GREY, anchor="mm")

    def draw_tuner(self, d):
        """音名を大きく、ずれ(セント)を横の目盛りで。±5 セント以内は緑"""
        d.text((W // 2, 26), "TUNER", font=font(30, False), fill=GREY, anchor="mm")
        if self.tuner_note is None:
            d.text((W // 2, 150), "—", font=font(120, False), fill=GREY, anchor="mm")
            return
        n = round(self.tuner_note)
        cents = (self.tuner_note - n) * 100
        ok = abs(cents) <= 5
        color = (0, 220, 90) if ok else (255, 170, 0)
        d.text((W // 2, 140), f"{NOTE_NAMES[n % 12]}{n // 12 - 1}", font=font(130, False), fill=color, anchor="mm")
        d.line([20, 260, W - 20, 260], fill=GREY, width=2)
        for c in (-50, -25, 0, 25, 50):
            x = W // 2 + int(c / 50 * (W // 2 - 20))
            d.line([x, 245 if c else 230, x, 275 if c else 290], fill="white" if c == 0 else GREY, width=3 if c == 0 else 2)
        x = W // 2 + int(max(-50, min(50, cents)) / 50 * (W // 2 - 20))
        d.rectangle([x - 8, 236, x + 8, 284], fill=color)
        d.text((W // 2, 305), f"{cents:+.0f} cent", font=font(22, False), fill=GREY, anchor="mm")

    def draw_meter(self, d, now):
        """VOL の右に出力の大きさ。0 dBFS に届いたら 1 秒赤"""
        x0, x1, y0, y1 = 250, W - 8, 76, 100
        d.rectangle([x0, y0, x1, y1], fill=DARK, outline=GREY)
        frac = (self.meter_db - METER_FLOOR) / -METER_FLOOR
        color = (0, 200, 80) if self.meter_db < -12 else (255, 190, 0) if self.meter_db < -3 else (255, 90, 0)
        if frac > 0:
            d.rectangle([x0 + 1, y0 + 1, x0 + 1 + int((x1 - x0 - 2) * frac), y1 - 1], fill=color)
        if now < self.clip_until:
            d.rectangle([x1 - 40, y0, x1, y1], fill=(230, 0, 0))
            d.text((x1 - 20, (y0 + y1) // 2), "CLIP", font=font(14, False), fill="white", anchor="mm")

    def draw_home(self, d, now):
        name = self.name or "(名前なし)"
        d.text((8, 4), name, font=fit(d, name, 48, W - 130), fill="white")
        if self.edited():
            d.text((W - 8, 10), "● 編集", font=font(26), fill=ORANGE, anchor="ra")
        d.text((8, 66), f"VOL {self.out_vol:+.1f} dB", font=font(34, False), fill=GREY)
        self.draw_meter(d, now)
        for k in range(3):
            x = 4 + k * 160
            it = self.items.get(self.switch.get(k))
            color = RING[k]
            if it and it["enabled"]:
                d.rectangle([x, 116, x + 151, 314], fill=color)
                fg = "black"
            else:
                d.rectangle([x, 116, x + 151, 314], fill=DARK, outline=color, width=3)
                fg = GREY
            if k == self.sel:
                d.rectangle([x - 3, 113, x + 154, 317], outline="white", width=3)
            if not it:
                d.text((x + 76, 215), "—", font=font(44, False), fill=GREY, anchor="mm")
                continue
            short, params = PARAMS.get(it["uri"], (it["name"].replace("TooB ", "")[:8], []))
            if it.get("model"):   # 11/1: NAM は入れた音の名前(スマホのアプリで TONE3000 から入れたもの)を札に出す
                short = it["model"]
            d.text((x + 76, 170), short, font=fit(d, short, 44, 140, False), fill=fg, anchor="mm")
            if params:
                want = TILE_PARAM.get(short)
                sym, _, unit, *_ = next((p for p in params if p[0] == want), params[0])
                text = fmt(it["values"].get(sym, 0), unit)
                d.text((x + 76, 250), text, font=fit(d, text, 30, 140, False), fill=fg, anchor="mm")
        if now < self.overlay_until:
            d.rectangle([60, 70, W - 60, 250], fill=(20, 20, 20), outline="white", width=3)
            d.text((W // 2, 115), "VOL", font=font(40, False), fill=GREY, anchor="mm")
            d.text((W // 2, 190), f"{self.out_vol:+.1f} dB", font=font(72, False), fill="white", anchor="mm")
        if self.result:
            ok = self.result[0]
            d.rectangle([40, 100, W - 40, 220], fill=(0, 120, 50) if ok else (180, 0, 0), outline="white", width=3)
            d.text((W // 2, 160), "保存しました" if ok else "保存できませんでした", font=font(44), fill="white", anchor="mm")

    def draw_edit(self, d):
        _, sw_item = self.edit_item()
        params = self.edit_params()
        color = RING[self.sel]
        d.rectangle([0, 0, W, 56], fill=color)
        if not params:
            short = sw_item["name"].replace("TooB ", "")[:12] if sw_item else "?"
            d.text((10, 28), short, font=fit(d, short, 38, W - 120, False), fill="black", anchor="lm")
            d.text((24, 120), "このエフェクトは\nスマホで調整してください", font=font(32), fill=GREY)
            return
        i = self.param % len(params)
        iid, sym, label, unit, step, lo, hi = params[i]
        it = self.items[iid]
        short = PARAMS[it["uri"]][0]
        d.text((10, 28), short, font=fit(d, short, 38, W - 120, False), fill="black", anchor="lm")
        d.text((W - 10, 28), f"{i + 1}/{len(params)}", font=font(30, False), fill="black", anchor="rm")
        d.text((W // 2, 92), label, font=font(44), fill="white", anchor="mm")
        v = it["values"].get(sym, lo)
        text = fmt(v, unit)
        d.text((W // 2, 180), text, font=fit(d, text, 96, W - 20, False), fill="white", anchor="mm")
        frac = min(1, max(0, (v - lo) / (hi - lo)))
        d.rectangle([20, 240, W - 20, 268], fill=DARK, outline=GREY)
        d.rectangle([20, 240, 20 + int((W - 40) * frac), 268], fill=color)
        b = self.base.get((iid, sym))
        if isinstance(b, (int, float)):
            bx = 20 + int((W - 40) * min(1, max(0, (b - lo) / (hi - lo))))
            d.line([bx, 234, bx, 274], fill="white", width=3)   # 読み込んだときの値
        prev_l, next_l = params[(i - 1) % len(params)][2], params[(i + 1) % len(params)][2]
        d.text((10, 300), f"◀ {prev_l}", font=font(24), fill=GREY, anchor="lm")
        d.text((W - 10, 300), f"{next_l} ▶", font=font(24), fill=GREY, anchor="rm")

    # ---- 本体 ----
    def run(self):
        lcd = Lcd()
        lcd.init()
        lcd.show(self.draw(time.monotonic()))
        threading.Thread(target=self.ws_loop, daemon=True).start()
        last_midi_check = last_draw = 0.0
        last_reinit = time.monotonic()
        dirty, slow_dirty, overlay_shown, clip_shown = True, False, False, False
        while True:
            try:
                kind, data = self.q.get(timeout=0.02)
                if kind == "ws":
                    r = self.on_ws(data)
                    if r == "slow":
                        slow_dirty = True
                    elif r:
                        dirty = True
                else:
                    dirty = True
                if kind == "ws_open":
                    self.connected = True
                    self.next_id = 1
                    self.tuner_req = self.tuner_handle = None
                    self.hello_id = self.request("hello")
                    self.reset_next = True
                    self.request("currentPedalboard")
                    self.request("addVuSubscription", OUT_ID)
                    print("PiPedal につないだ", flush=True)
                elif kind == "ws_closed":
                    if self.connected:
                        print("PiPedal との接続が切れた", flush=True)
                    self.connected = False
                elif kind == "midi":
                    self.on_midi(data)
                elif kind == "saved":
                    self.finish_save(data, time.monotonic())
            except queue.Empty:
                pass
            now = time.monotonic()
            self.flush_edits(now)
            if self.mode in ("edit", "confirm") and now - self.last_touch > EDIT_IDLE_SEC:
                self.mode = "home"
                dirty = True
            if self.push_at is not None and now - self.push_at >= SAVE_HOLD:
                self.push_at = None                     # 離したときに編集へ行かないように
                self.mode = "confirm" if self.mode == "home" else self.mode
                dirty = True
            if self.mode == "saving" and now - self.save_started > SAVE_TIMEOUT:
                self.finish_save(False, now)
                dirty = True
            if self.result and now > self.result[1]:
                self.result = None
                dirty = True
            if overlay_shown != (now < self.overlay_until):
                overlay_shown = not overlay_shown
                dirty = True
            if clip_shown != (now < self.clip_until):
                clip_shown = not clip_shown
                dirty = True
            self.update_tuner_sub()
            if now - last_midi_check > 2:
                last_midi_check = now
                try:
                    self.midi_check()
                except Exception as e:  # noqa: BLE001  常駐なので止まらない
                    print("MIDI を開けない:", e, flush=True)
            if now - self.last_led > RESYNC_SEC:
                self.send_leds()
            if now - last_reinit > 300 and now - self.last_touch > 30:
                last_reinit = now                       # 読み返せない画面なので、ときどき初期化して全部描き直す
                lcd.init()
                dirty = True
            # 何か変わったときだけ描く(待っている間の CPU を使わない)。メーターだけの変化は 10 回/秒まで
            if (dirty and now - last_draw > 1 / 30) or (slow_dirty and now - last_draw > 0.1):
                last_draw = now
                dirty = slow_dirty = False
                lcd.show(self.draw(now))


if __name__ == "__main__":
    Ui().run()
