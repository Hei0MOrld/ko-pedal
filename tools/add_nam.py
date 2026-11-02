# NAM のモデル(.nam)をペダル(kopedal の PiPedal)に入れる(2026-11-01)。
# スマホの PiPedal から TONE3000 を直接落とすのは、http のペダルへ戻る所で Chrome / アプリが止める(「接続は安全ではありません」)。
# → KO が PC で TONE3000 から .nam を落とす → これがペダルへ送る。保護(overlayroot)中でも消えないよう SD 本体にも書く。
# 置き場所: /var/pipedal/audio_uploads/NeuralAmpModels/TONE3000/(PiPedal の Model の一覧に「TONE3000」フォルダで出る)
#   python add_nam.py <ファイル.nam> [...]      (scripts/media_inbox.py もダウンロードの新しい .nam をこれで送る)
import shlex
import subprocess
import sys
from pathlib import Path

HOST = 'ko@kopedal'
DEST = '/var/pipedal/audio_uploads/NeuralAmpModels/TONE3000'
SSH = ['ssh', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes']
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def send(path: Path) -> str:
    tmp = f'/tmp/{path.name}'
    subprocess.run(['scp', '-q', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', str(path), f'{HOST}:{tmp}'],
                   check=True, timeout=300, creationflags=NO_WINDOW)
    q, d = shlex.quote(tmp), shlex.quote(DEST)
    name = shlex.quote(path.name)
    remote = (
        f'set -e; sudo mkdir -p {d}; sudo chown pipedal_d:pipedal_d {d}; '
        f'sudo install -o pipedal_d -g pipedal_d -m 664 {q} {d}/{name}; '
        # 保護中なら SD 本体(/media/root-ro)にも同じものを書く。数秒だけ書き込みにしてすぐ戻す(pedal-persist と同じやり方)
        f'if [ -d /media/root-ro/var/pipedal ]; then '
        f'  sudo mount -o remount,rw /media/root-ro; '
        f'  sudo mkdir -p /media/root-ro{d}; sudo install -o pipedal_d -g pipedal_d -m 664 {q} /media/root-ro{d}/{name}; '
        f'  sync; sudo mount -o remount,ro /media/root-ro; echo saved-to-sd; fi; '
        f'rm -f {q}')
    r = subprocess.run(SSH + [HOST, remote], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=120, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(f'{path.name}: {r.stderr.strip()[:300]}')
    return r.stdout.strip()


if __name__ == '__main__':
    for a in sys.argv[1:]:
        print(Path(a).name, send(Path(a)) or 'ok')
