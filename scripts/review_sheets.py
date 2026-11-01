"""Render the design-review sheets (PNG) used on the Claude Design canvas.
usage: python scripts/review_sheets.py out/results.pkl out/review
"""
import sys, os, pickle, random
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from types import SimpleNamespace
from shapely.geometry import Polygon
from PIL import Image, ImageDraw, ImageFont
from stencil.outline import segs_to_path, finalize
from stencil.core import path_polys, signed_area

res = pickle.load(open(sys.argv[1], 'rb'))
prefix = sys.argv[2]
by_cp = {r['cp']: r for r in res.values() if r.get('cp') is not None and 'segs' in r}
try:
    LABEL = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 16)
except Exception:
    LABEL = ImageFont.load_default()

def draw_glyph(d, r, ox, oy, cell, final=True, cuts=True, orig=False):
    """Draw one glyph into cell (ox, oy, cell px square)."""
    path = segs_to_path(r['orig_segs'] if orig else r['segs'])
    if final and not orig:
        path, _ = finalize(path)
    x0, y0, x1, y1 = -60, -200, 1060, 920
    s = cell / max(x1 - x0, y1 - y0)
    tf = lambda p: (ox + (p[0] - x0) * s, oy + cell - (p[1] - y0) * s)
    polys = path_polys(path, 0.5)
    polys.sort(key=lambda ph: -abs(signed_area(ph[0])))
    for pts, hole in polys:
        d.polygon([tf(p) for p in pts], fill=((255, 255, 255) if hole else (24, 24, 24)))
    if cuts and not orig:
        for c in r['chosen']:
            pts = [tf(p) for p in c['rect']]
            d.line(pts, fill=(220, 50, 40), width=2)

def sheet(recs, path, cols=8, cell=150, pad=14, pairs=False, title=None):
    n = len(recs)
    cw = cell * (2 if pairs else 1) + pad
    rows = (n + cols - 1) // cols
    top = 46 if title else 10
    img = Image.new('RGB', (cols * cw + pad, rows * (cell + 34) + top + pad), (250, 249, 245))
    d = ImageDraw.Draw(img)
    if title:
        d.text((pad, 12), title, fill=(40, 40, 40), font=LABEL)
    for i, r in enumerate(recs):
        rr, cc = divmod(i, cols)
        x = pad + cc * cw; y = top + rr * (cell + 34)
        d.rectangle([x, y, x + cw - pad, y + cell], fill=(255, 255, 255), outline=(225, 225, 220))
        if pairs:
            draw_glyph(d, r, x, y, cell, orig=True)
            draw_glyph(d, r, x + cell, y, cell)
        else:
            draw_glyph(d, r, x, y, cell)
        ch = chr(r['cp']) if r['cp'] else r['g']
        kinds = [c['info'].split('>')[0].split(':')[-1] for c in r['chosen']]
        summary = ' '.join('%s%d' % (k, kinds.count(k)) for k in ('END', 'START', 'mid') if kinds.count(k))
        d.text((x + 4, y + cell + 6), '%s U+%04X %s' % (ch, r['cp'] or 0, summary), fill=(90, 90, 90), font=LABEL)
    img.save(path); print('wrote', path, img.size)

def recs_for(chars):
    return [by_cp[ord(c)] for c in chars if ord(c) in by_cp]

def block(cp):
    if cp < 0x250: return 'latin'
    if 0x3040 <= cp <= 0x30FF: return 'kana'
    if 0x4E00 <= cp <= 0x9FFF: return 'kanji'
    return 'other'

# 1. rule examples: before/after pairs
sheet(recs_for('口日目田国回東用曲門品BDPRAeg8あおめぬ'), prefix + '_rules.png', cols=6, cell=170, pairs=True,
      title='カット規則の例（左: 原字  右: ステンシル版、赤枠 = ブリッジ）')
# 2. latin & symbols with holes
latin = [r for r in res.values() if 'segs' in r and r['cp'] and r['cp'] < 0x250 and r['holes']]
latin.sort(key=lambda r: r['cp'])
sheet(latin, prefix + '_latin.png', cols=10, cell=120, title='ラテン文字・記号（穴のある全グリフ）')
# 3. kana with holes
kana = [r for r in res.values() if 'segs' in r and r['cp'] and 0x3040 <= r['cp'] <= 0x30FF and r['holes']]
kana.sort(key=lambda r: r['cp'])
sheet(kana, prefix + '_kana.png', cols=10, cell=120, title='かな（穴のある全グリフ）')
# 4. random kanji
kanji = [r for r in res.values() if 'segs' in r and r['cp'] and 0x4E00 <= r['cp'] <= 0x9FFF and r['holes']]
random.Random(42).shuffle(kanji)
sheet(kanji[:80], prefix + '_kanji.png', cols=10, cell=120, title='漢字（無作為抽出 80 字）')
# 5. densest kanji
dense = sorted(kanji, key=lambda r: -r['holes'])[:60]
sheet(dense, prefix + '_dense.png', cols=10, cell=130, title='穴の多い漢字 上位 60 字')
# 6. joyo-ish frequent sample
freq = '日本語東京大学生活時間人間社会国際電話会議新聞雑誌図書館銀行郵便局病院薬局学校駅前道路公園食堂喫茶店映画音楽美術'
sheet(recs_for(freq), prefix + '_common.png', cols=10, cell=120, title='常用漢字サンプル')
