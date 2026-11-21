"""Bridge (stencil cut) placement: candidate generation, stroke-order scoring, MST selection, cutting."""
import math
from dataclasses import dataclass
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, box
from shapely.geometry.polygon import orient
from shapely.prepared import prep
import pathops
from .core import path_polys, signed_area

# ---------- ink / regions ----------
def ink_polygons(path, tol=1.0):
    polys = path_polys(path, tol)
    outers = [(Polygon(p), abs(signed_area(p))) for p, h in polys if not h]
    holes = [Polygon(p) for p, h in polys if h]
    assigned = {i: [] for i in range(len(outers))}
    for hp in holes:
        rp = hp.representative_point()
        best = None
        for i, (op, area) in enumerate(outers):
            if op.contains(rp) and (best is None or area < outers[best][1]):
                best = i
        if best is not None:
            assigned[best].append(list(hp.exterior.coords))
    result = [Polygon(list(op.exterior.coords), holes=assigned[i]) for i, (op, a) in enumerate(outers)]
    geom = MultiPolygon(result) if len(result) != 1 else result[0]
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom

def material_regions(ink, pad=200):
    """Split the material (plane minus ink) into connected regions. Returns (regions: {id: Polygon}, ext_id)."""
    b = ink.bounds
    frame = box(b[0]-pad, b[1]-pad, b[2]+pad, b[3]+pad)
    mat = frame.difference(ink)
    comps = list(mat.geoms) if hasattr(mat, 'geoms') else [mat]
    regions = {}; ext = None
    for i, c in enumerate(comps):
        regions[i] = c
        if c.exterior.intersects(frame.exterior):
            ext = i
    return regions, ext

# ---------- geometry helpers ----------
def resample_ring(coords, step):
    """Yield (point, unit tangent) every `step` units along a closed ring."""
    n = len(coords)
    carry = 0.0
    for i in range(n):
        p = coords[i]; q = coords[(i + 1) % n]
        seg = math.dist(p, q)
        if seg < 1e-9:
            continue
        t = ((q[0]-p[0])/seg, (q[1]-p[1])/seg)
        pos = carry
        while pos < seg:
            yield (p[0] + t[0]*pos, p[1] + t[1]*pos), t
            pos += step
        carry = pos - seg

def make_rect(a, n, L, w, e):
    """Rectangle of width w along normal n, from a - n*e to a + n*(L+e)."""
    px, py = -n[1], n[0]
    x0 = (a[0] - n[0]*e, a[1] - n[1]*e); x1 = (a[0] + n[0]*(L+e), a[1] + n[1]*(L+e))
    hw = w/2
    return Polygon([(x0[0]+px*hw, x0[1]+py*hw), (x1[0]+px*hw, x1[1]+py*hw),
                    (x1[0]-px*hw, x1[1]-py*hw), (x0[0]-px*hw, x0[1]-py*hw)])

def nearest_on_polyline(pts, c):
    """Return (dist, arc_pos, tangent, total_len) of the nearest point on polyline pts to c."""
    best = (float('inf'), 0.0, (1.0, 0.0)); acc = 0.0
    for i in range(len(pts)-1):
        p, q = pts[i], pts[i+1]
        dx, dy = q[0]-p[0], q[1]-p[1]; L2 = dx*dx+dy*dy
        if L2 < 1e-12:
            continue
        t = max(0.0, min(1.0, ((c[0]-p[0])*dx + (c[1]-p[1])*dy)/L2))
        x, y = p[0]+t*dx, p[1]+t*dy
        d = math.hypot(c[0]-x, c[1]-y)
        seg = math.sqrt(L2)
        if d < best[0]:
            best = (d, acc + t*seg, (dx/seg, dy/seg))
        acc += seg
    return best[0], best[1], best[2], acc

# ---------- candidates ----------
@dataclass
class Cand:
    r1: int; r2: int
    a: tuple; b: tuple; n: tuple; L: float
    rect: Polygon
    cost: float = 0.0
    info: str = ''

def gen_candidates(ink, regions, ext_id, stroke_w, w, step=6.0, Lmax=None, e=5.0, prep_ink=None, clear=10.0):
    Lmax = Lmax or 1.7*stroke_w
    prep_ink = prep_ink or prep(ink)
    preps = {rid: prep(reg) for rid, reg in regions.items()}
    def region_of(pt):
        P = Point(pt)
        for rid, pr in preps.items():
            if pr.contains(P):
                return rid
        return None
    cands = []
    for rid, reg in regions.items():
        if rid == ext_id:
            continue
        ring = orient(Polygon(reg.exterior.coords), 1.0).exterior  # CCW
        coords = list(ring.coords)[:-1]
        for a, t in resample_ring(coords, step):
            n = (t[1], -t[0])  # outward (into ink) for CCW ring
            s0 = (a[0] + n[0]*0.6, a[1] + n[1]*0.6)
            if not prep_ink.contains(Point(s0)):
                continue
            ray = LineString([s0, (a[0] + n[0]*Lmax, a[1] + n[1]*Lmax)])
            out = ray.difference(ink)
            if out.is_empty:
                continue
            pieces = list(out.geoms) if hasattr(out, 'geoms') else [out]
            A = Point(a)
            bpt = None; bd = float('inf')
            for g in pieces:
                for cand_pt in (g.coords[0], g.coords[-1]):
                    d = A.distance(Point(cand_pt))
                    if d < bd:
                        bd = d; bpt = cand_pt
            L = bd
            if L < 0.3*stroke_w or L > Lmax:
                continue
            probe = (bpt[0] + n[0]*1.5, bpt[1] + n[1]*1.5)
            r2 = region_of(probe)
            if r2 is None or r2 == rid:
                continue
            # bar test on a rectangle widened by `clear` on both sides: the cut must sit in a clean,
            # parallel-sided stretch of stroke with at least `clear` units of plain stroke beside it
            wide = make_rect(a, n, L, w + 2*clear, e)
            inter = wide.intersection(ink)
            ncomp = len(inter.geoms) if hasattr(inter, 'geoms') else 1
            if ncomp != 1 or inter.is_empty:
                continue
            if abs(inter.area - L*(w + 2*clear)) > 0.12*L*(w + 2*clear):
                continue
            # no hairline ink (another stroke's edge grazing the zone) inside the widened zone
            thin = inter.difference(inter.buffer(-2.0).buffer(2.0))
            if any((g.area > 8.0 and 2*g.area/max(g.length, 1e-6) < 2.5)
                   for g in (thin.geoms if hasattr(thin, 'geoms') else [thin]) if not g.is_empty):
                continue
            rect = make_rect(a, n, L, w, e)
            cands.append(Cand(rid, r2, a, bpt, n, L, rect))
    return cands

# ---------- stroke-order scoring ----------
COST = {
    ('END', 'THROUGH'): 0.00, ('END', 'END'): 0.02, ('END', 'START'): 0.20,
    ('START', 'END'): 0.25, ('START', 'THROUGH'): 0.30, ('START', 'START'): 0.35,
    ('END', None): 0.40, ('START', None): 0.45,  # free end (no junction found) - unusual
}

def score_candidates(cands, strokes, stroke_w, w, prefer_later=False, match_tol=0.6, junction_tol=1.5):
    """strokes: list of dicts with 'pts' in glyph coords (ordered by stroke number) or None.
    prefer_later: tie-break END cuts towards later strokes (Latin: keep stems, cut bowls)."""
    T = 1.3*stroke_w + w/2
    # geometric fallback preference (no stroke data): bottom-right of the hole, kaisho-like
    if not strokes and cands:
        b = {}
        for c in cands:
            xs, ys = zip(*[c.a])
            r = b.setdefault(c.r1, [1e9, 1e9, -1e9, -1e9])
            r[0] = min(r[0], c.a[0]); r[1] = min(r[1], c.a[1]); r[2] = max(r[2], c.a[0]); r[3] = max(r[3], c.a[1])
    for c in cands:
        geo = 0.15*max(0.0, c.L/stroke_w - 1.0)
        if not strokes:
            x0, y0, x1, y1 = b[c.r1]
            span = max(x1-x0, y1-y0, 1.0)
            pos = ((x1 - c.a[0]) + (c.a[1] - y0)) / span
            c.cost = 1.0 + geo + 0.2*pos; c.info = 'nostroke'; continue
        mid = ((c.a[0]+c.b[0])/2, (c.a[1]+c.b[1])/2)
        best = None
        for si, s in enumerate(strokes):
            d, u, tan, tot = nearest_on_polyline(s['pts'], mid)
            if d > match_tol*stroke_w:
                continue
            if abs(tan[0]*c.n[0] + tan[1]*c.n[1]) > 0.55:   # stroke runs along the ray -> not a crossing
                continue
            if best is None or d < best[0]:
                best = (d, si, u, tot)
        if best is None:
            c.cost = 1.5 + geo; c.info = 'unmatched'; continue
        d, si, u, tot = best
        d_start, d_end = u, tot - u
        if min(d_start, d_end) >= T:
            c.cost = 1.0 + 0.05*min(d_start, d_end)/stroke_w + geo; c.info = 's%d:mid' % (si+1); continue
        is_end = d_end <= d_start
        P = strokes[si]['pts'][-1] if is_end else strokes[si]['pts'][0]
        kind = 'END' if is_end else 'START'
        # what does the endpoint meet?
        meet = None; md = float('inf'); mj = None
        for sj, s2 in enumerate(strokes):
            if sj == si:
                continue
            d2, u2, _, tot2 = nearest_on_polyline(s2['pts'], P)
            if d2 < md:
                md = d2; mj = sj
                T2 = 1.0*stroke_w
                meet = 'START' if u2 < T2 else ('END' if tot2 - u2 < T2 else 'THROUGH')
        if md > junction_tol*stroke_w:
            meet = None
        base = COST[(kind, meet)]
        # tie-breaks: END cuts prefer earlier strokes (kaisho: the later stroke overshoots the earlier
        # one's end), START cuts prefer later strokes; Latin prefers later strokes for both (keep stems).
        tie = min(0.01*si, 0.05) if prefer_later else min(0.004*si, 0.03)
        if kind == 'START' or prefer_later:
            tie = -tie
        near = 0.03*(d_end if is_end else d_start)/stroke_w   # hug the junction
        c.cost = base + tie + near + geo
        c.info = 's%d:%s>%s' % (si+1, kind, ('s%d:%s' % (mj+1, meet)) if meet else 'free')
    return cands

# ---------- selection (MST with conflict avoidance) ----------
class UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}
    def find(self, x):
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)

def select_bridges(cands, regions, ext_id, w, uf=None, chosen=None, min_gap=1.5):
    """Kruskal over material regions; bridges closer than min_gap*w to an already chosen one are skipped."""
    uf = uf or UnionFind(regions.keys())
    chosen = chosen if chosen is not None else []
    for c in sorted(cands, key=lambda c: c.cost):
        a, b = uf.find(c.r1), uf.find(c.r2)
        if a == b:
            continue
        thr = max(min_gap*w, 12.0) if min_gap > 0 else 0.0   # never below the weld gap; 0 = may merge
        if thr and any(c.rect.distance(o.rect) < thr for o in chosen):
            continue
        uf.union(a, b)
        chosen.append(c)
    unconnected = [rid for rid in regions if rid != ext_id and uf.find(rid) != uf.find(ext_id)]
    return chosen, unconnected

# ---------- cutting ----------
def rect_path(poly):
    p = pathops.Path(); pen = p.getPen()
    pts = list(poly.exterior.coords)[:-1]
    pen.moveTo(pts[0])
    for q in pts[1:]:
        pen.lineTo(q)
    pen.closePath()
    return p

def apply_cuts(path, chosen):
    cut = pathops.Path(path)
    for c in chosen:
        g = getattr(c, 'gap_path', None)
        cut = pathops.op(cut, g if g is not None else rect_path(c.rect), pathops.PathOp.DIFFERENCE, fix_winding=True, keep_starting_points=False)
    cut.simplify(fix_winding=True, keep_starting_points=False)
    return cut

# ---------- driver ----------
@dataclass
class Result:
    path: pathops.Path
    chosen: list
    unconnected: list
    n_holes_before: int
    n_holes_after: int
    strokes: list = None
    cands: int = 0
    trims: int = 0

def fill_pinholes(path, regions, ext, fill_min):
    """Fill counters whose bounding box is narrower than fill_min in either direction (pinholes of
    heavy weights that are far too small to be cut out as a stencil island). Returns (path, n_filled)."""
    small = [reg for rid, reg in regions.items() if rid != ext and
             min(reg.bounds[2] - reg.bounds[0], reg.bounds[3] - reg.bounds[1]) < fill_min]
    if not small:
        return path, 0
    cur = pathops.Path(path)
    for reg in small:
        cur = pathops.op(cur, rect_path(reg.buffer(0.5, 1)), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False)
    cur.simplify(fix_winding=True, keep_starting_points=False)
    return cur, len(small)

def stencil_glyph(path, strokes, stroke_w=67.0, w=60.0, step=6.0, prefer_later=False, snap=True, lmax_factor=1.7,
                  clear=10.0, min_gap=1.5, fill_min=0.0):
    if not list(path.contours):
        return Result(path, [], [], 0, 0, strokes, 0)
    ink = ink_polygons(path)
    regions, ext = material_regions(ink)
    if fill_min > 0:
        path, n_filled = fill_pinholes(path, regions, ext, fill_min)
        if n_filled:
            ink = ink_polygons(path)
            regions, ext = material_regions(ink)
    n_holes = len(regions) - 1
    if n_holes == 0:
        return Result(path, [], [], 0, 0, strokes, 0)
    if strokes and snap:
        from .kanjivg import snap as _snap
        strokes = _snap(strokes, ink, stroke_w)
    uf = UnionFind(regions.keys()); chosen = []
    cands = gen_candidates(ink, regions, ext, stroke_w, w, step=step, Lmax=lmax_factor*stroke_w, clear=clear)
    score_candidates(cands, strokes, stroke_w, w, prefer_later=prefer_later)
    chosen, unconnected = select_bridges(cands, regions, ext, w, uf, chosen, min_gap=min_gap)
    # progressively relax for holes that are still floating: allow closer bridges, longer crossings,
    # and finally a narrower bridge for tiny cells
    n_cands = len(cands)
    # the last stage also halves the stroke width used for candidate generation (minimum crossing
    # 0.3*stroke_w), for tiny cells of heavy weights whose walls are thinner than a normal stroke
    for gap, lmax, wf, sf, clear in ((0.8, None, 1.0, 1.0, 10.0), (0.5, 3.2*stroke_w, 1.0, 1.0, 10.0), (0.4, 3.2*stroke_w, 0.7, 1.0, 10.0),
                                     (0.3, 4.0*stroke_w, 0.55, 1.0, 10.0), (0.3, 4.0*stroke_w, 0.5, 0.5, 6.0),
                                     (0.3, 4.0*stroke_w, 0.4, 0.5, 5.0), (0.3, 4.0*stroke_w, 0.3, 0.5, 4.0),
                                     (0.0, 4.0*stroke_w, 0.4, 0.5, 4.0)):
        if not unconnected:
            break
        sub = {rid: regions[rid] for rid in regions if rid == ext or uf.find(rid) != uf.find(ext) or True}
        more = gen_candidates(ink, sub, ext, stroke_w*sf, w*wf, step=step, Lmax=lmax, clear=clear)
        more = [c for c in more if uf.find(c.r1) != uf.find(c.r2)]
        score_candidates(more, strokes, stroke_w*sf, w*wf, prefer_later=prefer_later)
        n_cands += len(more)
        chosen, unconnected = select_bridges(more, regions, ext, w*wf, uf, chosen, min_gap=gap)
    # bridges closer than the weld gap (only possible in the merging stage) are joined into one opening
    joins = []
    for i, c1 in enumerate(chosen):
        for c2 in chosen[i+1:]:
            d = c1.rect.distance(c2.rect)
            if 0.0 < d < 12.0:
                hull = c1.rect.union(c2.rect).convex_hull
                joins.append(Cand(c1.r1, c2.r1, c1.a, c1.b, c1.n, c1.L, hull, 0.0, 'join'))
    cut = apply_cuts(path, chosen + joins)
    from .weld import desliver, weld_guarded, trim_remnants, trim_leaves
    cut, _ntrim = trim_remnants(cut, [c.rect for c in chosen + joins])
    cut, _nleaf = trim_leaves(cut, [c.rect for c in chosen + joins])
    _ntrim += _nleaf
    cut, _nfix = desliver(cut)
    cut, _nw = weld_guarded(cut)
    if _nw:
        # a weld patch next to a cut can itself leave a sliver or a leaf: clean once more
        cut, _n2 = desliver(cut)
        cut, _n3 = trim_leaves(cut, [c.rect for c in chosen + joins])
        _ntrim += _n2 + _n3
    ink2 = ink_polygons(cut)
    regions2, ext2 = material_regions(ink2)
    return Result(cut, chosen + joins, unconnected, n_holes, len(regions2) - 1, strokes, n_cands, _ntrim)
