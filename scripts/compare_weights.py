"""Side-by-side sheet of two result sets (e.g. Regular vs Bold) for the same characters.
usage: python scripts/compare_weights.py a.pkl b.pkl out.png <chars> [cols]
"""
import sys, os, pickle; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFont
from stencil.outline import segs_to_path, finalize
from stencil.core import path_polys, signed_area
A = pickle.load(open(sys.argv[1], 'rb')); B = pickle.load(open(sys.argv[2], 'rb'))
out = sys.argv[3]; chars = sys.argv[4]; cols = int(sys.argv[5]) if len(sys.argv) > 5 else 5
LABEL = ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc', 15)
byA = {r['cp']: r for r in A.values() if r.get('cp') is not None and 'segs' in r}
byB = {r['cp']: r for r in B.values() if r.get('cp') is not None and 'segs' in r}
def draw_glyph(d, r, ox, oy, cell):
    path, _ = finalize(segs_to_path(r['segs']))
    x0, y0, x1, y1 = -60, -200, 1060, 920; s = cell / max(x1 - x0, y1 - y0)
    tf = lambda p: (ox + (p[0] - x0) * s, oy + cell - (p[1] - y0) * s)
    polys = path_polys(path, 0.5); polys.sort(key=lambda ph: -abs(signed_area(ph[0])))
    for pts, hole in polys:
        d.polygon([tf(p) for p in pts], fill=((255, 255, 255) if hole else (24, 24, 24)))
    for c in r['chosen']:
        d.line([tf(p) for p in c['rect']], fill=(220, 50, 40), width=2)
def kinds(r):
    ks = [c['info'].split('>')[0].split(':')[-1] for c in r['chosen']]
    return ' '.join('%s%d' % (k, ks.count(k)) for k in ('END', 'START', 'mid', 'nostroke', 'unmatched') if ks.count(k))
cell = 150; pad = 12; cw = 2 * cell + pad
recs = [(c, byA.get(ord(c)), byB.get(ord(c))) for c in chars if ord(c) in byA and ord(c) in byB]
rows = (len(recs) + cols - 1) // cols
img = Image.new('RGB', (cols * cw + pad, rows * (cell + 40) + pad), (250, 249, 245)); d = ImageDraw.Draw(img)
for i, (c, ra, rb) in enumerate(recs):
    rr, cc = divmod(i, cols); x = pad + cc * cw; y = pad + rr * (cell + 40)
    d.rectangle([x, y, x + cw - pad, y + cell], fill=(255, 255, 255), outline=(225, 225, 220))
    draw_glyph(d, ra, x, y, cell); draw_glyph(d, rb, x + cell, y, cell)
    d.text((x + 4, y + cell + 4), '%s  R: %s' % (c, kinds(ra)), fill=(90, 90, 90), font=LABEL)
    d.text((x + 4, y + cell + 21), '    B: %s' % kinds(rb), fill=(90, 90, 90), font=LABEL)
img.save(out); print('wrote', out, img.size)
