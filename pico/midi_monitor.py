"""Pico から届く MIDI を表示する (Windows 標準の winmm を使う。追加インストール不要)
使い方: python -P midi_monitor.py [秒数]  (既定 60 秒)
"""
import ctypes
import sys
import time
from ctypes import wintypes

winmm = ctypes.WinDLL("winmm")


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("dwSupport", wintypes.DWORD)]


MIM_DATA = 0x3C3
CALLBACK_FUNCTION = 0x30000
CB = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t,
                        ctypes.c_size_t, ctypes.c_size_t)


def on_midi(h, msg, inst, p1, p2):
    if msg != MIM_DATA:
        return
    st, d1, d2 = p1 & 0xFF, (p1 >> 8) & 0xFF, (p1 >> 16) & 0xFF
    kind = {0xB0: "CC", 0x90: "NoteOn", 0x80: "NoteOff", 0xC0: "PC"}.get(st & 0xF0, hex(st))
    print(f"{time.strftime('%H:%M:%S')}  ch{(st & 0x0F) + 1}  {kind}  {d1}  {d2}", flush=True)


callback = CB(on_midi)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    n = winmm.midiInGetNumDevs()
    names = []
    for i in range(n):
        caps = MIDIINCAPSW()
        winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
        names.append(caps.szPname)
    print("MIDI入力:", names)
    idx = next((i for i, s in enumerate(names) if "CircuitPython" in s or "Pico" in s), None)
    if idx is None:
        print("Pico が見つからない")
        return
    h = wintypes.HANDLE()
    r = winmm.midiInOpen(ctypes.byref(h), idx, callback, 0, CALLBACK_FUNCTION)
    if r:
        print("開けなかった (他のソフトが使用中かも)  code", r)
        return
    winmm.midiInStart(h)
    print(f"{names[idx]} を {secs:.0f} 秒聞きます。スイッチを押してください", flush=True)
    try:
        time.sleep(secs)
    finally:
        winmm.midiInStop(h)
        winmm.midiInClose(h)


main()
