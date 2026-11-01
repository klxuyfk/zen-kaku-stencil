"""Re-apply the post-cut cleanup (desliver + trim_leaves) to stored results, for glyphs whose weld
patches left slivers/leaves beside a cut. Updates the results file in place and prints the changed glyphs.
usage: python scripts/postclean.py out/results_bold.pkl
"""
import sys, os, pickle, multiprocessing as mp
sys.path.insert(0, os.path.dirname(__file__))

def fix(item):
    g, segs, rects = item
    from shapely.geometry import Polygon
    from stencil.outline import segs_to_path
    from stencil.weld import desliver, trim_leaves
    from stencil.core import path_polys, signed_area
    try:
        p0 = segs_to_path(segs)
        rs = [Polygon(r) for r in rects]
        p1, a = desliver(p0)
        p1, b = trim_leaves(p1, rs)
        if not (a or b):
            return g, None, 0
        h0 = sum(1 for _, h in path_polys(p0, 0.5) if h); h1 = sum(1 for _, h in path_polys(p1, 0.5) if h)
        c0 = len(list(p0.contours)); c1 = len(list(p1.contours))
        if h1 != h0 or c1 != c0:
            return g, None, -1   # would change topology: leave as is
        return g, [(verb, tuple(pts)) for verb, pts in p1.segments], a + b
    except Exception as ex:
        return g, None, -2

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    path = sys.argv[1]
    res = pickle.load(open(path, 'rb'))
    items = [(g, r['segs'], [c['rect'] for c in r['chosen']]) for g, r in res.items() if 'segs' in r and r['chosen']]
    with mp.Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        out = pool.map(fix, items, chunksize=32)
    changed = []; skipped = []
    for g, segs, n in out:
        if segs is not None:
            res[g]['segs'] = segs; res[g]['postclean'] = n; changed.append(g)
        elif n < 0:
            skipped.append((g, n))
    pickle.dump(res, open(path, 'wb'))
    cmap = {g: r.get('cp') for g, r in res.items()}
    print('changed', len(changed), ''.join(chr(cmap[g]) if cmap.get(g) else '?' for g in changed))
    print('skipped', len(skipped), skipped[:10])
