# 手順 F(音の基板)の穴の配置図を作る。行 A〜L(上→下)・列 1〜20。step_f_board.html の <!--BOARD--> に入れる。
S, X0, Y0 = 34, 70, 50
ROWS = 'ABCDEFGHIJKL'
def xy(h):
    r, c = ROWS.index(h[0]), int(h[1:]) - 1
    return X0 + c * S, Y0 + r * S
out = []
W, H = X0 + 20 * S + 40, Y0 + 12 * S + 30
out.append(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="基板の穴の配置図(部品の面から見た図)">')
out.append(f'<rect x="{X0-22}" y="{Y0-22}" width="{19*S+44}" height="{11*S+44}" rx="8" fill="var(--board)" stroke="var(--part-edge)"/>')
for c in range(20):
    out.append(f'<text x="{X0+c*S}" y="{Y0-28}" text-anchor="middle" class="small mono">{c+1}</text>')
for r, R in enumerate(ROWS):
    out.append(f'<text x="{X0-36}" y="{Y0+r*S+4}" text-anchor="middle" class="small mono">{R}</text>')
    for c in range(20):
        out.append(f'<circle cx="{X0+c*S}" cy="{Y0+r*S}" r="3.2" fill="var(--hole)"/>')
def wire(a, b, cls, dash=False):
    (x1, y1), (x2, y2) = xy(a), xy(b)
    d = ' stroke-dasharray="7 5"' if dash else ''
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="w {cls}"{d}/>')
def pad(h, label, cls, side='r'):
    x, y = xy(h)
    out.append(f'<circle cx="{x}" cy="{y}" r="8" class="pad {cls}"/>')
    dx, anc = {'r': (14, 'start'), 'l': (-14, 'end'), 'u': (0, 'middle'), 'd': (0, 'middle')}[side]
    dy = {'u': -14, 'd': 24}.get(side, 4)
    out.append(f'<text x="{x+dx}" y="{y+dy}" text-anchor="{anc}" class="lbl">{label}</text>')
# 裏の線(点線)と表のはんだブリッジ(実線)
wire('I1', 'I19', 'gnd')                       # 制御 GND の列(すずめっき線)
wire('B8', 'I8', 'gnd', True)                  # Q1 E → GND の列
wire('B1', 'B2', 'ctl'); wire('B5', 'B6', 'ctl')   # GP9 → R1 → ベース
wire('B7', 'D11', 'ctl', True)                 # コレクター → 10 番
wire('D10', 'D11', 'ctl'); wire('G10', 'G11', 'pwr')   # ダイオード ↔ 10 番 / 1 番
wire('D1', 'G9', 'pwr', True); wire('G9', 'G10', 'pwr')  # +5V → 1 番
wire('D12', 'G12', 'sig', True)                # 2 ↔ 9 素通り
wire('A13', 'D13', 'sig', True); wire('A15', 'D14', 'sig', True)
wire('L13', 'G13', 'in', True); wire('L15', 'G14', 'in', True)
wire('L17', 'L18', 'ing')
# 部品
x, y = xy('D11'); x2, y2 = xy('G15')
out.append(f'<rect x="{x-14}" y="{y-14}" width="{x2-x+28}" height="{y2-y+28}" rx="4" class="part"/>')
out.append(f'<circle cx="{x-6}" cy="{(y+y2)/2}" r="4" fill="var(--fg)"/>')
out.append(f'<text x="{(x+x2)/2}" y="{(y+y2)/2+5}" text-anchor="middle" class="lbl b">TQ2-5V</text>')
for i, n in enumerate([10, 9, 8, 7, 6]):
    px, py = xy(f'D{11+i}'); out.append(f'<text x="{px}" y="{py+22}" text-anchor="middle" class="pin">{n}</text>')
for i, n in enumerate([1, 2, 3, 4, 5]):
    px, py = xy(f'G{11+i}'); out.append(f'<text x="{px}" y="{py-12}" text-anchor="middle" class="pin">{n}</text>')
(x, y), (x2, _) = xy('B2'), xy('B5')
out.append(f'<rect x="{x+4}" y="{y-7}" width="{x2-x-8}" height="14" rx="6" class="part res"/><text x="{(x+x2)/2}" y="{y-12}" text-anchor="middle" class="lbl">R1 1kΩ</text>')
(x, y), (x2, _) = xy('B6'), xy('B8')
out.append(f'<path d="M{x-10} {y+9} L{x2+10} {y+9} L{x2+10} {y-3} Q{(x+x2)/2} {y-22} {x-10} {y-3} Z" class="part"/>')
for h, n in (('B6', 'B'), ('B7', 'C'), ('B8', 'E')):
    px, py = xy(h); out.append(f'<text x="{px}" y="{py+24}" text-anchor="middle" class="pin">{n}</text>')
out.append(f'<text x="{xy("B7")[0]}" y="{xy("B7")[1]-26}" text-anchor="middle" class="lbl">Q1 2SC1815</text>')
(x, y), (_, y2) = xy('D10'), xy('G10')
out.append(f'<rect x="{x-7}" y="{y+5}" width="14" height="{y2-y-10}" rx="5" class="part dio"/><rect x="{x-7}" y="{y2-14}" width="14" height="5" fill="var(--fg)"/>')
out.append(f'<text x="{x-12}" y="{(y+y2)/2+4}" text-anchor="end" class="lbl">D1 1N4148</text>')
# 線の着地点
pad('B1', 'Pico GP9', 'ctl', 'l'); pad('D1', 'Pico VBUS(+5V)', 'pwr', 'l'); pad('I1', 'Pico GND', 'gnd', 'l')
pad('A13', 'OUT ジャック 先', 'sig', 'u'); pad('A15', 'LINE OUT L 芯', 'sig', 'u')
pad('I18', 'OUT スリーブ', 'gnd', 'd'); pad('I19', 'LINE OUT 網線', 'gnd', 'r')
pad('L13', 'IN 先', 'in', 'd'); pad('L15', 'HI-Z 芯', 'in', 'd')
pad('L17', '', 'ing'); pad('L18', 'IN スリーブ + HI-Z 網線', 'ing', 'r')
out.append('</svg>')
print('\n'.join(out))
