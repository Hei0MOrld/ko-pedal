// ベース用の歪み — 2026-09-30 試作 2 号・強め版
// 低音(120Hz 以下)は歪ませる前に削る。削った低音は UR12 が返す元の音が補うので、
// 「原音を混ぜる(ドライ・ブレンド)」形になる。
// KO の方針に合わせて、歪みを強め・音量を最大にして、元の音より大きく鳴らす。
import("stdfaust.lib");

drive = hslider("[0]歪み(dB)", 32, 0, 45, 0.1) : ba.db2linear : si.smoo;
tone  = hslider("[1]音色(Hz)", 2500, 500, 8000, 10) : si.smoo;
level = hslider("[2]音量", 1, 0, 1, 0.01) : si.smoo;

// 丸く潰す(ソフトクリップ)。どんなに大きい音でも ±1 に収まる
clip(x) = x / sqrt(1 + x * x);

// 安全装置: どんな音が来ても ±0.5 を超えないように切る
safety = max(-0.5) : min(0.5);

// UR12 の入力1と入力2を足す
bass = +;

process = bass : fi.highpass(2, 120) : *(drive) : clip : fi.lowpass(2, tone) : *(level) : safety <: _, _;
