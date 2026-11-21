"""Batch-stencil every simple glyph of the base font with multiprocessing. Writes out/results.pkl.
STENCIL_ENGINE=corners (default): the revised cuts (stencil.junction.stencil_glyph2, docs/09_revision_policy.md)
with the options in STENCIL_OPTS (default: the release options in release_config.py); a glyph the revised cuts
cannot open completely falls back to the first release's cuts (rec['engine'] says which was used).
STENCIL_ENGINE=bridges: the first release's cuts (stencil.bridges.stencil_glyph, v1.000)."""
import sys, os, time, pickle, traceback, multiprocessing as mp
sys.path.insert(0, os.path.dirname(__file__))
import release_config; release_config.apply()
from stencil.core import Font
from stencil import kanjivg
from stencil.bridges import stencil_glyph
from stencil.weld import weld

FONT = os.environ.get('STENCIL_FONT', 'base_font/ZenKakuGothicNew-Regular.ttf')
STROKE_W = float(os.environ.get('STENCIL_STROKE_W', 67.0))
W = float(os.environ.get('STENCIL_W', 60.0))
CLEAR = float(os.environ.get('STENCIL_CLEAR', 10.0))        # side clearance of the clean-bar test
MIN_GAP = float(os.environ.get('STENCIL_MIN_GAP', 1.5))    # first-pass spacing between bridges, x W
FILL_MIN = float(os.environ.get('STENCIL_FILL_MIN', 0.0))  # fill counters narrower than this (0 = off)
ENGINE = os.environ.get('STENCIL_ENGINE', 'corners')
_font = None; _rev = None

def init():
    global _font, _rev
    _font = Font(FONT)
    _rev = {}
    for c, g in _font.cmap.items():
        _rev.setdefault(g, c)

def stroke_source(cp):
    if cp is None:
        return None
    if 0xFF01 <= cp <= 0xFF5E:          # fullwidth ASCII -> ASCII
        return cp - 0xFEE0
    return cp

def is_cjk(cp):
    return cp is not None and (0x2E80 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0xFF61 <= cp <= 0xFF9F)

def path_segments(path):
    return [(verb, tuple(pts)) for verb, pts in path.segments]

def work(gname):
    t = time.time()
    rec = {'g': gname, 'cp': _rev.get(gname)}
    try:
        glyph = _font.tt['glyf'][gname]
        if glyph.isComposite():
            rec['composite'] = [(c.glyphName, c.x, c.y) for c in glyph.components]
            # keep the composite unless its components overlap/touch (e.g. C + cedilla): those are
            # flattened and processed as a simple glyph so the outline is a clean union
            raw = _font.raw_path(gname); clean = _font.clean_path(gname)
            from stencil.weld import problems
            if abs(raw.area - clean.area) > 1.0 or len(list(raw.contours)) != len(list(clean.contours)) or problems(clean):
                rec['decomposed'] = True
            else:
                return rec
        p = _font.clean_path(gname)
        p, n_weld = weld(p)
        rec['welds'] = n_weld
        cp = rec['cp']
        strokes = None; src = stroke_source(cp)
        if src is not None and rec.get('composite'):
            # accented letter: use the base letter's strokes
            import unicodedata
            base = unicodedata.normalize('NFD', chr(cp))[0]
            src = ord(base)
        if src is not None:
            kv = kanjivg.load(src)
            if kv:
                strokes = kanjivg.align(kv, p.bounds, STROKE_W)
        ideograph = cp is not None and (0x2E80 <= cp <= 0x2FDF or 0x3400 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF)
        res = None; rec['engine'] = 'bridges'
        if ENGINE == 'corners':
            from stencil import junction as _junction
            import copy
            try:
                res = _junction.stencil_glyph2(p, copy.deepcopy(strokes), STROKE_W, W, prefer_later=not is_cjk(cp), lmax_factor=(1.7 if ideograph else 2.1), clear=CLEAR, min_gap=MIN_GAP, fill_min=FILL_MIN)
                rec['filled'] = _junction.LAST_FILLED
                if res.unconnected or res.n_holes_after:
                    res2 = _junction.stencil_glyph2(p, copy.deepcopy(strokes), STROKE_W*0.5, W*0.5, prefer_later=not is_cjk(cp), lmax_factor=2.1, clear=CLEAR, min_gap=MIN_GAP, fill_min=FILL_MIN)
                    if not (res2.unconnected or res2.n_holes_after):
                        res = res2; rec['small'] = True; rec['filled'] = _junction.LAST_FILLED
                if res.unconnected or res.n_holes_after:
                    rec['corners_unresolved'] = True; res = None
                else:
                    rec['engine'] = 'corners'
            except Exception:
                rec['corners_error'] = traceback.format_exc(); res = None
        if res is None:
            res = stencil_glyph(p, strokes, STROKE_W, W, prefer_later=not is_cjk(cp), lmax_factor=(1.7 if ideograph else 2.1), clear=CLEAR, min_gap=MIN_GAP, fill_min=FILL_MIN)
            if res.unconnected or res.n_holes_after:
                # last resort for scaled-down multi-character glyphs (e.g. square kana ligatures): thinner strokes
                res2 = stencil_glyph(p, strokes, STROKE_W*0.5, W*0.5, prefer_later=not is_cjk(cp), lmax_factor=2.1, clear=CLEAR, min_gap=MIN_GAP, fill_min=FILL_MIN)
                if not (res2.unconnected or res2.n_holes_after):
                    res = res2; rec['small'] = True
        rec.update({
            'segs': path_segments(res.path),
            'orig_segs': path_segments(p),
            'chosen': [{'info': c.info, 'cost': c.cost, 'rect': list((c.rect if c.rect.geom_type == 'Polygon' else c.rect.convex_hull).exterior.coords),
                        'a': c.a, 'b': c.b, 'n': c.n, 'L': c.L, 'w': getattr(c, 'w', None)} for c in res.chosen],
            'unconnected': res.unconnected, 'holes': res.n_holes_before, 'holes_after': res.n_holes_after,
            'strokes': [s['pts'] for s in res.strokes] if res.strokes else None, 'cands': res.cands,
            'has_strokes': strokes is not None, 'adv': _font.advance(gname), 'trims': res.trims,
        })
    except Exception:
        rec['error'] = traceback.format_exc()
    rec['t'] = time.time() - t
    return rec

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    out = sys.argv[1] if len(sys.argv) > 1 else 'out/results.pkl'
    f = Font(FONT)
    names = f.tt.getGlyphOrder()
    if len(sys.argv) > 2:
        names = names[:int(sys.argv[2])]
    t0 = time.time()
    n = int(os.environ.get('STENCIL_PROCS', max(1, (os.cpu_count() or 2) - 1)))
    results = {}
    with mp.Pool(n, initializer=init) as pool:
        for i, rec in enumerate(pool.imap_unordered(work, names, chunksize=16)):
            results[rec['g']] = rec
            if i % 500 == 0:
                print(f"{i}/{len(names)} {time.time()-t0:.0f}s", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    pickle.dump(results, open(out, 'wb'))
    errs = [r for r in results.values() if 'error' in r]
    unc = [r for r in results.values() if r.get('unconnected') or r.get('holes_after')]
    print(f"done {len(results)} glyphs in {time.time()-t0:.0f}s; errors {len(errs)}; unresolved holes {len(unc)}")
    if ENGINE == 'corners':
        cut = [r for r in results.values() if r.get('chosen')]
        print('revised cuts: %d glyphs; first-release cuts kept: %d (unresolved %d, error %d); half-size %d; rooms filled in %d glyphs' % (
            sum(1 for r in cut if r.get('engine') == 'corners'), sum(1 for r in cut if r.get('engine') != 'corners'),
            sum(1 for r in results.values() if r.get('corners_unresolved')), sum(1 for r in results.values() if r.get('corners_error')),
            sum(1 for r in results.values() if r.get('small')), sum(1 for r in results.values() if r.get('filled'))))
    for r in errs[:5]:
        print(r['g'], r['error'].splitlines()[-1])
