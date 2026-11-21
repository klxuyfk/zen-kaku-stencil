"""Stencil a few characters and render a contact sheet with the cut outlines and the stroke-order data
drawn over the glyphs (quick parameter checks). The cuts are those of the release (release_config.py);
--v1 gives the cuts of the first release.
usage: python scripts/run_sample.py <chars> <out.png> [--font F] [--stroke 67] [--w 60] [--nostrokes] [--v1]
"""
import sys, os, time, argparse; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_config; release_config.apply()
from stencil.core import Font, contact_sheet
from stencil import kanjivg
from stencil.bridges import stencil_glyph
from stencil.junction import stencil_glyph2
from stencil.outline import finalize
from stencil.weld import weld
from stencil.review import render_result
ap = argparse.ArgumentParser()
ap.add_argument('chars', nargs='?', default='口日目田国回東曲用あおめBAa0e8@'); ap.add_argument('out', nargs='?', default='out/sample.png')
ap.add_argument('--font', default='base_font/ZenKakuGothicNew-Regular.ttf'); ap.add_argument('--stroke', type=float, default=67.0)
ap.add_argument('--w', type=float, default=60.0); ap.add_argument('--nostrokes', action='store_true'); ap.add_argument('--cols', type=int, default=6)
ap.add_argument('--v1', action='store_true')
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
    cjk = 0x2E80 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0xFF61 <= cp <= 0xFF9F
    res = (stencil_glyph if a.v1 else stencil_glyph2)(p, strokes, a.stroke, a.w, prefer_later=not cjk, lmax_factor=(1.7 if ideograph else 2.1))
    if not a.v1:
        res.path, _ = finalize(res.path, base=p)          # as build_font.py does: the short pieces beside the cuts removed
    print("%s welds %d holes %d->%d cands %d chosen %s unconnected %s %.2fs" % (
        ch, nw, res.n_holes_before, res.n_holes_after, res.cands,
        [(c.info.split('>')[0], round(c.cost, 3)) for c in res.chosen], res.unconnected, time.time()-t))
    imgs.append(render_result(res, label=ch, show_strokes=not a.nostrokes))
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
contact_sheet(imgs, cols=a.cols).save(a.out)
print('total', round(time.time()-t0, 1), 's ->', a.out)
