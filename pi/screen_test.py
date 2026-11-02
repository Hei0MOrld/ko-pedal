# -*- coding: utf-8 -*-
"""3.5 インチ画面(ILI9488、SPI)のテスト表示(2026-10-20、手順 E-1)。

配線(step_e_screen.html): CS=CE0(GPIO8)、D/C=GPIO24、RESET=GPIO25、SDI=GPIO10、SCK=GPIO11、SDO はつながない。
ILI9488 の SPI は 1 ピクセル 3 バイト(RGB666、各バイトの上 6 ビット)しか受け付けない。
横向き 480×320 に色の帯と文字を描く。

    python3 screen_test.py
"""
import time

import gpiod
import spidev
from gpiod.line import Direction, Value
from PIL import Image, ImageDraw, ImageFont

DC, RST = 24, 25
W, H = 480, 320
SPI_HZ = 16_000_000

req = gpiod.request_lines("/dev/gpiochip0", consumer="lcd",
                          config={(DC, RST): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)})
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = SPI_HZ
spi.mode = 0


def cmd(c, data=b""):
    req.set_value(DC, Value.INACTIVE)
    spi.writebytes([c])
    if data:
        req.set_value(DC, Value.ACTIVE)
        spi.writebytes2(bytes(data))


def init():
    req.set_value(RST, Value.INACTIVE)
    time.sleep(0.02)
    req.set_value(RST, Value.ACTIVE)
    time.sleep(0.15)
    cmd(0xC0, [0x17, 0x15])          # 電源 1
    cmd(0xC1, [0x41])                # 電源 2
    cmd(0xC5, [0x00, 0x12, 0x80])    # VCOM
    cmd(0x36, [0x28])                # 横向き(MV)+ BGR
    cmd(0x3A, [0x66])                # 18 ビット色(SPI はこれだけ)
    cmd(0xB0, [0x00])
    cmd(0xB1, [0xA0])                # フレームレート
    cmd(0xB4, [0x02])
    cmd(0xB6, [0x02, 0x02, 0x3B])
    cmd(0xE9, [0x00])
    cmd(0xF7, [0xA9, 0x51, 0x2C, 0x82])
    cmd(0x11)                        # スリープ解除
    time.sleep(0.12)
    cmd(0x29)                        # 表示 ON


def show(img):
    cmd(0x2A, [0, 0, (W - 1) >> 8, (W - 1) & 0xFF])
    cmd(0x2B, [0, 0, (H - 1) >> 8, (H - 1) & 0xFF])
    cmd(0x2C, img.convert("RGB").tobytes())


def test_image():
    img = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(img)
    colors = ["red", "lime", "blue", "yellow", "cyan", "magenta", "white", "gray"]
    bw = W // len(colors)
    for i, c in enumerate(colors):
        d.rectangle([i * bw, 0, (i + 1) * bw - 1, 120], fill=c)
    big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    d.text((20, 150), "KO PEDAL", font=big, fill="white")
    d.text((20, 215), "ILI9488 480x320  SPI test", font=small, fill="lime")
    d.text((20, 250), time.strftime("%Y-%m-%d %H:%M:%S"), font=small, fill="yellow")
    d.rectangle([0, 0, W - 1, H - 1], outline="white", width=2)
    return img


if __name__ == "__main__":
    init()
    t = time.time()
    show(test_image())
    print(f"描いた: {time.time() - t:.2f} 秒")
