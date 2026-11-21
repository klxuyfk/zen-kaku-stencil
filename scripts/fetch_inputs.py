"""Download the inputs needed to regenerate the fonts: the parent font and the stroke-order data.

    python scripts/fetch_inputs.py

- Zen Kaku Gothic New Regular (SIL OFL 1.1) from the googlefonts/zen-kakugothic repository
  -> base_font/
- KanjiVG (Copyright Ulrich Apel, CC BY-SA 3.0) from the KanjiVG/kanjivg repository
  -> kanjivg_dl/x/kanji/   (read by scripts/stencil/kanjivg.py while placing bridges; not embedded in the fonts)
"""
import io, os, zipfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'https://github.com/googlefonts/zen-kakugothic/raw/main/fonts/ttf/'
FONTS = ['ZenKakuGothicNew-Regular.ttf', 'OFL.txt']
KVG = 'https://github.com/KanjiVG/kanjivg/archive/refs/heads/master.zip'

def get(url):
    print('downloading', url)
    return urllib.request.urlopen(url, timeout=180).read()

def fetch_base_font():
    d = os.path.join(ROOT, 'base_font'); os.makedirs(d, exist_ok=True)
    for name in FONTS:
        dest = os.path.join(d, name)
        if os.path.exists(dest):
            print('present:', dest); continue
        url = BASE + name if name.endswith('.ttf') else 'https://github.com/googlefonts/zen-kakugothic/raw/main/OFL.txt'
        with open(dest, 'wb') as f:
            f.write(get(url))

def fetch_kanjivg():
    dest = os.path.join(ROOT, 'kanjivg_dl', 'x', 'kanji')
    if os.path.isdir(dest) and len(os.listdir(dest)) > 6000:
        print('present:', dest); return
    z = zipfile.ZipFile(io.BytesIO(get(KVG)))
    os.makedirs(dest, exist_ok=True); n = 0
    for name in z.namelist():
        parts = name.split('/')
        if len(parts) == 3 and parts[1] == 'kanji' and parts[2].endswith('.svg'):
            with open(os.path.join(dest, parts[2]), 'wb') as f:
                f.write(z.read(name)); n += 1
    with open(os.path.join(ROOT, 'kanjivg_dl', 'COPYING'), 'w', encoding='utf-8') as f:
        f.write('KanjiVG, Copyright Ulrich Apel, Creative Commons Attribution-ShareAlike 3.0.\n'
                'https://kanjivg.tagaini.net/  https://creativecommons.org/licenses/by-sa/3.0/\n')
    print('extracted', n, 'stroke files to', dest)

if __name__ == '__main__':
    fetch_base_font()
    fetch_kanjivg()
