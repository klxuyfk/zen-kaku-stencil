"""Prototype of the revised cut geometry (2026-11-03 design review).

Old: a rectangle of width w is pushed across the wall between two material regions, perpendicular to the
hole boundary, overshooting each face by 5 units. At a junction the rectangle may land on the through
stroke, its straight ends leave slivers where the faces are not parallel, and the lateral position is
whatever sample point scored best, so the bite into the through stroke varies.

New ("end cut"): the terminating stroke A is cut square (perpendicular to its own direction) at the
place where the nearer corner of the cut face is w away from the face of the stroke B it meets, and all
of A's ink between that cut and B's face is removed. B's face is fitted (line or circle) through face
points measured on the ink on both sides of the junction and is never carved (bite 0.5 unit).
  - A right-angle T junction gives the same w x stroke-width rectangle as before, now flush with B.
  - An oblique or tangential junction (僕's diagonal, る's curl meeting its own body) gets a square end and
    a gap of at least w everywhere, with no sliver left on B.
  - The same construction serves stroke endpoints (END/START), an endpoint meeting its own body and the
    arms of crossings including self-crossings (は).
  - A candidate is dropped when the stub of A that would remain is shorter than 0.5 stroke widths
    (tiny cells of heavy weights); such cells are opened through the frame by the old ring-sampled cut,
    whose ends now follow the faces too (`adaptive_rect`).
All measurements are taken on the ink through full cross-sections, because the snapped KanjiVG centrelines
can sit up to half a stroke width off centre and their last segment is often bent at a junction.
Selection stays a minimum spanning tree over the material regions with the stroke-order cost table; the
spacing rule between chosen cuts applies only to cuts on the same stroke, so neighbouring cells can all be
opened on the same side.
"""
import math
from shapely.geometry import Polygon, LineString, Point
from .bridges import (Cand, COST, UnionFind, nearest_on_polyline, make_rect, ink_polygons, material_regions,
                      gen_candidates, score_candidates, apply_cuts, Result)


def _unit(v):
    L = math.hypot(v[0], v[1])
    return (v[0] / L, v[1] / L) if L > 1e-9 else (1.0, 0.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _pieces(g):
    return [p for p in (g.geoms if hasattr(g, 'geoms') else [g]) if not p.is_empty]


def point_at(pts, u):
    """(point, unit tangent) at arc length u along polyline pts (clamped)."""
    acc = 0.0
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        seg = math.dist(p, q)
        if seg < 1e-9:
            continue
        if acc + seg >= u or i == len(pts) - 2:
            t = max(0.0, min(1.0, (u - acc) / seg))
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t), _unit((q[0] - p[0], q[1] - p[1]))
        acc += seg
    return pts[-1], _unit((pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]))


def poly_length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def tangent_at(pts, u, half):
    """Chord direction of the polyline over [u-half, u+half] (robust to a distorted last segment)."""
    tot = poly_length(pts)
    a = max(0.0, u - half); b = min(tot, u + half)
    if b - a < 1.0:
        return point_at(pts, u)[1]
    pa, _ = point_at(pts, a); pb, _ = point_at(pts, b)
    return _unit((pb[0] - pa[0], pb[1] - pa[1]))


def ref_tangent(pts, u, half, exclude=None):
    """Direction of the longest polyline segment within [u-half, u+half] (ignores a vertex that the snap
    pulled onto a crossing stroke); follows the polyline order."""
    acc = 0.0; best = None
    for i in range(len(pts) - 1):
        seg = math.dist(pts[i], pts[i + 1])
        a, b = max(acc, u - half), min(acc + seg, u + half)
        if b > a and not (exclude is not None and exclude[0] <= acc <= exclude[1]):
            if best is None or b - a > best[0]:
                best = (b - a, _unit((pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])))
        acc += seg
    return best[1] if best else point_at(pts, u)[1]


def face_point(ink, origin, n, max_d):
    """First exit from the ink along n starting at origin (inside the ink): (point, distance) or None."""
    seg = LineString([origin, (origin[0] + n[0] * max_d, origin[1] + n[1] * max_d)])
    inter = seg.intersection(ink)
    O = Point(origin)
    own = [g for g in _pieces(inter) if g.geom_type == 'LineString' and g.distance(O) < 1e-6]
    if not own:
        return None
    far = max(own[0].coords, key=lambda p: math.dist(p, origin))
    return far, math.dist(far, origin)


def inside_point(ink, pt, n, step):
    """pt, or the nearest of pt +- n*step*(1,2) that lies inside the ink; None if none does."""
    if ink.contains(Point(pt)):
        return pt
    for k in (1, -1, 2, -2):
        q = (pt[0] + n[0] * step * k, pt[1] + n[1] * step * k)
        if ink.contains(Point(q)):
            return q
    return None


def cross_section(ink, pt, n, max_d):
    """Ink cross-section through pt along +-n: (point on +n side, point on -n side, length) or None."""
    r1 = face_point(ink, pt, n, max_d); r2 = face_point(ink, pt, (-n[0], -n[1]), max_d)
    if not (r1 and r2):
        return None
    return r1[0], r2[0], r1[1] + r2[1]


# ---------- the face of the stroke that is met ----------
def _fit_circle(pts):
    """Algebraic (Kasa) least-squares circle through points; None when degenerate."""
    n = len(pts)
    sx = sum(p[0] for p in pts) / n; sy = sum(p[1] for p in pts) / n
    xs = [p[0] - sx for p in pts]; ys = [p[1] - sy for p in pts]
    Suu = sum(x * x for x in xs); Svv = sum(y * y for y in ys); Suv = sum(x * y for x, y in zip(xs, ys))
    Suuu = sum(x ** 3 for x in xs); Svvv = sum(y ** 3 for y in ys)
    Suvv = sum(x * y * y for x, y in zip(xs, ys)); Svuu = sum(y * x * x for x, y in zip(xs, ys))
    det = Suu * Svv - Suv * Suv
    if abs(det) < 1e-6:
        return None, None
    uc = (Svv * (Suuu + Suvv) - Suv * (Svvv + Svuu)) / (2 * det)
    vc = (Suu * (Svvv + Svuu) - Suv * (Suuu + Suvv)) / (2 * det)
    R = math.sqrt(uc * uc + vc * vc + (Suu + Svv) / n)
    return (uc + sx, vc + sy), R


class Face:
    """B's face near a junction: a line or a circle fitted through measured face points.
    samples: list of (point, k) with k the arc distance from the junction (signed). `nB` points to A's side."""
    def __init__(self, samples, nB, tB, stroke_w=67.0):
        self_sw = stroke_w
        pts = [p for p, k in samples]
        self.kind = 'line'
        if len(pts) >= 3:
            a, b = pts[0], pts[-1]
            lf0 = _unit((b[0] - a[0], b[1] - a[1])); nf0 = (-lf0[1], lf0[0])
            sagitta = max(abs(_dot((p[0] - a[0], p[1] - a[1]), nf0)) for p in pts)
            span = math.dist(a, b)
            c, R = _fit_circle(pts) if (sagitta > 3.0 and span >= 1.5 * self_sw) else (None, None)
            if c is not None and R < 3000.0 and max(abs(math.dist(p, c) - R) for p in pts) < 2.5:
                self.kind = 'circle'; self.c = c; self.R = R
                self.outside = _dot(nB, (pts[0][0] - c[0], pts[0][1] - c[1])) > 0
                return
        # line: all samples if they are collinear, else the sample nearest the junction on each side
        a, b = pts[0], pts[-1]
        lf = _unit((b[0] - a[0], b[1] - a[1])); nf = (-lf[1], lf[0])
        if len(pts) >= 2 and max(abs(_dot((p[0] - a[0], p[1] - a[1]), nf)) for p in pts) > 2.5:
            neg = [s for s in samples if s[1] < 0]; pos = [s for s in samples if s[1] > 0]
            pts = [min(neg, key=lambda s: -s[1])[0]] if neg else []
            pts += [min(pos, key=lambda s: s[1])[0]] if pos else []
        if len(pts) >= 2:
            a, b = pts[0], pts[-1]
            lf = _unit((b[0] - a[0], b[1] - a[1]))
        else:
            a = pts[0]; lf = tB
        nf = (-lf[1], lf[0])
        if _dot(nf, nB) < 0:
            nf = (-nf[0], -nf[1])
        self.p0 = a; self.lf = lf; self.nf = nf

    def dist(self, q):
        """Signed distance from the face: positive on A's side."""
        if self.kind == 'line':
            return _dot((q[0] - self.p0[0], q[1] - self.p0[1]), self.nf)
        d = math.dist(q, self.c) - self.R
        return d if self.outside else -d

    def above(self, d0, D, extent):
        """Polygon of the region on A's side between distance d0 and D from the face."""
        if self.kind == 'line':
            p0, lf, nf = self.p0, self.lf, self.nf
            A0 = (p0[0] - lf[0] * extent, p0[1] - lf[1] * extent); A1 = (p0[0] + lf[0] * extent, p0[1] + lf[1] * extent)
            return Polygon([(A0[0] + nf[0] * d0, A0[1] + nf[1] * d0), (A1[0] + nf[0] * d0, A1[1] + nf[1] * d0),
                            (A1[0] + nf[0] * D, A1[1] + nf[1] * D), (A0[0] + nf[0] * D, A0[1] + nf[1] * D)])
        C = Point(self.c)
        if self.outside:
            return C.buffer(self.R + D, 64).difference(C.buffer(self.R + d0, 64))
        inner = max(self.R - D, 0.0)
        ring = C.buffer(self.R - d0, 64)
        return ring.difference(C.buffer(inner, 64)) if inner > 0 else ring


def measure_face(ink, B_pts, uQ, nB, tB_ref, stroke_w, exclude=None, per_side=3):
    """Face samples of B on A's side on both sides of the junction at uQ: the end of the full ink
    cross-section through the polyline point. Stops on a side where B bends away (corners).
    Returns [(point, signed arc distance)] ordered along the face."""
    totB = poly_length(B_pts)
    out = []
    for sign in (-1, 1):
        got = 0
        for k in (0.8, 1.1, 1.5, 2.0, 2.6, 3.3):
            u = uQ + sign * k * stroke_w
            if u < 0 or u > totB or (exclude is not None and exclude[0] <= u <= exclude[1]):
                break
            Bu, _ = point_at(B_pts, u)
            tBu = tangent_at(B_pts, u, 0.5 * stroke_w)
            if abs(_dot(tBu, tB_ref)) < math.cos(math.radians(50)):
                break                                          # B turns a corner: stop on this side
            q = inside_point(ink, Bu, nB, 0.25 * stroke_w)
            if q is None:
                continue
            cs = cross_section(ink, q, nB, 1.6 * stroke_w)
            if cs and 0.6 * stroke_w <= cs[2] <= 1.5 * stroke_w and math.dist(cs[0], Bu) <= 1.3 * stroke_w:
                out.append((cs[0], sign * k * stroke_w)); got += 1
                if got >= per_side:
                    break
    out.sort(key=lambda s: _dot(s[0], (nB[1], -nB[0])))
    return out


def clean_section(ink, pts, u, stroke_w):
    """Cross-section of A at arc position u: (midpoint, tangent, corner1, corner2) when it is one plain
    stroke wide, else None."""
    pt, _ = point_at(pts, u)
    t = tangent_at(pts, u, 0.6 * stroke_w)
    n = (-t[1], t[0])
    q = inside_point(ink, pt, n, 0.25 * stroke_w)
    if q is None:
        return None
    cs = cross_section(ink, q, n, 1.3 * stroke_w)
    if not cs or not (0.6 * stroke_w <= cs[2] <= 1.5 * stroke_w):
        return None
    c1, c2 = cs[0], cs[1]
    return ((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2), t, c1, c2


def end_cut(ink, regions, A_pts, at_end, B_pts, stroke_w, w, uQ=None, exclude=None, why=None):
    """Gap that shortens stroke A (its END if at_end else its START) flush with the face of B.
    Returns (gap polygon, touched regions, cut point, direction into the junction, removed length) or None."""
    pts = A_pts if at_end else list(reversed(A_pts))      # junction at the end of `pts`
    totA = poly_length(pts)
    P = pts[-1]
    tA = ref_tangent(pts, totA - 1.2 * stroke_w, 1.2 * stroke_w)
    if uQ is None:
        _, uQ, _, _ = nearest_on_polyline(B_pts, P)
    totB = poly_length(B_pts)
    tB = ref_tangent(B_pts, uQ, 2.0 * stroke_w, exclude)
    nB0 = (-tB[1], tB[0])
    nB = nB0 if _dot(nB0, tA) <= 0 else (-nB0[0], -nB0[1])  # B's normal pointing back towards A
    samples = measure_face(ink, B_pts, uQ, nB, tB, stroke_w, exclude)
    if not samples:
        if why is not None: why.append('no face samples')
        return None
    face = Face(samples, nB, tB, stroke_w)
    # march back along A from the junction until a clean cross-section is w clear of B's face
    cut = None; s = 0.0
    while s <= w + 3.0 * stroke_w:
        cs = clean_section(ink, pts, totA - s, stroke_w)
        if cs is not None:
            dmin = min(face.dist(cs[2]), face.dist(cs[3]))
            if dmin >= w:
                cut = cs; break
        s += 2.0
    if cut is None:
        if why is not None: why.append('no cut position (face %s)' % face.kind)
        return None
    pt, t, c1, c2 = cut
    # stub of plain stroke that remains beyond the cut (followed along the polyline)
    stub = 0.0; s2 = s + 3.0
    while s2 <= s + 2.0 * stroke_w and totA - s2 >= 0.0:
        if clean_section(ink, pts, totA - s2, stroke_w) is None:
            break
        stub = s2 - s; s2 += 3.0
    if stub < 0.5 * stroke_w:
        if why is not None: why.append('stub %.0f at s %.0f' % (stub, s))
        return None
    E = 2.0 * stroke_w; D = s + 2.0 * stroke_w
    n = (-t[1], t[0])
    beyond = Polygon([(pt[0] + n[0] * E, pt[1] + n[1] * E), (pt[0] - n[0] * E, pt[1] - n[1] * E),
                      (pt[0] - n[0] * E + t[0] * D, pt[1] - n[1] * E + t[1] * D),
                      (pt[0] + n[0] * E + t[0] * D, pt[1] + n[1] * E + t[1] * D)])
    region = beyond.intersection(face.above(1.5, D + 2.0 * stroke_w, 4.0 * stroke_w))
    pieces = [g for g in _pieces(region.intersection(ink)) if g.geom_type == 'Polygon']
    if not pieces:
        if why is not None: why.append('no pieces')
        return None
    ref = Point(pt[0] + t[0] * 3.0, pt[1] + t[1] * 3.0)
    piece = min(pieces, key=lambda g: g.distance(ref))
    if piece.distance(ref) > 2.0:
        if why is not None: why.append('piece away from ref %.1f' % piece.distance(ref))
        return None
    # the piece must lie along A (not merged with a neighbouring stroke)
    tail = pts[max(0, len(pts) - 40):]
    ext = [(pt[0] + t[0] * (s + 2.0 * stroke_w), pt[1] + t[1] * (s + 2.0 * stroke_w))]
    corridor = LineString([pt] + ext).buffer(0.8 * stroke_w + 2.0).union(LineString(tail).buffer(0.8 * stroke_w + 2.0))
    if piece.difference(corridor).area > 0.3 * piece.area:
        if why is not None: why.append('outside corridor %.0f%%' % (100 * piece.difference(corridor).area / piece.area))
        return None
    gap = piece.buffer(2.0, join_style=2)                      # 1.5 inward margin + 0.5 bite into B
    touched = [rid for rid, reg in regions.items() if reg.intersects(gap.buffer(0.5))]
    if len(touched) != 2:
        if why is not None: why.append('touched %d regions' % len(touched))
        return None
    return gap, touched, pt, t, s


def junction_of(strokes, si, P, exclude_self):
    """Nearest stroke to endpoint P: (sj, u, tot, d). Own stroke counts only outside `exclude_self`."""
    best = None
    for sj, s in enumerate(strokes):
        pts = s['pts']
        if sj == si:
            cand = None; acc = 0.0
            for i in range(len(pts) - 1):
                seg = math.dist(pts[i], pts[i + 1])
                if not (acc + seg < exclude_self[0] or acc > exclude_self[1]):
                    acc += seg; continue
                dd, uu, _, _ = nearest_on_polyline([pts[i], pts[i + 1]], P)
                if cand is None or dd < cand[0]:
                    cand = (dd, acc + uu)
                acc += seg
            if cand is None:
                continue
            d, u = cand; tot = acc
        else:
            d, u, _, tot = nearest_on_polyline(pts, P)
        if best is None or d < best[3]:
            best = (sj, u, tot, d)
    return best


def junction_candidates(ink, regions, strokes, stroke_w, w, prefer_later=False, junction_tol=1.5):
    cands = []
    for si, s in enumerate(strokes):
        pts = s['pts']; tot = poly_length(pts)
        if len(pts) < 2 or tot < 0.5 * stroke_w:
            continue
        for kind in ('END', 'START'):
            if kind == 'END':
                P = pts[-1]; excl = (max(0.0, tot - 2.5 * stroke_w), tot + 1.0)
            else:
                P = pts[0]; excl = (-1.0, min(tot, 2.5 * stroke_w))
            j = junction_of(strokes, si, P, excl)
            if j is None or j[3] > junction_tol * stroke_w:
                continue
            sj, u, totj, d = j
            meet = 'THROUGH' if sj == si else ('START' if u < 1.0 * stroke_w else ('END' if totj - u < 1.0 * stroke_w else 'THROUGH'))
            r = end_cut(ink, regions, pts, kind == 'END', strokes[sj]['pts'], stroke_w, w, uQ=u,
                        exclude=excl if sj == si else None)
            if r is None:
                continue
            gap, touched, pt, t, removed = r
            base = COST[(kind, meet)]
            tie = min(0.01 * si, 0.05) if prefer_later else min(0.004 * si, 0.03)
            if kind == 'START' or prefer_later:
                tie = -tie
            c = Cand(touched[0], touched[1], pt, pt, t, w, gap, base + tie, 's%d:%s>s%d:%s' % (si + 1, kind, sj + 1, meet))
            c.stroke = si; c.removed = removed
            cands.append(c)
    return cands


def crossings(strokes, stroke_w):
    """(si, ui, sj, uj, X) for every crossing between stroke polylines (self crossings included)."""
    out = []; segs = []
    for si, s in enumerate(strokes):
        pts = s['pts']; acc = 0.0
        for i in range(len(pts) - 1):
            segs.append((si, acc, pts[i], pts[i + 1])); acc += math.dist(pts[i], pts[i + 1])
    for a in range(len(segs)):
        for b in range(a + 1, len(segs)):
            si, ua, p1, p2 = segs[a]; sj, ub, q1, q2 = segs[b]
            if si == sj and abs(ua - ub) < 2.0 * stroke_w:
                continue
            d = (p2[0] - p1[0]) * (q2[1] - q1[1]) - (p2[1] - p1[1]) * (q2[0] - q1[0])
            if abs(d) < 1e-9:
                continue
            t = ((q1[0] - p1[0]) * (q2[1] - q1[1]) - (q1[1] - p1[1]) * (q2[0] - q1[0])) / d
            v = ((q1[0] - p1[0]) * (p2[1] - p1[1]) - (q1[1] - p1[1]) * (p2[0] - p1[0])) / d
            if 0.0 <= t <= 1.0 and 0.0 <= v <= 1.0:
                X = (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))
                out.append((si, ua + t * math.dist(p1, p2), sj, ub + v * math.dist(q1, q2), X))
    return out


def _arm(pts, u, sign):
    """Polyline of the arm of `pts` starting at arc position u and running towards the end (sign>0) or start."""
    X, _ = point_at(pts, u)
    acc = 0.0; out = [X]
    if sign > 0:
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1])
            if acc + seg > u + 1e-6:
                out.append(pts[i + 1])
            acc += seg
    else:
        idx = []
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1])
            if acc < u - 1e-6:
                idx.append(i)
            acc += seg
        out += [pts[i] for i in reversed(idx)]
    return out


def crossing_candidates(ink, regions, strokes, stroke_w, w):
    cands = []
    for si, ui, sj, uj, X in crossings(strokes, stroke_w):
        for (sa, ua, sb, ub) in ((si, ui, sj, uj), (sj, uj, si, ui)):
            A = strokes[sa]['pts']; totA = poly_length(A)
            for sign in (-1, 1):
                arm_len = totA - ua if sign > 0 else ua
                if arm_len < w + stroke_w:
                    continue
                arm = _arm(A, ua, sign)
                if len(arm) < 2:
                    continue
                excl = (ua - 2.0 * stroke_w, ua + 2.0 * stroke_w) if sa == sb else None
                r = end_cut(ink, regions, arm, False, strokes[sb]['pts'], stroke_w, w, uQ=ub, exclude=excl)
                if r is None:
                    continue
                gap, touched, pt, t, removed = r
                c = Cand(touched[0], touched[1], pt, pt, t, w, gap, 1.0 + 0.02 * arm_len / stroke_w,
                         's%d:x%s>s%d' % (sa + 1, '+' if sign > 0 else '-', sb + 1))
                c.stroke = sa; c.removed = removed
                cands.append(c)
    return cands


def _ink_rings(ink):
    polys = ink.geoms if hasattr(ink, 'geoms') else [ink]
    rings = []
    for pg in polys:
        rings.append(pg.exterior); rings.extend(pg.interiors)
    return rings


def face_direction(rings, pt, h=4.0):
    """Unit direction of the ink boundary nearest to pt (chord over +-h units)."""
    P = Point(pt)
    ring = min(rings, key=lambda r: r.distance(P))
    u = ring.project(P); L = ring.length
    a = ring.interpolate((u - h) % L); b = ring.interpolate((u + h) % L)
    return _unit((b.x - a.x, b.y - a.y))


def square_crossing(rings, c, tol_deg):
    """True when the two faces crossed by candidate c are parallel and the crossing is square to them."""
    da = face_direction(rings, c.a); db = face_direction(rings, c.b)
    cos_t = math.cos(math.radians(tol_deg))
    return abs(_dot(da, db)) >= cos_t and abs(_dot(da, c.n)) <= math.sin(math.radians(tol_deg))


def adaptive_rect(ink, c, e_long=30.0):
    """Replace a ring-sampled rectangle by one whose ends follow the wall's faces."""
    w = c.rect.area / (c.L + 10.0)                               # area = (L + 2e) * w with e = 5
    long = make_rect(c.a, c.n, c.L, max(w - 2.0, 4.0), e_long)
    mid = Point((c.a[0] + c.b[0]) / 2, (c.a[1] + c.b[1]) / 2)
    pieces = [g for g in _pieces(long.intersection(ink)) if g.geom_type == 'Polygon']
    if not pieces:
        return c.rect
    piece = min(pieces, key=lambda g: g.distance(mid))
    return piece.buffer(1.0, join_style=2)


def select_bands(cands, regions, ext_id, w, uf=None, chosen=None, min_gap=1.5):
    """Kruskal; the spacing rule applies between cuts of the same stroke only (plus a 12-unit no-touch
    rule). A cut on a stroke that already has a cut (its other end) is deferred by +0.1, so a bar is not
    detached at both ends when a cut of nearly the same cost exists elsewhere."""
    import heapq
    uf = uf or UnionFind(regions.keys())
    chosen = chosen if chosen is not None else []
    heap = [(c.cost, k) for k, c in enumerate(cands)]
    heapq.heapify(heap)
    deferred = set()
    while heap:
        cost, k = heapq.heappop(heap)
        c = cands[k]
        a, b = uf.find(c.r1), uf.find(c.r2)
        if a == b:
            continue
        bad = False
        for o in chosen:
            d = c.rect.distance(o.rect)
            if d < 12.0 or (getattr(c, 'stroke', -1) >= 0 and c.stroke == getattr(o, 'stroke', -2) and d < min_gap * w):
                bad = True; break
        if bad:
            continue
        st = getattr(c, 'stroke', -1)
        if st >= 0 and k not in deferred and any(getattr(o, 'stroke', -2) == st for o in chosen):
            deferred.add(k); heapq.heappush(heap, (cost + 0.1, k)); continue
        uf.union(a, b)
        chosen.append(c)
    unconnected = [rid for rid in regions if rid != ext_id and uf.find(rid) != uf.find(ext_id)]
    return chosen, unconnected


def plain_run_middle(regions, cands, max_gap=14.0):
    """For each hole, the candidate in the middle of the longest run of consecutive ring-sampled slots
    (all square to parallel faces): the plain part of a bowl, away from where it flows into a stem.
    A ring that is plain all the way round (o, 0) returns nothing for that hole."""
    out = []
    by = {}
    for c in cands:
        by.setdefault(c.r1, []).append(c)
    for rid, cs in by.items():
        ring = regions[rid].exterior; L = ring.length
        items = sorted(((ring.project(Point(c.a)), c) for c in cs), key=lambda x: x[0])
        if len(items) < 3:
            continue
        gaps = [(items[(k + 1) % len(items)][0] - items[k][0]) % L for k in range(len(items))]
        breaks = [k for k, g in enumerate(gaps) if g > max_gap]
        if not breaks:
            continue                                   # plain all round
        best = None
        for bi, k in enumerate(breaks):
            start = (k + 1) % len(items); end = breaks[(bi + 1) % len(breaks)]
            cnt = (end - start) % len(items) + 1
            if best is None or cnt > best[0]:
                best = (cnt, start)
        cnt, start = best
        out.append(items[(start + cnt // 2) % len(items)][1])
    return out


FALLBACK_PENALTY = 1.5          # ring-sampled cuts come after every junction-based candidate
LAST_FILLED = 0                 # counters filled in the last stencil_glyph2 call (for the survey tools)


def stencil_glyph2(path, strokes, stroke_w=67.0, w=60.0, prefer_later=False, snap=True, lmax_factor=1.7,
                   clear=10.0, min_gap=1.5, fill_min=0.0):
    from .bridges import fill_pinholes
    if not list(path.contours):
        return Result(path, [], [], 0, 0, strokes, 0)
    ink = ink_polygons(path)
    regions, ext = material_regions(ink)
    if fill_min > 0:
        path, n_filled = fill_pinholes(path, regions, ext, fill_min)
        if n_filled:
            ink = ink_polygons(path); regions, ext = material_regions(ink)
    n_holes = len(regions) - 1
    if n_holes == 0:
        return Result(path, [], [], 0, 0, strokes, 0)
    if strokes and snap:
        from .kanjivg import snap as _snap
        for st in strokes:
            st['pts0'] = st['pts']                  # aligned polyline: reliable directions
        strokes = _snap(strokes, ink, stroke_w)
    uf = UnionFind(regions.keys()); chosen = []
    cands = []
    from .corners import corner_candidates
    cands = corner_candidates(ink, regions, ext, strokes, stroke_w, w, prefer_later=prefer_later)
    # a counter narrower than the smallest gap (0.5 w) that no junction cut can open is filled: forcing
    # a slot into it mangles the strokes around it (驚: a 26 x 33 cell), and an island that small cannot
    # be kept on a stencil anyway
    global LAST_FILLED
    LAST_FILLED = 0
    tiny = [rid for rid, reg in regions.items() if rid != ext
            and min(reg.bounds[2] - reg.bounds[0], reg.bounds[3] - reg.bounds[1]) < 0.5 * w
            and not any(rid in (c.r1, c.r2) for c in cands)]
    from .corners import OPTS as _COPTS
    if _COPTS.get('fill'):
        # study option: a room narrower than fill * w that no stroke-end cut can open (only slots or
        # crossing cuts, cost >= 1) is filled as well
        for rid, reg in regions.items():
            if rid == ext or rid in tiny:
                continue
            if min(reg.bounds[2] - reg.bounds[0], reg.bounds[3] - reg.bounds[1]) < _COPTS['fill'] * w \
                    and all(c.cost >= 1.0 for c in cands if rid in (c.r1, c.r2)):
                tiny.append(rid)
    if tiny:
        import pathops
        from .bridges import rect_path
        cur = pathops.Path(path)
        for rid in tiny:
            cur = pathops.op(cur, rect_path(regions[rid].buffer(0.5, 1)), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False)
        cur.simplify(fix_winding=True, keep_starting_points=False)
        path = cur; LAST_FILLED = len(tiny)
        ink = ink_polygons(path); regions, ext = material_regions(ink)
        uf = UnionFind(regions.keys()); chosen = []
        if len(regions) - 1 == 0:
            return Result(path, [], [], n_holes, 0, strokes, 0)
        cands = corner_candidates(ink, regions, ext, strokes, stroke_w, w, prefer_later=prefer_later)
    chosen, unconnected = select_bands(cands, regions, ext, w, uf, chosen, min_gap=min_gap)
    n_cands = len(cands)
    # fallback: ring-sampled cuts with face-following ends, progressively relaxed (as before)
    rings = _ink_rings(ink)
    for gap, lmax, wf, sf, cl, par in ((1.5, lmax_factor * stroke_w, 1.0, 1.0, clear, 8.0), (1.5, lmax_factor * stroke_w, 1.0, 1.0, clear, 15.0),
                                       (1.5, lmax_factor * stroke_w, 1.0, 1.0, clear, None), (0.8, None, 1.0, 1.0, clear, None),
                                       (0.5, 3.2 * stroke_w, 1.0, 1.0, clear, None), (0.4, 3.2 * stroke_w, 0.7, 1.0, clear, None),
                                       (0.3, 4.0 * stroke_w, 0.55, 1.0, clear, None), (0.3, 4.0 * stroke_w, 0.5, 0.5, 6.0, None),
                                       (0.3, 4.0 * stroke_w, 0.4, 0.5, 5.0, None), (0.3, 4.0 * stroke_w, 0.3, 0.5, 4.0, None),
                                       (0.0, 4.0 * stroke_w, 0.4, 0.5, 4.0, None)):
        if not unconnected:
            break
        more = gen_candidates(ink, regions, ext, stroke_w * sf, w * wf, Lmax=lmax, clear=cl)
        more = [c for c in more if uf.find(c.r1) != uf.find(c.r2)]
        if par is not None:
            # smooth junctions (a bowl flowing into a stem): only slots square to parallel faces, so the
            # opening is the same width on both faces
            more = [c for c in more if square_crossing(rings, c, par)]
        score_candidates(more, strokes, stroke_w * sf, w * wf, prefer_later=prefer_later)
        for c in more:
            c.cost += FALLBACK_PENALTY
            c.rect = adaptive_rect(ink, c)
            c.stroke = -1
        # a slot that leaves a pointed end or a fin beside it: not while there is a choice, and last
        # among the candidates of the relaxed stages (tiny cells, where nothing else fits)
        from .corners import thin_remnant, THIN_MAX
        for c in more:
            c.thin = thin_remnant(ink, c.rect)
        if par is not None or gap >= 0.8:
            more = [c for c in more if c.thin <= THIN_MAX]
        else:
            for c in more:
                c.cost += min(c.thin, 400.0) / 400.0
        if prefer_later and par is not None and par <= 8.0:
            # Latin bowls (b d p q g a): one slot in the middle of the plain part of the ring, away from
            # the places where the bowl flows into the stem
            for c in plain_run_middle(regions, more):
                c.cost = FALLBACK_PENALTY - 0.3
        n_cands += len(more)
        chosen, unconnected = select_bands(more, regions, ext, w * wf, uf, chosen, min_gap=gap)
    joins = []
    for i, c1 in enumerate(chosen):
        for c2 in chosen[i + 1:]:
            d = c1.rect.distance(c2.rect)
            if 0.0 < d < 12.0:
                joins.append(Cand(c1.r1, c2.r1, c1.a, c1.b, c1.n, c1.L, c1.rect.union(c2.rect).convex_hull, 0.0, 'join'))
    cut = apply_cuts(path, chosen + joins)
    from .weld import desliver, weld_guarded, trim_remnants, trim_leaves
    rects = [c.rect for c in chosen + joins]
    cut, _ntrim = trim_remnants(cut, rects, keep_tips=True)
    cut, _nleaf = trim_leaves(cut, rects); _ntrim += _nleaf
    cut, _nfix = desliver(cut, rects=rects)
    cut, _nw = weld_guarded(cut, rects=rects)
    if _nw:
        cut, _n2 = desliver(cut, rects=rects); cut, _n3 = trim_leaves(cut, rects); _ntrim += _n2 + _n3
    ink2 = ink_polygons(cut)
    regions2, ext2 = material_regions(ink2)
    return Result(cut, chosen + joins, unconnected, n_holes, len(regions2) - 1, strokes, n_cands, _ntrim)
