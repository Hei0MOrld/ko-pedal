# 琥ペダル — ラズパイ 5 と Pico で作るベース用マルチエフェクター

自分のベース用に、足元のマルチエフェクターを一から作っている記録です。
回路・配線・箱の中の配置・ラズパイと Pico のソフト・スマホから操作するサイトまで、全部自作しています。

> **状態: 製作中**(2026-11)。ブレッドボードで音が出て、足元のスイッチ・LED・つまみ・画面まで動いています。
> 次は音の部分をユニバーサル基板に移して([手順 F](docs/step_f_board.html))、箱に入れます。

## しくみ

```
ベース ─ IN ─┬─(リレー: BYPASS)──────────────────────┬─ OUT ─ アンプ
             └─ UR12(HI-Z) ─ USB ─ ラズパイ 5 ─ UR12 ─┘
                                    │  PiPedal + NAM(アンプのモデル)
                                    │  3.5 インチの画面(SPI)
                                    └─ USB-MIDI ─ Pico ── フットスイッチ 5 個 / LED リング / つまみ
スマホ ─(家の Wi-Fi / Tailscale)─ 自作サイト ─ PiPedal の websocket
```

- **音**: ラズパイ 5 で [PiPedal](https://github.com/rerdavies/pipedal) を動かし、NAM(Neural Amp Modeler)のモデルでアンプの音を出す。音の出入りは Steinberg UR12。
- **足元**: Raspberry Pi Pico(CircuitPython)が USB-MIDI の機器になって、スイッチ・つまみを CC で送る。プリセットの LED は WS2812B のリング。→ [`pico/code.py`](pico/code.py)
- **BYPASS はラズパイを通さない**: Pico が直接リレー(GP9 → 2SC1815 → TQ2-5V)を動かすので、ラズパイが固まっても素の音に戻せる。
- **画面**: 3.5 インチの SPI 液晶に、今のプリセットと、足元のスイッチに割り当てたエフェクト(NAM ならモデル名)を出す。→ [`pi/pedal_ui.py`](pi/pedal_ui.py)
- **SD カードを守る**: ラズパイは overlayroot で読み取り専用にして、電源を急に抜いても壊れないようにした。プリセットを保存したときだけ、変わったファイルを SD 本体へ書く。→ [`pi/pedal-persist`](pi/pedal-persist)
- **スマホから音作り**: PiPedal の画面は英語だけで、スマホでは使いにくかった。なので日本語のサイトを作って、裏で PiPedal の websocket を叩いている。エフェクトの ON/OFF・つまみ・並べ替え・プリセットの保存・元に戻す、TONE3000 のモデルを直接入れる、AI に「もっと太く」のように頼む、ができる。→ [`app/`](app/)
- **自作エフェクト**: Faust で書いたオートワウ・歪み・ディレイ・トレモロ。→ [`faust/`](faust/)

## 手順と図

ブラウザで開くページです(ダウンロードして開けば動きます)。

| ページ | 中身 |
|---|---|
| [docs/pedal_inside.html](docs/pedal_inside.html) | 箱の中の配置、配線表(1 本ずつ) |
| [docs/step_e_knob.html](docs/step_e_knob.html) | Pico のピン図と、つまみ・ボタンの配線 |
| [docs/step_e_screen.html](docs/step_e_screen.html) | 画面とラズパイの配線 |
| [docs/step_d_di.html](docs/step_d_di.html) | 受け身の DI 出力(XLR) |
| [docs/step_f_board.html](docs/step_f_board.html) | 音の基板の穴の配置図、GND の分け方 |
| [docs/pedal_3d.html](docs/pedal_3d.html) / [pedal_final.html](docs/pedal_final.html) | 箱の 3D・完成図 |
| [docs/button_sim.html](docs/button_sim.html) | 足元の操作のシミュレーター |

日々の記録は [docs/BUILD_STEPS.md](docs/BUILD_STEPS.md)、仕様は [docs/SPEC.md](docs/SPEC.md)、部品は [docs/PARTS_FINAL.md](docs/PARTS_FINAL.md)。

## つまずいたこと: ノイズは GND の「輪」だった

ブレッドボードの段階で、何も弾いていないのに -50 dBFS のノイズが乗っていた。
同じベース・ケーブル・UR12 をバッテリーで動く Mac につなぐと -82 dBFS で静か。
なので、原因はラズパイ側の GND の揺れだと絞り込んだ。

最後に見つかった原因は配線だった。IN ジャックのスリーブと HI-Z ケーブルの網線が、Pico・LED と同じ GND の列に挿さっていた。
そのせいで「ラズパイ → USB → UR12 → 網線 → GND の列 → Pico → USB → ラズパイ」という輪ができ、そこに流れる揺れがベースの小さな信号に混ざっていた。
入口の GND だけを別の列に分けたら **-70 dBFS(21 dB 改善)**。
完成版の基板では、入口の GND を「HI-Z の網線 1 点だけ」の島にしている([手順 F](docs/step_f_board.html))。

| つなぐもの | GND の行き先 |
|---|---|
| ボタン・LED・つまみ・リング LED・リレーのトランジスター | Pico のどの GND でも(中で全部つながっている) |
| IN ジャックのスリーブ + HI-Z の網線 | 島にして、他とつながない |
| OUT ジャックのスリーブ + LINE OUT の網線 | 普通の GND 側 |

## 使い方(自分の環境の場合)

- Pico: CircuitPython を入れて `pico/code.py` を `CIRCUITPY` に置く。
- ラズパイ: PiPedal を入れて、`pi/pedal_ui.py` を `pi/pedal-ui.service` で起動。ホスト名は `kopedal`。
- スマホのサイト: `app/` を PC で `python server.py`(FastAPI、127.0.0.1:8740)。外から見るときは `tailscale serve`。
  TONE3000 を使うなら、自分の API キーを `app/t3k_config.json` に置く(このリポジトリには入れていない)。

## 作り方について

設計とコードは、AI(Claude)と相談しながら作っています。はんだ付け・組み立て・測定は自分の手で、ノイズの原因(配線)も自分の見立てで見つけました。

---

## English summary

A DIY bass multi-effects pedal: Raspberry Pi 5 running PiPedal + Neural Amp Modeler, a Raspberry Pi Pico as a USB-MIDI footswitch controller (5 switches, WS2812B rings, rotary encoder), a true-bypass relay driven by the Pico (it still works if the Pi hangs), a 3.5" SPI status screen, a read-only SD root with a small script that persists only changed presets, and a Japanese phone web app that drives PiPedal over its websocket. Build notes and wiring pages are in Japanese under `docs/`. Work in progress.

License: MIT
