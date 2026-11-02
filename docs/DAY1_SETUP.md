# ラズパイが届いた日の手順書(2026-10-03 作成)

目標: ベース → UR12 → Pi 5(PiPedal)→ UR12 → ヘッドホン で、スマホから音を作って弾く(BUILD_STEPS のステップ1)。
上から順にやれば終わるように書いた。モニター・キーボード・micro HDMI は使わない。

---

## 届く前にやっておくこと

- [ ] **microSD カードリーダーを買う**(100円ショップか家電量販店。USB-A でも USB-C でも、PC に挿せる方)
- [ ] PC に **Raspberry Pi Imager** を入れる(https://www.raspberrypi.com/software/)
- [ ] **TONE3000 のアカウント**を作り、下の「入れる NAM」をダウンロードして PC の1つのフォルダにまとめる
- [ ] 家の Wi-Fi の名前(SSID)とパスワードを手元に用意する

## 1. SD カードに OS を書く(PC で、約10分)

> **注意(10/3 わかったこと)**: PiPedal が正式に対応しているのは **Bookworm** だけ(Trixie はまだ書かれていない)。SPEC の仮決め「Trixie」をやめて、**Bookworm の Lite** にする。

1. カードリーダーにセットの microSD を挿して PC につなぐ(中身は消える。セットの OS は使わない)
2. Raspberry Pi Imager を開く
   - デバイス: **Raspberry Pi 5**
   - OS: **Raspberry Pi OS (other) → Raspberry Pi OS (Legacy, 64-bit) Lite**(説明に「Bookworm」とあるもの)
   - ストレージ: その microSD
3. 「設定を編集する」(カスタマイズ)で次を入れる
   - ホスト名: `kopedal`
   - ユーザー名とパスワード(忘れないようにメモ)
   - Wi-Fi: 家の SSID とパスワード、国 = **JP**
   - タイムゾーン: Asia/Tokyo、キーボード: jp
   - サービス: **SSH を有効**(パスワード認証)
4. 書き込む → 終わったら取り出す

## 2. 組み立てて電源を入れる

1. **公式クーラー SC1148** を Pi に付ける(ケースに入れる前。保護シートをはがしてから)
2. microSD を挿す
3. **電源 WS-U05500X** を挿す(これは 5A の PD 電源なので、Pi が自動で 5A と認識する。`PSU_MAX_CURRENT` の設定は今は要らない。箱に入れて降圧回路から給電するときに必要)
4. 1〜2分待つ(初回は少し長い)

## 3. PC からつなぐ(PowerShell)

```powershell
ssh <ユーザー名>@kopedal.local
```

- 初回は「yes」と打つ → パスワード
- `kopedal.local` が見つからないとき: ルーターの管理画面で Pi の IP を見て `ssh <ユーザー名>@<IP>`

## 4. 最新にする(約5〜10分)

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

1分待って、もう一度 `ssh` でつなぐ。

## 5. PiPedal を入れる(約5分)

> 当日、https://rerdavies.github.io/pipedal/download.html で最新の版を確かめる(10/3 時点は 2.0.110)。版が違えば下の数字を置き換える

```bash
cd ~
wget https://github.com/rerdavies/pipedal/releases/download/v2.0.110/pipedal_2.0.110_arm64.deb
sudo apt-get install ./pipedal_2.0.110_arm64.deb
```

- **`apt-get` を使う**(`apt` や `dpkg -i` だと入らない、と公式に書いてある)
- 「権限がない」という注意が出るのは問題なし(公式)

## 6. UR12 をつなぐ

1. UR12 の USB を **PC から抜いて Pi に挿す**(Pi から電気をもらって動く)
2. 認識を確かめる:
   ```bash
   aplay -l
   arecord -l
   ```
   どちらにも `UR12` が出れば OK
3. ベースを UR12 の **入力2(Hi-Z)** に、ヘッドホンを UR12 に

## 7. スマホで PiPedal を開く

1. スマホを家の Wi-Fi につないで、ブラウザで **http://kopedal.local**(開かなければ `http://<PiのIP>`)
2. **Settings → Audio Device Settings**
   - デバイス: UR12
   - サンプルレート: **48000Hz**(公式のおすすめ)
   - バッファ: **16×4**(公式のおすすめ。音がブツブツ切れたら大きくする)
   - 入力: UR12 の Hi-Z は **右チャンネル(入力2)** に来る。音が来なければ入力の選択を変える
3. **Settings → Auto-Hotspot**: 「Not at home」(家の Wi-Fi が無い場所では Pi が自分で Wi-Fi を出す。そのときは `http://10.40.0.1`)
4. 工場出荷の音色(Factory Presets)で鳴らしてみる

> UR12 は弾いた音をそのまま返す(9/30 にわかったこと)。Pi の遅れは数 ms なので、ブラウザの試作のような「ディレイみたい」にはならないはず。気になったらメモする
> **10/6 訂正**: UR12 の前面に DIRECT MONITOR の押しボタンがあり、OFF にすると素の音は返らない(PiPedal を止めて無音になるのを KO が確認)。押し込みの向きは見た目で分かりにくいので、音で確かめる

## 8. NAM を入れて弾き比べる

- PiPedal の NAM のプラグインを置いて、ファイルの選択から PC / スマホのファイルをアップロードする
- 同じ音で **A2-Full と A2-Lite を両方**入れて、音と CPU を比べる

### 入れる NAM(10/3 に TONE3000 の各ページで確認。全部 A2-Full / A2-Lite あり)

| 何に使う | 名前(作った人) | 中身 | ページ |
|---|---|---|---|
| B = 歪み(本命) | **Darkglass B7K Ultra**(Darkglass 公式) | B7K Ultra → Aguilar DB751 → DG412 キャビ(キャビなし版も入っている)。1.4万ダウンロード | https://www.tone3000.com/tones/darkglass-b7k-ultra-27698 |
| B = 歪み(比べる) | Darkglass B7K Bass Preamp Pedal (Cab Built-In)(braindeadtx) | キャビ込み、そのまま使える | https://www.tone3000.com/tones/darkglass-b7k-bass-preamp-pedal-cab-built-in-88 |
| B = 歪み(SansAmp) | TECH21 Sansamp Bass Driver(everipper) | 1.6万ダウンロード。キャビは別に IR が要る | https://www.tone3000.com/tones/tech21-sansamp-bass-driver-31010 |
| アンプ | AMPEG SVT CL (GAIN STAGES)(Deathblossomaudio) | クリーン〜歪みの 10段階。**8x10 キャビの IR が別に要る** | https://www.tone3000.com/tones/ampeg-svt-cl-gain-stages-84925 |
| A = コンプ・ブースト | Bass Pedalboard(flippy) | B7K・Diamond Bass Comp Jr・Bass Soul Food の 4つ | https://www.tone3000.com/tones/bass-pedalboard-28362 |
| メタル | Metal Bass Pack(ratchetstrapmedia) | Bass Driver・B7K・6505 の 4つ | https://www.tone3000.com/tones/metal-bass-pack-5278 |

### KO が PC で作った音色(10/3、TONE3000 プラグインで試奏)

**A = 「Clean」**(TONE3000 のプリセットに保存済み)
1. Noble(Noble Amplifier Company のプリアンプ)
2. → Orange Bass Butler(Bi-Amp Bass Pre)
- これも NAM 2個の直列。キャビの響き(IR)はなし
- 10/3 の画面では Output を上げすぎて出力が 0dB で振り切っていた → 下げて -12〜-6 に合わせる
- TONE3000 のページの正確な名前・作った人は未記録(PiPedal に入れる前に、TONE3000 の履歴かカードの表示で確かめる)

**B = 「Drive」**(TONE3000 のプリセットに保存済み)
1. TECH21 Sansamp Bass Driver(everipper)https://www.tone3000.com/tones/tech21-sansamp-bass-driver-31010
2. → Darkglass B7K Bass Pack(ratchetstrapmedia)https://www.tone3000.com/tones/darkglass-b7k-bass-pack-5319
- 歪みを2段重ねにしている。キャビの響き(IR)はなし
- 下のつまみ: EQ・Gate はほぼ真ん中、Offset は真ん中(オフ)
- **Pi では NAM 2個の直列になる** → 9 の負荷の実験の「NAM 2個」はこの組み合わせで測る
- どちらも A2(Full か Lite かは選ばず、最初に出たまま。Pi で両方試す)
- UR12 の GAIN: 入力2(ベース)= **12時**(入力1も12時)。Pi につないだ日もこの位置から始める
- PC の設定: Yamaha Steinberg USB Driver = Low Latency・128 サンプル(元は 1024 で約 56ms 遅れていた)。設定を変えたら TONE3000 を開き直す

- ライセンス(T3K): 使って録音・公開するのは自由。**ファイルそのものを人に配るのは禁止**(ハードオフ企画で配るのは、自分で取り込んだものだけ)
- C = 飛び道具(オクターバー・エンベロープフィルター)は NAM ではなく普通のエフェクト。PiPedal に入っていなければ `sudo apt install guitarix-lv2` で足す(当日に確かめる)

## 9. 負荷の実験(BUILD_STEPS ステップ1の5)

PiPedal の画面に CPU の使用率が出る。表に書く:

| 組み合わせ | A2-Full の CPU | A2-Lite の CPU | 音切れ |
|---|---|---|---|
| NAM 1個 | | | |
| NAM 2個 | | | |
| NAM 3個 | | | |
| NAM 1個 + IR + 軽いエフェクト 10個 | | | |
| 音色の切り替えで途切れるか | | | |

温度も見る: `vcgencmd measure_temp`(85℃ で遅くなる)

### 10/6 の結果(Pi 5 4GB、UR12、48000Hz、64×3、PiPedal 2.0.110)

モデルは Darkglass B7K Bass Pack(TONE3000 から PiPedal に直接取り込み、A2)。Full / Lite の違いはまだ比べていない(取り込んだのは1種類だけ)。コーラス(CE-2)を後ろに1個つけた状態で測った。

| 組み合わせ | CPU | 音切れ(XRuns) | 温度 |
|---|---|---|---|
| コーラスだけ | 0.5% | 0 | 46℃ |
| NAM 1個 | 10.0% | 0 | 46℃ |
| NAM 2個 | 19.8% | 0 | 47℃ |
| NAM 3個 | 29.5% | 0 | 48℃ |
| NAM 6個 | 60.4% | 0 | 48.5℃ |
| NAM 9個 | 95.8% | 0 | 48.5℃ |
| NAM 9個(うち1個を Threaded) | 85.3% | 0 | 49℃ |
| 音色の切り替え(B7K Drive + Chorus ↔ Bass Chorus) | — | 途切れなし(KO が弾いて確認) | — |

- NAM 1個でおよそ 10%。KO の「Drive」(NAM 2個)は 20% ほどで済む。Threaded を使えば別のコアに逃がせる
- 50℃ を超えないのでファンはほぼ回らない(Pi 5 の公式クーラーは 50℃ から回る)
- → BUILD_STEPS ステップ4の画面は「余裕あり → 5インチ(または7インチ)のタッチ画面」
- **注意**: SD を USB のカードリーダー経由で Pi に挿していたら、読み書きエラー(I/O error)で止まった。SD は必ず Pi のスロットに直接挿す

## 10. 終わるとき

```bash
sudo poweroff
```

緑のランプが止まってから電源を抜く(読み取り専用にするまでは、いきなり抜かない)。

---

## うまくいかないとき

| 症状 | まず見ること |
|---|---|
| `kopedal.local` が見つからない | ルーターで IP を見る。Imager の Wi-Fi の国が JP か |
| UR12 が出ない | 別の USB 口に挿し直す。`dmesg | tail` |
| 音が出ない | 入力チャンネル(右/左)、UR12 の GAIN、PiPedal の音量 |
| ブツブツ切れる | バッファを大きく。NAM を Lite に |
| 起動時に電源の警告 | 電源が WS-U05500X か確かめる(スマホ充電器だと出る) |
