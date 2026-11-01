"""Stencil a few characters and render a contact sheet (quick parameter checks).
usage: python scripts/run_sample.py <chars> <out.png> [--font F] [--stroke 67] [--w 60] [--nostrokes]
"""
import sys, os, time, argparse; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from stencil.core import Font, contact_sheet
from stencil import kanjivg
from stencil.bridges import stencil_glyph
from stencil.weld import weld
from stencil.review import render_result
ap = argparse.ArgumentParser()
ap.add_argument('chars', nargs='?', default='口日目田国回東曲用あおめBAa0e8@'); ap.add_argument('out', nargs='?', default='out/sample.png')
ap.add_argument('--font', default='base_font/ZenKakuGothicNew-Regular.ttf'); ap.add_argument('--stroke', type=float, default=67.0)
ap.add_argument('--w', type=float, default=60.0); ap.add_argument('--nostrokes', action='store_true'); ap.add_argument('--cols', type=int, default=6)
a = ap.parse_args()
f = Font(a.font)
imgs = []
t0 = time.time()
for ch in a.chars:
    g = f.glyph_name(ch)
    if g is None:
        print('no glyph', ch); continue
    p = f.clean_path(g); p, nw = weld(p)
    kv = kanjivg.load(ord(ch))
    strokes = kanjivg.align(kv, p.bounds, a.stroke) if kv else None
    cp = ord(ch); ideograph = 0x2E80 <= cp <= 0x2FDF or 0x3400 <= cp <= 0x9FFF
    t = time.time()
    res = stencil_glyph(p, strokes, a.stroke, a.w, prefer_later=(cp < 0x250), lmax_factor=(1.7 if ideograph else 2.1))
    print("%s welds %d holes %d->%d cands %d chosen %s unconnected %s %.2fs" % (
        ch, nw, res.n_holes_before, res.n_holes_after, res.cands,
        [(c.info.split('>')[0], round(c.cost, 3)) for c in res.chosen], res.unconnected, time.time()-t))
    imgs.append(render_result(res, label=ch, show_strokes=not a.nostrokes))
contact_sheet(imgs, cols=a.cols).save(a.out)
print('total', round(time.time()-t0, 1), 's ->', a.out)
