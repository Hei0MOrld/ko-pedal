# ステップ2 その4 (2026-10-09): 本番と同じ5ボタン(左から TUNER・1・2・3・BYPASS、SPEC「ボタンの動き」)
#   1 = GP2 (CC80, 緑) / 2 = GP3 (CC81, 青) / 3 = GP4 (CC82, 赤)  … WS2812B 3個、信号 = GP16
#   TUNER = GP5 (CC83。PiPedal の選択肢に 84〜90 が無いため、10/9)、LED = GP7(普通の赤 LED + 抵抗)/ BYPASS = GP6 (CC85)、LED = GP8(普通の白 LED + 抵抗)
# - 1/2/3: 短く押して離す → ON/OFF を切り替えて CC80〜82 を送る(127 = ON、0 = OFF)
#   長押しと区別するため、切り替えは「離した瞬間」(SPEC: 本体の 1/2/3 だけ)
#   LONG_SEC 押し続ける → スナップショット 1〜3 を呼ぶ CC90〜92(PiPedal の System MIDI Bindings、10/9 設定)
#   LED が一瞬白く光る。ON/OFF は変えない
# - TUNER / BYPASS: 踏んだ瞬間に切り替える(遅れなし)。TUNER 中はどのスイッチを踏んでも TUNER が解除される
#   BYPASS は Pico が直接リレー(GP9 → 2SC1815 → TQ2-5V)を動かす(ステップ3、10/10)。Pi を経由しないので Pi が固まっても効く
# - リレーに電気を流す = エフェクトを通す / 流さない = 素通り(電源が切れても素通り)
#   エフェクトを通すのは「BYPASS が OFF」かつ「Pi が生きている」ときだけ
#   Pi が生きている = pedal-ledsync から ALIVE_SEC 以内に MIDI が届いた(ledsync は 5 秒ごとに送り直す)
#   起動直後(Pi がまだ起きていない)と Pi が固まったときは素通りになり、白 LED がゆっくり点滅する
# - Pi の pedal-ledsync が PiPedal の今の状態を CC80〜83 で送ってくる → それに合わせて LED と状態を直す
#   (Pico を挿し直した直後や、スナップショットでまとめて変わったときにずれないように)
# v6 (2026-10-13, Mac で 10/12 に決めたこと):
# - TUNER / BYPASS は手持ちの 3PDT(押すと切り替わったまま = ラッチ)。押した・離したではなく「スイッチの向きが変わった」で切り替える。
#   起動したときの向きを基準(OFF)にする → どちら向きで電源を入れても素通り・TUNER OFF から始まる
# - 回して押せるつまみ(ALPS RE111F-41B3)+ 左右ボタン 2 個 = 本体で音作りを編集するため(VOLUME のポットの代わり)。
#   今は MIDI を送るだけ。受け取って画面を動かすのは Pi 側(PiPedal の websocket を使う予定)
#   つまみ: CC102 を相対値で(1 クリック右 = 65、左 = 63)、つまみを押す = CC103、左ボタン = CC104、右ボタン = CC105(押すと 127、離すと 0)
#   ピン: つまみ A = GP10 / B = GP11 / 押す = GP12、左 = GP13、右 = GP14(どれも GND に落とす、内部プルアップ)
# 1 つ前(タクトスイッチ 5 個の仮組み)は code_v5_tact.py
import time
import board
import digitalio
import neopixel_write
import rotaryio
import usb_midi

midi_in = usb_midi.ports[0]
midi_out = usb_midi.ports[1]

BRIGHT = 0.04  # 明るさ (0〜1)。10/20 KO「めっちゃ明るい」で 0.08→0.04。リング 3 個 = 48 個を USB の電気で光らせるので控えめ(1 個ずつの頃は 0.2)
LEDS_PER = 16  # v7 (10/19 手順 C): LED リング A-7979 = 1 個に 16 個。1 個ずつの頃(v6)は code_v6_single_led.py
LONG_SEC = 0.6   # SPEC の初期値。スマホから 0.5〜1.0 秒で変えられるようにするのは後で
DEBOUNCE = 0.025  # SPEC: チャタリング除けは 20〜30ms
SNAPSHOT_CC = 90
ALIVE_SEC = 12   # ledsync の送り直し 5 秒 × 2 + 余裕
LATCHING = {3, 4}   # TUNER / BYPASS = 3PDT(向きが変わるたびに切り替え)
ENC_CC, ENC_PUSH_CC, LEFT_CC, RIGHT_CC = 102, 103, 104, 105
# (ピン, CC番号, 色 (R, G, B) または普通の LED のピン, 長押しあり)
SWITCHES = [
    (board.GP2, 80, (0, 255, 0), True),       # 1
    (board.GP3, 81, (0, 80, 255), True),      # 2
    (board.GP4, 82, (255, 0, 0), True),       # 3
    (board.GP5, 83, board.GP7, False),        # TUNER(赤 LED)
    (board.GP6, 85, board.GP8, False),        # BYPASS(白 LED)
]
TUNER, BYPASS = 3, 4

relay = digitalio.DigitalInOut(board.GP9)
relay.direction = digitalio.Direction.OUTPUT
relay.value = False  # 素通りから始める

led_pin = digitalio.DigitalInOut(board.GP16)
led_pin.direction = digitalio.Direction.OUTPUT
onboard = digitalio.DigitalInOut(board.LED)
onboard.direction = digitalio.Direction.OUTPUT

pins, plain_leds = [], {}
for i, (p, _, led, _) in enumerate(SWITCHES):
    sw = digitalio.DigitalInOut(p)
    sw.direction = digitalio.Direction.INPUT
    sw.pull = digitalio.Pull.UP
    pins.append(sw)
    if not isinstance(led, tuple):
        out = digitalio.DigitalInOut(led)
        out.direction = digitalio.Direction.OUTPUT
        plain_leds[i] = out

n = len(SWITCHES)
state = [False] * n
last = [sw.value for sw in pins]
pressed_at = [None] * n
long_sent = [False] * n
cc_index = {cc: i for i, (_, cc, _, _) in enumerate(SWITCHES)}


def show(flash=None):
    buf = bytearray()
    for i, (on, (_, _, color, _)) in enumerate(zip(state, SWITCHES)):
        if i in plain_leds:
            plain_leds[i].value = on
            continue
        if flash == i:
            buf += bytes([12, 12, 12]) * LEDS_PER
            continue
        r, g, b = color
        k = BRIGHT if on else 0
        buf += bytes([int(g * k), int(r * k), int(b * k)]) * LEDS_PER  # WS2812B は G,R,B の順
    neopixel_write.neopixel_write(led_pin, buf)


def send_cc(cc, value):
    midi_out.write(bytes([0xB0, cc, value]))


rx = b""
last_rx = None  # Pi から最後に MIDI が届いた時刻


def read_midi():
    """Pi から届いた CC80〜83 で状態を合わせる。押している最中のボタンは触らない。
    (CircuitPython の bytearray は del で先頭を削れない → bytes を切り出して持ち越す)"""
    global rx, last_rx
    data = midi_in.read(64)
    if not data:
        return
    last_rx = time.monotonic()
    buf = rx + bytes(data)
    k, changed = 0, False
    while len(buf) - k >= 3:
        if buf[k] & 0xF0 != 0xB0:
            k += 1
            continue
        cc, value = buf[k + 1], buf[k + 2]
        k += 3
        i = cc_index.get(cc)
        if i is not None and pressed_at[i] is None and state[i] != (value >= 64):
            state[i] = value >= 64
            changed = True
    rx = buf[k:]
    if changed:
        show()


enc = rotaryio.IncrementalEncoder(board.GP10, board.GP11)   # 1 クリック = 1(divisor の既定は 4)
enc_last = enc.position
buttons = []
for p, cc in ((board.GP12, ENC_PUSH_CC), (board.GP13, LEFT_CC), (board.GP14, RIGHT_CC)):
    b = digitalio.DigitalInOut(p)
    b.direction = digitalio.Direction.INPUT
    b.pull = digitalio.Pull.UP
    buttons.append([b, cc, b.value])

show()
print("ready")

def toggle(i):
    state[i] = not state[i]
    send_cc(SWITCHES[i][1], 127 if state[i] else 0)
    print(("1", "2", "3", "TUNER", "BYPASS")[i], "ON" if state[i] else "OFF")


while True:
    now_t = time.monotonic()
    for i, sw in enumerate(pins):
        now = sw.value
        if now != last[i]:
            time.sleep(DEBOUNCE)  # チャタリング除け
            now = sw.value
            if now != last[i]:
                last[i] = now
                has_long = SWITCHES[i][3]
                if i in LATCHING:                # 3PDT: 向きが変わった = 踏んだ
                    if state[TUNER] and i != TUNER:
                        toggle(TUNER)            # TUNER 中は BYPASS を踏んでも TUNER を抜けるだけ
                    else:
                        toggle(i)
                    show()
                elif not now:                    # 押した
                    if state[TUNER] and i != TUNER:
                        toggle(TUNER)            # TUNER 中は、どれを踏んでも TUNER を抜けるだけ
                        pressed_at[i] = None
                        long_sent[i] = True
                    elif has_long:
                        pressed_at[i] = now_t
                        long_sent[i] = False
                    else:
                        toggle(i)                # TUNER / BYPASS は踏んだ瞬間
                    show()
                else:                            # 離した
                    if has_long and pressed_at[i] is not None and not long_sent[i]:
                        toggle(i)
                    pressed_at[i] = None
                    show()
                onboard.value = not now
        if pressed_at[i] is not None and not long_sent[i] and now_t - pressed_at[i] >= LONG_SEC:
            long_sent[i] = True
            send_cc(SNAPSHOT_CC + i, 127)        # PiPedal は 127 に上がった瞬間で反応する
            send_cc(SNAPSHOT_CC + i, 0)
            print("長押し", i + 1, "→ スナップショット", i + 1)
            show(flash=i)
    pos = enc.position                           # つまみ
    if pos != enc_last:
        d = pos - enc_last
        enc_last = pos
        for _ in range(min(abs(d), 8)):
            send_cc(ENC_CC, 65 if d < 0 else 63)  # A-6331 は右回しで position が減る(10/20 実測)→ 右 = 65
    for b in buttons:                            # つまみを押す / 左 / 右
        v = b[0].value
        if v != b[2]:
            time.sleep(DEBOUNCE)
            if b[0].value == v:
                b[2] = v
                send_cc(b[1], 0 if v else 127)
    read_midi()
    alive = last_rx is not None and now_t - last_rx < ALIVE_SEC
    relay.value = alive and not state[BYPASS]
    # 白 LED: BYPASS 中は点灯、Pi 待ち(自動で素通り)はゆっくり点滅
    plain_leds[BYPASS].value = state[BYPASS] if alive else int(now_t * 2) % 2 == 0
    time.sleep(0.002)
