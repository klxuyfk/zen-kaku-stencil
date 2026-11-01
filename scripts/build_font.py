"""Build the stencil TTF from out/results.pkl: replace simple-glyph outlines, keep composites, rename family."""
import sys, os, pickle, time
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from stencil.outline import segs_to_path, finalize
import pathops

BASE = sys.argv[1] if len(sys.argv) > 1 else 'base_font/ZenKakuGothicNew-Regular.ttf'
RESULTS = sys.argv[2] if len(sys.argv) > 2 else 'out/results.pkl'
OUT = sys.argv[3] if len(sys.argv) > 3 else 'out/ZenKakuStencil-Regular.ttf'
FAMILY = os.environ.get('STENCIL_FAMILY', 'Zen Kaku Stencil')
STYLE = os.environ.get('STENCIL_STYLE', 'Regular')

res = pickle.load(open(RESULTS, 'rb'))
f = TTFont(BASE)
glyf = f['glyf']; hmtx = f['hmtx']
glyphset = f.getGlyphSet()
bad = []; n_simple = 0; n_comp = 0; reports = {}
t0 = time.time()
for g in f.getGlyphOrder():
    r = res.get(g)
    if r is None or ('composite' in r and 'segs' not in r):
        n_comp += 1 if (r and 'composite' in r) else 0
        continue
    if 'error' in r:
        bad.append((g, 'error')); continue
    path = segs_to_path(r['segs'])
    final, rep = finalize(path)
    reports[g] = rep
    if not rep['ok']:
        bad.append((g, rep))
    # TrueType wants clockwise outer contours: finalize() leaves outers counter-clockwise, so reverse
    # every contour (a plain reversal keeps the cleaned point set intact, unlike another simplify pass)
    final.reverse()
    ttpen = TTGlyphPen(glyphset)
    pen = Cu2QuPen(ttpen, max_err=0.5, reverse_direction=False)
    final.draw(pen)
    new = ttpen.glyph()
    # guard against degenerate contours (fewer than 3 points)
    if new.numberOfContours > 0:
        ends = list(new.endPtsOfContours); start = 0; degenerate = False
        for e in ends:
            if e - start + 1 < 3:
                degenerate = True
            start = e + 1
        if degenerate:
            bad.append((g, 'degenerate contour'))
    glyf[g] = new
    n_simple += 1
print('rebuilt simple glyphs', n_simple, 'composites kept', n_comp, 'flagged', len(bad), 'in %.0fs' % (time.time()-t0))
for g, rep in bad[:15]:
    print('  ', g, rep)
# drop the (now invalid) digital signature
if 'DSIG' in f:
    del f['DSIG']
f['head'].flags |= 0  # leave flags
# names
name = f['name']
ps = (FAMILY + '-' + STYLE).replace(' ', '')
for rec in name.names:
    nid = rec.nameID
    if nid == 1: rec.string = FAMILY
    elif nid == 2: rec.string = STYLE
    elif nid == 3: rec.string = '%s;%s' % (ps, time.strftime('%Y%m%d'))
    elif nid == 4: rec.string = '%s %s' % (FAMILY, STYLE)
    elif nid == 5: rec.string = 'Version 0.1; stencil derivative of Zen Kaku Gothic New'
    elif nid == 6: rec.string = ps
    elif nid == 16: rec.string = FAMILY
    elif nid == 17: rec.string = STYLE
# OpenType requires both maxp/head recomputation on save; fontTools does it on compile
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
f.save(OUT)
pickle.dump({'bad': bad, 'reports': reports}, open(OUT + '.report.pkl', 'wb'))
print('saved', OUT, os.path.getsize(OUT), 'bytes')
