"""CAD lint over out/results.pkl: finalize every glyph outline and report geometric hazards
(remaining holes, invalid/self-touching contours, kissing contours, micro segments, tiny contours)."""
import sys, os, pickle, math, multiprocessing as mp
sys.path.insert(0, os.path.dirname(__file__))
import release_config; release_config.apply()
from stencil.outline import segs_to_path, finalize, finalize_record
from stencil.core import path_polys, signed_area

def lint_one(item):
    g, rec = item
    from shapely.geometry import Polygon
    try:
        p, rep = finalize_record(rec)
        polys = path_polys(p, 0.5)
        shp = []
        for pts, h in polys:
            poly = Polygon(pts)
            if not poly.is_valid:
                rep['invalid'] = rep.get('invalid', 0) + 1
            shp.append(poly)
        # kissing / near-touching distinct contours (ignore proper nesting: hole inside outer etc.)
        kiss = 1e9
        for i in range(len(shp)):
            for j in range(i + 1, len(shp)):
                a, b = shp[i], shp[j]
                if a.contains(b) or b.contains(a):
                    # nested: distance between rings
                    d = a.exterior.distance(b.exterior)
                else:
                    d = a.distance(b)
                kiss = min(kiss, d)
        rep['min_contour_gap'] = kiss
        # near-degenerate angles (spikes): consecutive on-curve points forming < 5 deg turn-back
        spikes = 0
        for pts, h in polys:
            n = len(pts)
            for k in range(n):
                p0, p1, p2 = pts[k-1], pts[k], pts[(k+1) % n]
                v1 = (p0[0]-p1[0], p0[1]-p1[1]); v2 = (p2[0]-p1[0], p2[1]-p1[1])
                l1 = math.hypot(*v1); l2 = math.hypot(*v2)
                if l1 < 1e-6 or l2 < 1e-6:
                    continue
                cosang = (v1[0]*v2[0] + v1[1]*v2[1]) / (l1*l2)
                if cosang > math.cos(math.radians(4)) and min(l1, l2) > 1.0:
                    spikes += 1
        rep['spikes'] = spikes
        rep['g'] = g
        return rep
    except Exception as ex:
        return {'g': g, 'error': str(ex)}

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    res = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else 'out/results.pkl', 'rb'))
    items = [(g, {k: r.get(k) for k in ('segs', 'orig_segs', 'engine', 'chosen')}) for g, r in res.items() if 'segs' in r]
    with mp.Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        reps = pool.map(lint_one, items, chunksize=32)
    bad = {'holes': [], 'invalid': [], 'kiss': [], 'micro': [], 'tiny': [], 'spikes': [], 'error': []}
    for rep in reps:
        g = rep['g']
        if 'error' in rep: bad['error'].append(g); continue
        if rep['holes_after']: bad['holes'].append(g)
        if rep.get('invalid'): bad['invalid'].append(g)
        if rep['min_contour_gap'] < 3.0: bad['kiss'].append((g, round(rep['min_contour_gap'], 2)))
        if rep['min_line_seg'] < 2.0: bad['micro'].append((g, round(rep['min_line_seg'], 2)))
        if rep['tiny_contours']: bad['tiny'].append(g)
        if rep['spikes']: bad['spikes'].append((g, rep['spikes']))
    cmap = {r['g']: r['cp'] for r in res.values()}
    def show(lst):
        out = []
        for x in lst[:40]:
            g = x[0] if isinstance(x, tuple) else x
            cp = cmap.get(g)
            out.append((chr(cp) if cp else g) + ('' if not isinstance(x, tuple) else ':%s' % (x[1],)))
        return ' '.join(out)
    for k, v in bad.items():
        print('%-8s %5d  %s' % (k, len(v), show(v)))
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'out/lint.pkl'
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    pickle.dump(reps, open(out_path, 'wb'))
