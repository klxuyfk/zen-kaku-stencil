"""Corner-based end cuts (prototype, 2026-11-03).

Every junction that borders a counter shows up on the counter's outline as a corner: the outline runs
along the face of one stroke, turns, and runs along the face of the other. A cusp (a curl merging
tangentially into its own body, る) is a 180-degree corner. The cut is built from that outline alone:

  A = the stroke to shorten (the face before the corner, or after: both assignments are candidates)
  B = the stroke it meets (the other face)
  - B's face is fitted (line, or circle when clearly curved) through outline points after the corner and
    extended across the junction; it is never carved (bite 0.5 unit).
  - Walking back along A's face from the corner, the first cross-section of A that is one plain stroke wide
    and whose both ends are at least w away from B's face is the cut: A is cut square there, and all of
    A's ink between the cut and B's face is removed. The gap is therefore w or wider everywhere, its sides
    are A's own faces, and nothing thin is left behind.
  - A candidate is dropped when less than half a stroke width of A would remain.
KanjiVG strokes are used only to classify the corner (which stroke ends there: END/START cut, what it
meets) for the stroke-order cost table; their geometry is too unreliable near junctions to build shapes.
A corner with no stroke end is a crossing (mid cut, cost 1.0); there the more curved face is preferred as
the stroke to cut (a loop returning to a stem is cut, the stem is kept).
"""
import math
from shapely.geometry import Polygon, LineString, Point
from shapely.geometry.polygon import orient
from .bridges import Cand, COST, nearest_on_polyline
from .junction import (_unit, _dot, _pieces, face_point, cross_section, Face, poly_length, point_at, tangent_at)
import pathops

# options of the dense-kanji study (2026-11-07); the defaults reproduce the behaviour before it
OPTS = {'scale': False,     # the bridge follows the glyph's stroke width: w * min(1, m / (FULL_WIDTH stroke_w)), floor 0.5 w,
                            # m = median cross-section of the glyph's ink (日 国 は: 60-62 for the nominal 67)
        'oblique': 0.0,     # slots square to A beside an oblique B: cost += oblique * (|cos(A, B's face)| - 0.17)
        'fill': 0.0,        # fill rooms with a short side under fill * w that only slots or crossing cuts can open
        'cap': False,       # a stroke that ends under the start of another ends with a cap square to its axis
        'tip': False,       # ... True: with a cap square to its own axis through the top of its foot, both corners
                            # right angles (12th round); 'edge': along its visible end edge, extended across it
                            # (the reviewer's 11th-round sketch; its tip stays pointed)
        'dot': False,       # a dot (㇔) that ends on the end of another stroke (the vertex of マ) is shortened at
                            # its start instead; the vertex stays and the dot may be left shorter than a stroke width
        'axis': 0.0,        # cost added to every cut of a stroke that runs more than 20 degrees off the horizontal
                            # and the vertical at the cut (13th round: sweeps stay whole, the bars they meet are
                            # shortened; 権 鷹). 0.35 puts such a cut after the start cut of a bar (0.30)
        'kinkface': False,  # at a kinked junction (2.12) whose third stroke's face is upright or level within 20
                            # degrees, A's hidden face follows that face instead of the chord (番 魚: the bar
                            # starts square after the upright, not along a slanted line to its corner)
        'root': False,      # a stroke that runs into the root of a hane (the lowest bar of 龍 into its 乚, 襲):
                            # the hane is capped by the straight face from the corner where its upper edge
                            # begins, resting on the inside of its bend; the bar is cut square (15th round)
        'bend': 0.0,        # cost added to an end cut that parts one KanjiVG stroke at its own bend (the tail of
                            # ㇇ cut off the bar it turns from: 憂 履 鷺, 16th round); with it the falling part
                            # of a ㇇ counts as a sweep for `axis`
        'fin': False,       # A's own end face is exposed beyond the corner where its far face meets B (the 提 of
                            # 艮 in 眼 touches the leg with one corner only): the end of A beside B goes with
                            # the gap instead of staying on B as a fin (16th round)
        'band': False,      # the gap of a straight A stays within A's own band (its width at the cut + 3 units a
                            # side): ink of another stroke that touches A beside the junction is not carried off
                            # with it (蘿: the tip of 糸 under the bar of 罒; 蹙: the root of a side bar)
        'orphan': 0.5,      # cost added to a cut that detaches a piece of ink (16th round: 1.0, after the slots)
        'flat': False,      # the hidden face is a straight chord between the two real corners unless B is one
                            # smooth arc under A (both ends leave the chord to the same side by like amounts):
                            # an S-shaped or lopsided cubic showed as a wobble on the met stroke (16th round)
        'heal': 0.0}        # outline.finalize removes the new pieces shorter than this many units that a cut leaves
                            # beside its edges (steps, remainders of original segments, needles; 18th round: 12)

_SW_CACHE = {'key': None, 'm': None}
_CTX = {'kanji': True}      # set per glyph by corner_candidates: KanjiVG strokes with types (kanji, not kana or Latin)
_R16 = {'flat': False, 'band': False, 'fin': False, 'bend': 0.0, 'orphan': 0.5}


def _o(name):
    """A 16th-round option: as set for kanji, the old behaviour for kana and Latin (their loops and bowls
    were reviewed and accepted as they are; the new rules moved 24 kana)."""
    return OPTS[name] if _CTX['kanji'] else _R16[name]


def glyph_stroke_width(ink, stroke_w, step=6.0):
    """Median width of the ink measured square to the outline every 12 units (cached per glyph). Dense
    kanji are drawn with thinner strokes (鬱 47, 轟 40) than ordinary ones (日 62, 国 60)."""
    if _SW_CACHE['key'] is ink:
        return _SW_CACHE['m']
    ws = []
    for g in _pieces(ink):
        if g.geom_type != 'Polygon':
            continue
        for ring in [g.exterior] + list(g.interiors):
            pts = resample(list(ring.coords)[:-1], step); n = len(pts)
            if n < 8:
                continue
            for i in range(0, n, 2):
                a, b = pts[(i - 2) % n], pts[(i + 2) % n]
                t = _unit((b[0] - a[0], b[1] - a[1]))
                for nin in ((t[1], -t[0]), (-t[1], t[0])):
                    q = (pts[i][0] + nin[0] * 0.6, pts[i][1] + nin[1] * 0.6)
                    if ink.contains(Point(q)):
                        r = face_point(ink, q, nin, 1.5 * stroke_w)
                        if r is not None and 0.3 * stroke_w <= r[1] + 0.6 <= 1.5 * stroke_w:
                            ws.append(r[1] + 0.6)
                        break
    ws.sort()
    m = ws[len(ws) // 2] if ws else stroke_w
    _SW_CACHE['key'] = ink; _SW_CACHE['m'] = m
    return m


FULL_WIDTH = 0.83      # measured median of a glyph drawn at the nominal stroke width (日 62 国 60 東 56 for 67)


def bridge_width(ink, stroke_w, w):
    """The bridge width aimed at in this glyph: w, or (OPTS scale) w reduced in the ratio of the glyph's
    stroke width to that of an ordinary glyph (FULL_WIDTH * stroke_w), never under 0.5 w."""
    if not OPTS['scale']:
        return w
    m = glyph_stroke_width(ink, stroke_w)
    return max(0.5 * w, min(w, w * m / (FULL_WIDTH * stroke_w)))


def set_opts(spec):
    """'scale,oblique=1.0,fill=1.0,tip=edge' -> OPTS (a bare name sets True; a non-numeric value stays a string)."""
    for item in (spec or '').split(','):
        item = item.strip()
        if not item:
            continue
        k, _, v = item.partition('=')
        if not v:
            OPTS[k] = True
        else:
            try:
                OPTS[k] = float(v)
            except ValueError:
                OPTS[k] = v


# the batch tools (batch.py, lint.py, build_font.py, audit_font.py) take the options from the environment, so that
# their worker processes get them as well
set_opts(__import__('os').environ.get('STENCIL_OPTS', ''))


def resample(coords, step):
    """Closed ring resampled every `step` units; returns list of points."""
    out = []; n = len(coords); carry = 0.0
    for i in range(n):
        p = coords[i]; q = coords[(i + 1) % n]
        seg = math.dist(p, q)
        if seg < 1e-9:
            continue
        t = ((q[0] - p[0]) / seg, (q[1] - p[1]) / seg); pos = carry
        while pos < seg:
            out.append((p[0] + t[0] * pos, p[1] + t[1] * pos)); pos += step
        carry = pos - seg
    return out


def _turns(pts, k):
    n = len(pts); out = []
    for i in range(n):
        a = pts[(i - k) % n]; b = pts[i]; c = pts[(i + k) % n]
        d1 = _unit((b[0] - a[0], b[1] - a[1])); d2 = _unit((c[0] - b[0], c[1] - b[1]))
        out.append(math.degrees(math.acos(max(-1.0, min(1.0, _dot(d1, d2))))))
    return out


def ring_corners(pts, step, min_turn=35.0, k=4, k2=12, min_turn2=55.0):
    """Indices of corners of a resampled ring: sharp corners (turning over +-k samples >= min_turn) and
    rounded junctions (turning over +-k2 samples >= min_turn2, e.g. a bowl merging into a stem with a
    fillet). Returns (indices, sharp turns, rounded flags)."""
    n = len(pts)
    t1 = _turns(pts, k); t2 = _turns(pts, k2)
    corners = []
    for i in range(n):
        if t1[i] >= min_turn and all(t1[i] >= t1[(i + j) % n] for j in range(-k, k + 1) if j != 0):
            corners.append((i, False))
    for i in range(n):
        if t2[i] >= min_turn2 and all(t2[i] >= t2[(i + j) % n] for j in range(-k2, k2 + 1) if j != 0):
            if not any(abs((i - c) % n) <= k2 or abs((c - i) % n) <= k2 for c, _ in corners):
                corners.append((i, True))
    corners.sort()
    out = []; rounded = {}
    for i, r in corners:
        if not out or (i - out[-1]) % n > k:
            out.append(i); rounded[i] = r
    return out, t1, rounded


def ring_dir(pts, i, span, forward=True):
    """Unit direction of the ring at index i over `span` samples ahead (forward) or behind."""
    n = len(pts)
    if forward:
        a, b = pts[i], pts[(i + span) % n]
    else:
        a, b = pts[(i - span) % n], pts[i]
    return _unit((b[0] - a[0], b[1] - a[1]))


def face_curvature(pts, i, span, forward):
    """Turning (degrees) of the ring over `span` samples leaving the corner i."""
    n = len(pts)
    k0 = min(6, max(2, span // 3))                 # start clear of the rounding of the corner itself
    if forward:
        d1 = ring_dir(pts, (i + k0) % n, 4, True); d2 = ring_dir(pts, (i + span) % n, 4, True)
    else:
        d1 = ring_dir(pts, (i - k0) % n, 4, False); d2 = ring_dir(pts, (i - span) % n, 4, False)
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(d1, d2)))))


def face_samples_beyond(ink, corner, lf, nf, L_A, stroke_w, span=2.0, every=4.0):
    """Real face points of B on the far side of A (beyond A's width along -lf), found by projecting
    from the air just above B's fitted face onto the ink boundary. Returns points ordered from the
    nearest to the farthest."""
    out = []
    bnd = ink.boundary
    d = 0.0
    while d <= span * stroke_w:
        u = -(L_A + 0.15 * stroke_w + d)
        q = (corner[0] + lf[0] * u + nf[0] * 12.0, corner[1] + lf[1] * u + nf[1] * 12.0)
        if not ink.contains(Point(q)):
            seg = LineString([q, (q[0] - nf[0] * 40.0, q[1] - nf[1] * 40.0)])
            inter = seg.intersection(bnd)
            hits = [g for g in _pieces(inter) if g.geom_type == 'Point']
            if hits:
                h = min(hits, key=lambda g: g.distance(Point(q)))
                if 4.0 <= h.distance(Point(q)) <= 30.0:
                    out.append((h.x, h.y))
        d += every
    return out


def _bez(P0, P1, P2, P3, t):
    mt = 1.0 - t
    return (mt ** 3 * P0[0] + 3 * mt * mt * t * P1[0] + 3 * mt * t * t * P2[0] + t ** 3 * P3[0],
            mt ** 3 * P0[1] + 3 * mt * mt * t * P1[1] + 3 * mt * t * t * P2[1] + t ** 3 * P3[1])


def hermite_face(P3, T3, P0, T0, nf, H, ext, bite=0.5):
    """Lower edge of the removal region as a tangent-continuous cubic from P3 (real face beyond A) to
    P0 (the corner, real face on the near side), with the two inner control points pushed `bite`
    into B so the curve never leaves a hair of A on B's face and meets the real outline at the ends
    without a step. Straight tangent extensions of `ext` units at both ends. Returns (pathops path,
    shapely polygon) of the region above that edge up to height H."""
    d = math.dist(P0, P3)
    C1 = (P3[0] + T3[0] * d / 3 - nf[0] * bite / 0.75, P3[1] + T3[1] * d / 3 - nf[1] * bite / 0.75)
    C2 = (P0[0] - T0[0] * d / 3 - nf[0] * bite / 0.75, P0[1] - T0[1] * d / 3 - nf[1] * bite / 0.75)
    A = (P3[0] - T3[0] * ext, P3[1] - T3[1] * ext); B = (P0[0] + T0[0] * ext, P0[1] + T0[1] * ext)
    Bt = (B[0] + nf[0] * H, B[1] + nf[1] * H); At = (A[0] + nf[0] * H, A[1] + nf[1] * H)
    path = pathops.Path(); pen = path.getPen()
    pen.moveTo(A); pen.lineTo(P3); pen.curveTo(C1, C2, P0); pen.lineTo(B); pen.lineTo(Bt); pen.lineTo(At); pen.closePath()
    flat = [A, P3] + [_bez(P3, C1, C2, P0, k / 24.0) for k in range(1, 24)] + [P0, B, Bt, At]
    poly = Polygon(flat)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return path, poly


def above_region(P3, T3, P0, T0, nf, H, straight, bite=0.5, far_pts=(), near_pts=(), wide_far=0.0, wide_near=0.0,
                 chord=False, nf_far=None, up=None, via=()):
    """Removal region above B's face between P3 and P0 (real outline points on either side of A).
    straight face: the edge is the straight segment P3-P0 itself, so B's face stays one straight line.
    curved face: a tangent-continuous cubic with the inner control points pushed `bite` into B.
    Beyond the end points the edge leaves the face at a shallow angle (0.3 unit up over 20 units), so
    it never runs along the outline. Returns (pathops path, shapely polygon)."""
    # just beyond the end points the edge follows the real outline 0.3 unit outside it (a curved face
    # would otherwise be clipped by a straight extension); further out it only has to stay in the air
    # chord=True: the face A ends on changes direction under A (a third stroke shares the junction);
    # the two corners are joined by a straight line and each side follows its own real outline, with
    # its own outward normal (nf_far on the far side)
    nl = nf_far if nf_far is not None else nf
    off = lambda q: (q[0] + nf[0] * 0.3, q[1] + nf[1] * 0.3)
    offl = lambda q: (q[0] + nl[0] * 0.3, q[1] + nl[1] * 0.3)
    left = [offl(q) for q in far_pts]; right = [off(q) for q in near_pts]
    a0 = left[0] if left else P3; b0 = right[-1] if right else P0
    A = (a0[0] - T3[0] * 20.0 + nl[0] * 0.6, a0[1] - T3[1] * 20.0 + nl[1] * 0.6)
    B = (b0[0] + T0[0] * 20.0 + nf[0] * 0.6, b0[1] + T0[1] * 20.0 + nf[1] * 0.6)
    # sideways beyond that (only where a wing keeps the region off B's face): out to A's corridor
    A2 = (A[0] - T3[0] * wide_far + nl[0] * 0.2, A[1] - T3[1] * wide_far + nl[1] * 0.2)
    B2 = (B[0] + T0[0] * wide_near + nf[0] * 0.2, B[1] + T0[1] * wide_near + nf[1] * 0.2)
    ud = up if up is not None else nf                      # along A, away from the junction
    At = (A2[0] + ud[0] * H, A2[1] + ud[1] * H); Bt = (B2[0] + ud[0] * H, B2[1] + ud[1] * H)
    path = pathops.Path(); pen = path.getPen()
    pen.moveTo(A2 if wide_far else A)
    if wide_far:
        pen.lineTo(A)
    for q in left:
        pen.lineTo(q)
    pen.lineTo(P3)
    if straight or chord:
        for q in via:                                        # chord with a corner (kinkface): P3 -> via -> P0
            pen.lineTo(q)
        pen.lineTo(P0)
        mid_pts = list(via)
    else:
        d = math.dist(P0, P3)
        C1 = (P3[0] + T3[0] * d / 3 - nf[0] * bite / 0.75, P3[1] + T3[1] * d / 3 - nf[1] * bite / 0.75)
        C2 = (P0[0] - T0[0] * d / 3 - nf[0] * bite / 0.75, P0[1] - T0[1] * d / 3 - nf[1] * bite / 0.75)
        pen.curveTo(C1, C2, P0)
        mid_pts = [_bez(P3, C1, C2, P0, k / 24.0) for k in range(1, 24)]
    for q in right:
        pen.lineTo(q)
    pen.lineTo(B)
    if wide_near:
        pen.lineTo(B2)
    pen.lineTo(Bt); pen.lineTo(At); pen.closePath()
    poly = Polygon(([A2] if wide_far else []) + [A] + left + [P3] + mid_pts + [P0] + right + [B] + ([B2] if wide_near else []) + [Bt, At])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return path, poly


def poly_path(poly):
    path = pathops.Path(); pen = path.getPen()
    rings = [poly.exterior] + list(poly.interiors)
    for ring in rings:
        pts = list(ring.coords)[:-1]
        pen.moveTo(pts[0])
        for q in pts[1:]:
            pen.lineTo(q)
        pen.closePath()
    return path


def ray_face(ink, corner, lf, nf, u, h=6.0, reach=20.0):
    """Real face point of B at position u along the face: projected from h units above the fitted
    face onto the ink boundary. None when the start is inside the ink or nothing is hit nearby."""
    q = (corner[0] + lf[0] * u + nf[0] * h, corner[1] + lf[1] * u + nf[1] * h)
    if ink.contains(Point(q)):
        return None
    seg = LineString([q, (q[0] - nf[0] * reach, q[1] - nf[1] * reach)])
    hits = [g for g in _pieces(seg.intersection(ink.boundary)) if g.geom_type == 'Point']
    if not hits:
        return None
    hpt = min(hits, key=lambda g: g.distance(Point(q)))
    d = hpt.distance(Point(q))
    return (hpt.x, hpt.y) if 0.5 <= d <= reach - 2.0 else None


def footprint_end(ink, corner, lf, nf, L_A):
    """Position u (< 0) along B's face where A's ink ends on the far side: the first air point 3 units
    above the face after A's ink. A that meets B obliquely covers more of the face than its width."""
    u = -2.0; seen_ink = False
    while u >= -(3.0 * L_A + 40.0):
        q = Point(corner[0] + lf[0] * u + nf[0] * 3.0, corner[1] + lf[1] * u + nf[1] * 3.0)
        inside = ink.contains(q)
        if inside:
            seen_ink = True
        elif seen_ink:
            return u
        u -= 2.0
    return None


_RING_CACHE = {'key': None, 'rings': {}}
KINK_LOG = None           # a list: every chord-form decision appends its measurements (inspection scripts)
FLAT_LOG = None           # a list: (corner, a_before, far angle, near angle, chord?) of every hidden-face decision
import os as _os
_DBG_AT = tuple(float(v) for v in _os.environ['CORNERS_DEBUG'].split(',')) if _os.environ.get('CORNERS_DEBUG') else None
_NO_KINK = bool(_os.environ.get('CORNERS_NO_KINK'))      # comparison renders only: leave out the chord cuts


def _dbg(corner, *a):
    if _DBG_AT is not None and math.dist(corner, _DBG_AT) <= 6.0:
        print('   [dbg]', *a)


def _region_rings(regions, rid, step):
    """Resampled rings (with their corners) of a material region; cached per glyph."""
    if _RING_CACHE['key'] is not regions:          # the object itself: an id() can be reused by the next glyph
        _RING_CACHE['key'] = regions; _RING_CACHE['rings'] = {}
    if rid not in _RING_CACHE['rings']:
        reg = regions[rid]; out = []
        for ring in [reg.exterior] + list(reg.interiors):
            rp = resample(list(ring.coords)[:-1], step)
            if len(rp) >= 12:
                cs, _, _ = ring_corners(rp, step)
                out.append((rp, cs))
        _RING_CACHE['rings'][rid] = out
    return _RING_CACHE['rings'][rid]


def far_ring(regions, c1, c2, t, step):
    """Outline of the region on A's far side at the far end c2 of the cut section:
    (ring points, set of corner indices, index nearest to c2, sign of walking towards the junction)."""
    out = _unit((c2[0] - c1[0], c2[1] - c1[1]))
    probe = Point(c2[0] + out[0] * 1.5, c2[1] + out[1] * 1.5)
    rid2 = next((rid for rid, reg in regions.items() if reg.contains(probe)), None)
    if rid2 is None:
        return None
    best = None
    for rp, cs in _region_rings(regions, rid2, step):
        j0 = min(range(len(rp)), key=lambda k: (rp[k][0] - c2[0]) ** 2 + (rp[k][1] - c2[1]) ** 2)
        d0 = math.dist(rp[j0], c2)
        if best is None or d0 < best[0]:
            best = (d0, rp, cs, j0)
    if best is None or best[0] > 4.0:
        return None
    _, rp, cs, j0 = best
    n2 = len(rp)
    sg = 1 if _dot((rp[(j0 + 3) % n2][0] - rp[j0][0], rp[(j0 + 3) % n2][1] - rp[j0][1]), t) > 0 else -1
    return rp, set(cs), j0, sg


def far_corner_of(ink, regions, c1, c2, t, reach, step, accept, corner=(1e9, 1e9)):
    """The corner where A's far face meets B, found on the outline of the region on A's far side by
    walking from the far end c2 of the cut section towards the junction: the first corner that
    `accept(ring points, index, sign)` takes. Returns (ring points, corner index, walking sign beyond
    the corner) or None."""
    out = _unit((c2[0] - c1[0], c2[1] - c1[1]))
    probe = Point(c2[0] + out[0] * 1.5, c2[1] + out[1] * 1.5)
    rid2 = next((rid for rid, reg in regions.items() if reg.contains(probe)), None)
    _dbg(corner, 'far_corner_of: c2 %s rid2 %s reach %.0f' % (c2, rid2, reach))
    if rid2 is None:
        return None
    best = None
    for rp, cs in _region_rings(regions, rid2, step):
        j0 = min(range(len(rp)), key=lambda k: (rp[k][0] - c2[0]) ** 2 + (rp[k][1] - c2[1]) ** 2)
        d0 = math.dist(rp[j0], c2)
        if best is None or d0 < best[0]:
            best = (d0, rp, cs, j0)
    _dbg(corner, 'far_corner_of: nearest ring point d=%.1f' % (best[0] if best else -1))
    if best is None or best[0] > 4.0:
        return None
    _, rp, cs, j0 = best
    n2 = len(rp)
    sg = 1 if _dot((rp[(j0 + 3) % n2][0] - rp[j0][0], rp[(j0 + 3) % n2][1] - rp[j0][1]), t) > 0 else -1
    cset = set(cs)
    for k in range(1, int(reach / step) + 1):
        j = (j0 + sg * k) % n2
        if j in cset:
            ok = accept(rp, j, sg)
            _dbg(corner, 'far_corner_of: corner at k=%d %s accepted %s' % (k, rp[j], ok))
            if ok:
                return rp, j, sg
    _dbg(corner, 'far_corner_of: none; ring corners near: %s' % [rp[c] for c in cs if math.dist(rp[c], c2) < 150])
    return None


_INK_CACHE = {'key': None, 'core': None}


def _ink_core(ink):
    """The ink eroded by 1 unit (cached per glyph): outline of a gap inside it is a cut through ink."""
    if _INK_CACHE['key'] is not ink:
        _INK_CACHE['key'] = ink; _INK_CACHE['core'] = ink.buffer(-1.0)
    return _INK_CACHE['core']


_VERT_CACHE = {'key': None, 'pts': None}


def _ink_vertices(ink):
    """Vertices of the ink outline (cached per glyph)."""
    if _VERT_CACHE['key'] is not ink:
        out = []
        for g in _pieces(ink):
            if g.geom_type == 'Polygon':
                for ring in [g.exterior] + list(g.interiors):
                    out.extend(list(ring.coords)[:-1])
        _VERT_CACHE['key'] = ink; _VERT_CACHE['pts'] = out
    return _VERT_CACHE['pts']


def vertex_near(ink, q, r=3.0):
    """The outline vertex nearest to q within r units (a ring sample of a corner lies up to a sampling
    step off the vertex itself), else q."""
    best = None
    for v in _ink_vertices(ink):
        if abs(v[0] - q[0]) <= r and abs(v[1] - q[1]) <= r:
            d = math.dist(v, q)
            if d <= r and (best is None or d < best[0]):
                best = (d, v)
    return best[1] if best else q


def inner_corner(ink, rp, j, k=3):
    """True when the ring corner j is an inner corner of the ink (two strokes meeting): the chord between
    the outline points k samples either side of it runs through the air. At an outer corner (the end of
    a stroke) it runs through the ink."""
    n = len(rp); a = rp[(j - k) % n]; b = rp[(j + k) % n]
    return not ink.contains(Point((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))


def _corners_of_ring(rp):
    """Corner indices of a cached region ring (the list object itself), or None."""
    for rings in _RING_CACHE['rings'].values():
        for rp2, cs in rings:
            if rp2 is rp:
                return cs
    return None


def tip_face(ink, rp, jo, sg, P0, T0, stroke_w, step, corner=(1e9, 1e9)):
    """B's visible end edge, extended across B (OPTS tip). Co = rp[jo] is the outer corner where A's far
    face turns into the end of A (鬱: the bottom left corner of the bar under the sweep). Walking on from
    there, away from A's far face, the outline climbs A's end face and meets the underside of B's tip,
    which overhangs it: an inner corner Ca. It then runs along that short visible edge and turns at B's
    tip Ct (an outer corner). The line through Ct and Ca, carried on into the ink, is the end face the
    sweep would have had on its own; it meets B's near face (P0, T0) at E, near the corner. Returns
    (Ct, Ca, E, d, Tout), d the unit direction Ct -> E and Tout the direction of B's outer face above
    the tip (away from it), or None when the outline is not of that shape."""
    cs = _corners_of_ring(rp)
    if cs is None:
        return None
    n = len(rp); cset = set(cs); found = []
    for k in range(1, int(2.0 * stroke_w / step) + 1):
        j = (jo + sg * k) % n
        if j in cset:
            found.append(j)
            if len(found) == 2:
                break
    if len(found) < 2:
        _dbg(corner, 'tip: corners found %s' % [rp[j] for j in found])
        return None
    Ca, Ct = rp[found[0]], rp[found[1]]
    if not inner_corner(ink, rp, found[0]) or inner_corner(ink, rp, found[1]):
        _dbg(corner, 'tip: corners %s %s not inner then outer' % (tuple(round(v) for v in Ca), tuple(round(v) for v in Ct)))
        return None
    ell = math.dist(Ca, Ct)
    d = _unit((Ca[0] - Ct[0], Ca[1] - Ct[1]))                  # along the end edge, from the tip into the ink
    den = d[0] * T0[1] - d[1] * T0[0]
    _dbg(corner, 'tip: Ca %s Ct %s edge %.1f d.T0 %.2f' % (tuple(round(v) for v in Ca), tuple(round(v) for v in Ct), ell, _dot(d, T0)))
    if ell < 3.0 or ell > 1.2 * stroke_w or abs(_dot(d, T0)) > 0.85 or abs(den) < 1e-6:
        return None
    dx, dy = P0[0] - Ct[0], P0[1] - Ct[1]
    lam = (dx * T0[1] - dy * T0[0]) / den                      # Ct + d lam = P0 + T0 mu
    mu = (dx * d[1] - dy * d[0]) / den
    _dbg(corner, 'tip: lam %.1f mu %.1f' % (lam, mu))
    if lam < ell + 2.0 or lam > 2.5 * stroke_w or mu < -1.0 * stroke_w or mu > 1.5 * stroke_w:
        return None
    E = (Ct[0] + d[0] * lam, Ct[1] + d[1] * lam)
    hidden = ((Ca[0] + E[0]) / 2.0, (Ca[1] + E[1]) / 2.0)       # the carried-on part runs through the ink
    if not ink.contains(Point(hidden)):
        _dbg(corner, 'tip: extension not hidden')
        return None
    jt = found[1]
    qa, qb = rp[(jt + sg * 4) % n], rp[(jt + sg * 16) % n]
    Tout = _unit((qb[0] - qa[0], qb[1] - qa[1]))                # along B's outer face, away from the tip
    return Ct, Ca, E, d, Tout


def tip_cap(ink, pts, i, sgn, T0, Tout, nB, stroke_w, step, corner=(1e9, 1e9)):
    """The cap that ends B square to its own axis (OPTS tip, 12th round). It passes through the point of
    B's near face where the face runs straight (the sweep of 鬱 stands on a 9-unit upright foot above the
    corner; the cap passes just above it), square to the mean direction of B's two faces, and reaches
    B's outer face above the tip, so that both corners of the end are right angles and the pointed tip
    goes with the gap. Returns (Qin, Qout, cdir), cdir the unit direction Qin -> Qout, or None."""
    if _dot(T0, Tout) < math.cos(math.radians(25.0)):
        _dbg(corner, 'tip cap: faces not parallel (%.2f)' % _dot(T0, Tout))
        return None
    axis = _unit((T0[0] + Tout[0], T0[1] + Tout[1]))
    n = len(pts)
    Qin = pts[(i - sgn * 1) % n]
    for k in range(1, int(0.6 * stroke_w / step) + 1):
        idx = (i - sgn * k) % n
        dloc = _unit((pts[(idx - sgn * 2) % n][0] - pts[(idx + sgn) % n][0], pts[(idx - sgn * 2) % n][1] - pts[(idx + sgn) % n][1]))
        if _dot(dloc, T0) >= math.cos(math.radians(12.0)):
            Qin = pts[idx]
            break
    cdir = (-axis[1], axis[0])
    if _dot(cdir, nB) > 0:
        cdir = (-cdir[0], -cdir[1])                                  # across B, away from the hole
    seg = LineString([(Qin[0] + cdir[0] * 2.0, Qin[1] + cdir[1] * 2.0), (Qin[0] + cdir[0] * 1.6 * stroke_w, Qin[1] + cdir[1] * 1.6 * stroke_w)])
    hits = [g for g in _pieces(seg.intersection(ink.boundary)) if g.geom_type == 'Point']
    if not hits:
        _dbg(corner, 'tip cap: no outer face')
        return None
    hq = min(hits, key=lambda g: g.distance(Point(Qin)))
    Qout = (hq.x, hq.y); wB = math.dist(Qin, Qout)
    _dbg(corner, 'tip cap: Qin %s Qout %s width %.1f axis (%.2f, %.2f)' % (tuple(round(v) for v in Qin), tuple(round(v) for v in Qout), wB, axis[0], axis[1]))
    if wB < 0.3 * stroke_w or wB > 1.3 * stroke_w:
        return None
    return Qin, Qout, cdir


def root_face(ink, rp, jo, sg, pts, i, sgn, P0, t, stroke_w, step, corner=(1e9, 1e9), loose=False):
    """B takes over where A ends (OPTS root; 襲: the lowest bar of 龍 runs into the hane of its 乚). Beyond
    Co = rp[jo], the exposed corner of A's far face, the outline descends A's short end face to an inner
    corner, crosses a hollow of one or two short edges, and at an inner corner Qin turns into B's upper
    face, which runs on in A's direction. B's root is then capped by the straight face from Qin that
    rests on the inside of B's bend: the line from Qin tangent to B's near face where it curves away
    from A (the reviewer's sketch for 襲, 15th round). Returns (Qin, Qout, cdir, Tb), cdir the unit
    direction Qin -> Qout and Tb the direction of B's upper face, or None when the outline is not of
    that shape."""
    cs = _corners_of_ring(rp)
    if cs is None:
        _dbg(corner, 'root: ring not cached')
        return None
    n = len(rp); cset = set(cs); j1 = None
    for k in range(1, int(0.6 * stroke_w / step) + 1):
        j = (jo + sg * k) % n
        if j in cset:
            k1, j1 = k, j
            break
    if j1 is None and loose:
        # an end face too short for its foot to be listed beside the corner above it (聾: 10 units): the
        # first concave bend of 25 degrees or more over 2-sample arms
        for k in range(2, int(0.6 * stroke_w / step) + 1):
            j = (jo + sg * k) % n
            d_in = ring_dir(rp, (j - 2 * sg) % n, 2, forward=(sg > 0)); d_out = ring_dir(rp, j, 2, forward=(sg > 0))
            if math.degrees(math.acos(max(-1.0, min(1.0, _dot(d_in, d_out))))) >= 25.0 and inner_corner(ink, rp, j):
                k1, j1 = k, j
                break
    if j1 is None:
        _dbg(corner, 'root: no corner at the foot of A\'s end face')
        return None
    d1 = _unit((rp[j1][0] - rp[jo][0], rp[j1][1] - rp[jo][1]))      # along A's exposed end face
    if abs(_dot(d1, t)) > 0.5 or not inner_corner(ink, rp, j1):
        _dbg(corner, 'root: A end face %d units, d.t %.2f, inner %s' % (k1 * step, _dot(d1, t), inner_corner(ink, rp, j1)))
        return None
    # B's upper face begins at the sharpest bend of the hollow beyond that corner (a bend too gentle to
    # be listed as a corner: 21 degrees in 襲), concave, after which the ring runs on in A's direction
    # for 16 samples with no corner
    best = None
    for k in range(k1 + 2, k1 + int(1.0 * stroke_w / step) + 1):
        j = (jo + sg * k) % n
        if j in cset and not inner_corner(ink, rp, j):
            break                                                    # an outer corner: B's tip, not its root
        d_in = ring_dir(rp, (j - 2 * sg) % n, 2, forward=(sg > 0)); d_out = ring_dir(rp, j, 2, forward=(sg > 0))
        turn = math.degrees(math.acos(max(-1.0, min(1.0, _dot(d_in, d_out)))))
        if best is None or turn > best[0]:
            best = (turn, j)
    if best is None or best[0] < 12.0:
        _dbg(corner, 'root: no bend in the hollow (%s)' % (best and round(best[0])))
        return None
    turn, jq = best
    qa, qb = rp[(jq + sg * 1) % n], rp[(jq + sg * 16) % n]
    Tb = _unit((qb[0] - qa[0], qb[1] - qa[1]))                      # along B's upper face, away from A
    run_clear = not any(((jq + sg * m) % n) in cset for m in range(1, 17))
    _dbg(corner, 'root: bend %.0f at %s Tb.t %.2f run clear %s inner %s' % (turn, tuple(round(v) for v in rp[jq]), _dot(Tb, t), run_clear, inner_corner(ink, rp, jq)))
    if _dot(Tb, t) < math.cos(math.radians(35.0)) or not run_clear or not inner_corner(ink, rp, jq):
        return None
    Qin = rp[jq]
    # the foot of the cap: the point of B's near face (walked from the corner, away from A) that the
    # line from Qin turns furthest to reach; the face bends away from A there and the cap rests on it
    n2 = len(pts); u0 = _unit((P0[0] - Qin[0], P0[1] - Qin[1])); best = None
    for k in range(2, int(2.5 * stroke_w / step) + 1):
        q = pts[(i - sgn * k) % n2]
        uq = _unit((q[0] - Qin[0], q[1] - Qin[1]))
        ang = math.atan2(u0[0] * uq[1] - u0[1] * uq[0], _dot(u0, uq))
        if best is None or abs(ang) > abs(best[0]):
            best = (ang, q)
        elif abs(ang) < abs(best[0]) - math.radians(10.0):
            break                                                    # past the bend: the face turns back
    ang, Qout = best
    cdir = _unit((Qout[0] - Qin[0], Qout[1] - Qin[1])); wB = math.dist(Qin, Qout)
    _dbg(corner, 'root: Qin %s Qout %s turn %.0f width %.1f cdir.Tb %.2f' % (tuple(round(v) for v in Qin), tuple(round(v) for v in Qout), math.degrees(ang), wB, _dot(cdir, Tb)))
    # a real bend to rest on, a cap of about a stroke width and roughly square to B's upper face
    if abs(ang) < math.radians(10.0 if loose else 20.0) or wB < 0.4 * stroke_w or wB > 1.3 * stroke_w or abs(_dot(cdir, Tb)) > 0.5:
        return None
    for fr in (0.2, 0.5, 0.8):                                       # the cap runs through B's root
        if not ink.contains(Point((Qin[0] + cdir[0] * wB * fr, Qin[1] + cdir[1] * wB * fr))):
            _dbg(corner, 'root: cap not hidden')
            return None
    return Qin, Qout, cdir, Tb


def thin_remnant(ink, gap, r=8.0, reach=60.0):
    """Area of ink thinner than 2r that the cut newly creates next to the gap: a stroke end left as a
    pointed wedge, a fin of the stroke's flared end left on the stroke it met, a sliver beside the cut.
    Thin parts that the glyph already has do not count. A square cut end leaves none; the corner of an
    oblique cut end leaves r*r*(cot(a/2) - (pi - a)/2): 44 at 60 degrees, 79 at 45, 155 at 30."""
    win = gap.buffer(reach)
    before = ink.intersection(win)
    after = before.difference(gap)
    if after.is_empty:
        return 0.0
    ra = after.difference(after.buffer(-r).buffer(r))
    rb = before.difference(before.buffer(-r).buffer(r))
    new = ra.difference(rb.buffer(1.5))
    return sum(g.area for g in _pieces(new) if g.area > 8.0 and g.distance(gap) < 1.0)


THIN_MAX = 100.0       # the tip of a 40-degree corner at r = 8; the fins and wedges seen so far were 113-131


def throat(gap, regions, touched):
    """Width of the narrower of the two openings of the gap (into the two regions it joins). A slot
    whose end lands on another stroke opens through a throat much narrower than the slot itself."""
    return min(max(0.0, gap.exterior.intersection(regions[rid]).length - 4.0) for rid in touched)


def absorb_crumbs(ink, gap, gap_path, max_area):
    """Small bits of ink that the cut would leave floating are removed with it."""
    n_before = len([g for g in _pieces(ink) if g.area > 1.0])
    rest = [g for g in _pieces(ink.difference(gap)) if g.area > 1.0]
    if len(rest) > n_before:
        for cr in rest:
            if cr.area < max_area and cr.distance(gap) < 1.0:
                crb = cr.buffer(0.6, join_style=2)
                gap = gap.union(crb)
                if gap_path is not None:
                    gap_path = pathops.op(gap_path, poly_path(crb), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False)
        if gap.geom_type != 'Polygon':
            gap = max(_pieces(gap), key=lambda g: g.area)
    return gap, gap_path


def next_corner_dist(corners_idx, i, sgn, n):
    """Ring samples from corner index i to the next corner in direction sgn."""
    best = n
    for j in corners_idx:
        if j == i:
            continue
        d = (sgn * (j - i)) % n
        if 0 < d < best:
            best = d
    return best


def truncated_face(pts, i, sgn, corners_idx, stroke_w, step):
    """A face shorter than 0.3 stroke widths right after corner i (walking sgn), with the face beyond it
    running within 60 degrees of the face before the corner: the truncation of an acute corner of the
    hole (the top left of マ: the bar's underside, 12 units down the head of the dot, then the dot's
    upper face at 28 degrees to the bar). Returns (samples of the short face, index of its far corner,
    face length including the face beyond) or None."""
    n = len(pts); corner = pts[i]
    k1 = next_corner_dist(corners_idx, i, sgn, n)
    if k1 * step >= 0.3 * stroke_w or _os.environ.get('CORNERS_NO_TRUNC'):
        return None
    j2 = (i + sgn * k1) % n
    fB = _unit((pts[(i - sgn * 4) % n][0] - corner[0], pts[(i - sgn * 4) % n][1] - corner[1]))
    fA2 = _unit((pts[(j2 + sgn * 6) % n][0] - pts[j2][0], pts[(j2 + sgn * 6) % n][1] - pts[j2][1]))
    if _dot(fB, fA2) <= 0.5:
        return None
    return k1, j2, (k1 + next_corner_dist(corners_idx, j2, sgn, n)) * step


def cut_at_corner(ink, regions, pts, i, a_before, stroke_w, w, step, why=None, corners_idx=None, rounded=False, mode='end', w_t=None, allow_kink=True, trunc=False):
    """Build the end cut at ring index i, shortening the stroke whose face comes before the corner
    (a_before=True) or after it. Returns (gap, touched, cut point, direction into junction, removed) or None.
    allow_kink=False: without the chord form of 2.12 (the plain form is retried when the chord form fails
    its checks: the dot of マ in 霧 ends on the bar below the vertex, and that inner corner is not a kink).
    trunc=True: A's face runs on beyond a short truncation face (truncated_face)."""
    n = len(pts)
    kink = False

    def _reject(msg):
        """The gap failed a check: give up, or retry in the plain form when the chord form was used."""
        if why is not None: why.append(msg)
        if kink and allow_kink:
            if why is not None: why.append('(chord form failed; plain form)')
            return cut_at_corner(ink, regions, pts, i, a_before, stroke_w, w, step, why, corners_idx=corners_idx,
                                 rounded=rounded, mode=mode, w_t=w_t, allow_kink=False, trunc=trunc)
        return None
    sgn = -1 if a_before else 1          # walking direction along A's face away from the corner
    # --- B's face: outline points after the corner (or before), up to the next bend
    bpts = []; side1 = []; j = 1
    base = ring_dir(pts, i, 3, forward=a_before)          # ring direction along B's face
    side1.append(pts[i])
    while j * step <= 2.4 * stroke_w:
        idx = (i - sgn * j) % n
        d = ring_dir(pts, idx, 3, forward=a_before)
        if _dot(d, base) < math.cos(math.radians(40)):
            break
        side1.append(pts[idx])
        if j * step >= (0.7 if rounded else 0.25) * stroke_w:
            bpts.append((pts[idx], j * step))
        j += 1
    corner = pts[i]
    face_len = next_corner_dist(corners_idx, i, sgn, n) * step if corners_idx is not None else 4.0 * stroke_w
    j_first = 1                    # first ring sample of A's cross-sections
    trunc_j2 = None
    if trunc and corners_idx is not None:
        tf = truncated_face(pts, i, sgn, corners_idx, stroke_w, step)
        if tf is not None:
            k1, trunc_j2, face_len = tf
            j_first = k1 + 1
            _dbg(corner, 'truncated corner: short face %d, A face beyond %.0f' % (k1 * step, face_len))
    # normal of B's face pointing into the hole (= towards A, which borders the same hole)
    tB = base
    nB = (-tB[1], tB[0])           # the hole is on the left of a CCW ring
    if not bpts:
        bpts = [(corner, 0.0)]
    face = Face(bpts, nB, tB, stroke_w)
    # the bridge width this cut aims at: the nominal w, or (OPTS scale) w in the ratio of this glyph's
    # stroke width to an ordinary one, since dense kanji are drawn with thinner strokes on purpose
    if w_t is None:
        w_t = bridge_width(ink, stroke_w, w)
    # --- cross-sections of A along its face, walking away from the corner. The local width of A is
    # measured here (dense components of heavy weights are drawn thinner than the nominal stroke). The
    # widest section accepted shrinks with the glyph's stroke width like the bridge does: in 鷹 the 亻's
    # upright crossed by its ノ measured 93 beside a room, twice the glyph's strokes, and a cut across
    # that composite is a cut through the ノ
    max_sec = 1.5 * stroke_w * (w_t / w)
    secs = []                      # (j, p, far point, width, min distance of the two ends from B's face)
    j = j_first
    while j * step <= w + 3.0 * stroke_w:
        idx = (i + sgn * j) % n
        t = ring_dir(pts, idx, 3, forward=a_before)        # direction along the ring towards the corner
        if not a_before:
            t = (-t[0], -t[1])
        nin = (t[1], -t[0]) if a_before else (-t[1], t[0])  # into the ink (right of a CCW ring)
        p = pts[idx]
        q = (p[0] + nin[0] * 0.6, p[1] + nin[1] * 0.6)
        if ink.contains(Point(q)):
            r = face_point(ink, q, nin, 1.5 * stroke_w)
            if r is not None and 0.3 * stroke_w <= r[1] + 0.6 <= max_sec:
                secs.append((j, p, r[0], r[1] + 0.6, min(face.dist(p), face.dist(r[0])), t))
        j += 1
    # plain sections: width stable against the next sample (a junction blob changes the width abruptly)
    plain = []
    for k in range(len(secs) - 1):
        if secs[k + 1][0] == secs[k][0] + 1 and abs(secs[k + 1][3] - secs[k][3]) <= 0.15 * secs[k][3]:
            plain.append(secs[k])
    if not plain:
        if why is not None: why.append('no plain section')
        return None
    widths = sorted(x[3] for x in plain[:8]); L_A = widths[len(widths) // 2]
    # the gap may use the face up to half a stroke width before the next corner (the stub that stays)
    usable = face_len - 0.5 * L_A - 2.0 * step
    w_eff = min(w_t, usable)
    if w_eff < 0.5 * w:
        if why is not None: why.append('cell too small (face %.0f, width %.0f)' % (face_len, L_A))
        return None
    w_slot = w_eff
    if mode in ('slot', 'slotf'):
        kb0, kb1 = (i - sgn * 4) % n, (i - sgn * 16) % n
        tface = _unit((pts[kb1][0] - pts[kb0][0], pts[kb1][1] - pts[kb0][1]))
        r = slot_at_corner(ink, regions, pts, i, corner, plain, L_A, w_eff, step, stroke_w, why,
                           tface=tface, nB=nB, anchor=pts[kb0], face_len=face_len, along_face=(mode == 'slotf'), w=w)
        if r is not None:
            r[8]['w_t'] = w_t
        return r
    # --- B's face on the far side of A, then refit through both sides (line or circle)
    lf = (nB[1], -nB[0])                                      # along the face, from A towards side 1
    if _dot(lf, (side1[-1][0] - corner[0], side1[-1][1] - corner[1])) < 0:
        lf = (-lf[0], -lf[1])
    nf = (-lf[1], lf[0])
    if _dot(nf, nB) < 0:
        nf = (-nf[0], -nf[1])
    side2 = face_samples_beyond(ink, corner, lf, nf, L_A, stroke_w)
    if side2:
        samples2 = bpts + [(q, -(L_A + 0.15 * stroke_w + k * 4.0)) for k, q in enumerate(side2)]
        face2 = Face(samples2, nB, tB, stroke_w)
        # keep the refit only if it still agrees with side 1 (a bend on side 2 must not tilt it)
        if max(abs(face2.dist(q)) for q, _ in bpts) <= 2.5:
            face = face2
            plain = [(jj, p, far, L, min(face.dist(p), face.dist(far)), t) for jj, p, far, L, dmin, t in plain]
    cut = None
    for jj, p, far, L, dmin, t in plain:
        if jj * step > usable:
            break
        if dmin >= w_eff:
            cut = (((p[0] + far[0]) / 2, (p[1] + far[1]) / 2), t, p, far, jj * step); break
    if cut is None:
        # the clearance never reaches w_eff before the stroke bends away (small curls): take the widest
        # gap available, provided it is at least half the nominal width
        best = max((x for x in plain if x[0] * step <= usable), key=lambda x: x[4], default=None)
        if best is not None and best[4] >= 0.5 * w:
            jj, p, far, L, dmin, t = best
            w_eff = dmin
            cut = (((p[0] + far[0]) / 2, (p[1] + far[1]) / 2), t, p, far, jj * step)
    if cut is None:
        if why is not None: why.append('no cut position (width %.0f)' % L_A)
        return None
    mid, t, c1, c2, s = cut
    # the cut line never reaches past A's far face line (its median width + 1): where another stroke
    # leaves A's far face exactly at the cut (慣: a leg of 八 under the bar of 貝), the section measured
    # through both and the cut would nick the leg
    c2_raw = c2                    # the measured far end of the section (on the outline)
    wcut = math.dist(c1, c2)
    if wcut > L_A + 3.0:
        dn = ((c2[0] - c1[0]) / wcut, (c2[1] - c1[1]) / wcut)
        c2 = (c1[0] + dn[0] * (L_A + 1.0), c1[1] + dn[1] * (L_A + 1.0)); mid = ((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2)
    # a corner on A's far face just beyond the cut (another stroke joining A there, 園 角) would leave
    # a few units of A's face between the cut and that corner: move the cut onto the corner
    fr = far_ring(regions, c1, c2, t, step)
    if fr is not None:
        rp2, cs2, j0, sg0 = fr; n2 = len(rp2)
        for k in range(1, 6):
            j = (j0 - sg0 * k) % n2
            if j in cs2:
                d = -_dot((rp2[j][0] - c2[0], rp2[j][1] - c2[1]), t)
                if 0.5 < d <= 10.0:
                    mid = (mid[0] - t[0] * d, mid[1] - t[1] * d); c1 = (c1[0] - t[0] * d, c1[1] - t[1] * d)
                    c2 = (c2[0] - t[0] * d, c2[1] - t[1] * d); s = s + d
                break
    # --- B's face on both sides of A
    # near side: tangent of B's face from its straight part 8-32 units away from the corner (the first
    # samples sit on the rounding of the corner itself); the end point is a real outline point
    ka, kb = (i - sgn * 4) % n, (i - sgn * 16) % n
    T0 = _unit((pts[kb][0] - pts[ka][0], pts[kb][1] - pts[ka][1]))
    if _dot(T0, lf) < 0:
        T0 = (-T0[0], -T0[1])
    P0 = pts[(i - sgn * 1) % n]
    # far side: the corner where A's far face meets B, taken from the outline of the region on A's
    # other side (the mirror image of the near corner). Fallback when that outline has no corner
    # there (A's far face is flush with B's end, 国): the fitted face at A's width, clamped.
    side2 = []
    def _onto_face(rp2, jc, sg2):
        n2 = len(rp2)
        if not inner_corner(ink, rp2, jc):
            return False
        qa, qb = rp2[(jc + sg2 * 4) % n2], rp2[(jc + sg2 * 16) % n2]
        run = _unit((qb[0] - qa[0], qb[1] - qa[1]))
        tfar = (-run[0], -run[1])                              # along the far face, towards the junction
        same_dir = _dot(tfar, T0)
        chd = _unit((P0[0] - rp2[jc][0], P0[1] - rp2[jc][1]))
        _dbg(corner, 'far corner check: face.dist %.1f run.lf %.2f tfar.T0 %.2f chord %.2f/%.2f' % (
            face.dist(rp2[jc]), _dot(run, lf), same_dir, _dot(chd, T0), _dot(chd, tfar)))
        if same_dir < 0.64:                                    # bends by more than 50 degrees: not one face
            return False
        on_line = abs(face.dist(rp2[jc])) <= 0.25 * stroke_w and abs(_dot(run, lf)) >= 0.8
        smooth = _dot(chd, T0) >= 0.82 and _dot(chd, tfar) >= 0.82
        return on_line or smooth
    fc = far_corner_of(ink, regions, c1, c2, t, s + 1.5 * stroke_w, step, _onto_face, corner)
    if mode == 'slotx':
        # slot along the face of the stroke that meets A from the OTHER side (僕: the upright above the
        # bar, while the counter's corner below is made by the 丷). Only where the junction is kinked.
        if fc is not None:
            if why is not None: why.append('slotx: plain junction')
            return None
        fk = far_corner_of(ink, regions, c1, c2, t, s + 1.5 * stroke_w, step, lambda rp, j, sg: True, corner)
        if fk is None or not inner_corner(ink, fk[0], fk[1]):
            if why is not None: why.append('slotx: no far corner')
            return None
        rp2, jc, sg2 = fk; n2 = len(rp2)
        qa, qb = rp2[(jc + sg2 * 4) % n2], rp2[(jc + sg2 * 16) % n2]
        Tk = _unit((qa[0] - qb[0], qa[1] - qb[1]))
        r = slot_at_corner(ink, regions, pts, i, corner, plain, L_A, w_slot, step, stroke_w, why,
                           face_len=face_len, w=w, far=(qa, Tk))
        if r is not None:
            r[8]['w_t'] = w_t
        return r
    kink = False; nf3 = nf; sq_end = None; cap = None; tip = None; tcap = None; end_face = None; kink_via = []; root = False
    flush = False                  # B's end is flush with A's far face and its two faces are parallel (口 国)
    if fc is None:
        # B ends at A's far face (the first corner of that face is an outer corner) and B's near face is
        # not parallel to its outer face there (鬱: a diagonal that turns upright under the bar). Joining
        # the two corners would leave B's end as a pointed wedge; instead B's hidden face runs from the
        # near corner parallel to B's outer face, so that B keeps its width and ends square on A's far
        # face. When the two faces are parallel (国 口) the plain extension below does the same thing.
        fo = far_corner_of(ink, regions, c1, c2, t, s + 1.5 * stroke_w, step, lambda rp, j, sg: True, corner)
        fo_raw = None
        if fo is None and _o('flat') and OPTS['root'] and c2_raw is not c2:
            # the section was clipped to A's median width (A thickens into B: the lowest bar of 龍 in 聾)
            # and its clipped end lies inside the ink: for the root form only, the far corner is searched
            # from the measured end on the outline
            fo_raw = far_corner_of(ink, regions, c1, c2_raw, t, s + 1.5 * stroke_w, step, lambda rp, j, sg: True, corner)
            if fo_raw is not None and not inner_corner(ink, fo_raw[0], fo_raw[1]):
                rf = root_face(ink, fo_raw[0], fo_raw[1], fo_raw[2], pts, i, sgn, P0, t, stroke_w, step, corner, loose=True)
                if rf is not None:
                    Qin, Qout, cdir, Tb = rf
                    sq_end = (Qin, Tb, fo_raw[0][fo_raw[1]]); tcap = (Qin, Qout, cdir); root = True
        if fo is not None and not inner_corner(ink, fo[0], fo[1]):
            rpo, jo, sgo = fo; no = len(rpo); Co = rpo[jo]
            qa, qb = rpo[(jo + sgo * 4) % no], rpo[(jo + sgo * 16) % no]
            To = _unit((qa[0] - qb[0], qa[1] - qb[1]))            # along B's outer face, towards A's far face
            across = _unit((c2[0] - c1[0], c2[1] - c1[1]))        # across A, near face to far face
            den = To[0] * t[1] - To[1] * t[0]
            flush = _dot(To, across) > 0.5 and abs(_dot(To, T0)) >= 0.978
            if _dot(To, across) > 0.5 and abs(_dot(To, T0)) < 0.978 and abs(den) > 1e-6:
                lam = ((c2[0] - P0[0]) * t[1] - (c2[1] - P0[1]) * t[0]) / den
                F = (P0[0] + To[0] * lam, P0[1] + To[1] * lam)    # foot of the hidden face on A's far face
                wB = math.dist(F, Co)
                along = _dot((F[0] - c2[0], F[1] - c2[1]), t)
                _dbg(corner, 'square end: lam %.0f width %.0f along %.0f Co dist %.0f' % (lam, wB, along, math.dist(Co, corner)))
                if 0.5 * L_A <= lam <= 2.5 * L_A and 0.3 * stroke_w <= wB <= 2.2 * stroke_w and along > 0:
                    sq_end = (F, To, Co)
                    if OPTS['tip']:
                        tip = tip_face(ink, rpo, jo, sgo, P0, T0, stroke_w, step, corner)
                        if tip is not None and OPTS['tip'] != 'edge':
                            tcap = tip_cap(ink, pts, i, sgn, T0, tip[4], nB, stroke_w, step, corner)
                            if tcap is None:
                                tip = None                    # no cap: B keeps the plain square end
            if sq_end is None and OPTS['root']:
                # A runs into the root of B, which carries on in A's direction (襲): B is capped square to
                # its upper face at the corner where that face begins, the cap resting on the inside of
                # its bend; the merged end of A beside the cap goes with the gap
                rf = root_face(ink, rpo, jo, sgo, pts, i, sgn, P0, t, stroke_w, step, corner)
                if rf is not None:
                    Qin, Qout, cdir, Tb = rf
                    sq_end = (Qin, Tb, Co); tcap = (Qin, Qout, cdir); root = True
    if sq_end is not None:
        F, To, _Co = sq_end
        if root:
            # the cut keeps w_eff clear of B's near face from the corner to the foot of the cap, and of the cap
            Qin, Qout, _c = tcap
            guide = LineString([P0, Qout, Qin, (Qin[0] - _c[0] * 300.0, Qin[1] - _c[1] * 300.0)])
        elif tcap is not None:
            # the cut keeps w_eff clear of B's cap and of B's near face above it
            Qin, Qout, _c = tcap
            guide = LineString([Qout, Qin, (Qin[0] + T0[0] * 300.0, Qin[1] + T0[1] * 300.0)])
        elif tip is not None:
            # the cut keeps w_eff clear of B's natural end face and of B's near face
            Ct, _Ca, E, _d, _To = tip
            guide = LineString([Ct, E, P0, (P0[0] + T0[0] * 300.0, P0[1] + T0[1] * 300.0)])
        else:
            guide = LineString([(F[0] + To[0] * 300.0, F[1] + To[1] * 300.0), F, P0, (P0[0] + T0[0] * 300.0, P0[1] + T0[1] * 300.0)])
        cut2 = None
        # (root cap: B's face fitted through the corner no longer bounds anything, since the ink above it
        # goes with the gap; the cut may come closer than the plain cut did, w_eff from the guide)
        s_min = 0.0 if root else s
        for jj, p, far, L, dmin, tt in plain:
            if jj * step > usable:
                break
            if jj * step < s_min:
                continue
            if guide.distance(Point(p)) >= w_eff and guide.distance(Point(far)) >= w_eff:
                cut2 = (((p[0] + far[0]) / 2, (p[1] + far[1]) / 2), tt, p, far, jj * step); break
        if cut2 is None:
            if why is not None: why.append('no cut position clear of the square end')
            return None
        mid, t, c1, c2, s = cut2
    if fc is None and sq_end is None and not _NO_KINK and allow_kink:
        # no corner onto B's face: a third stroke shares the junction (夂: the bar starts where ノ and
        # ㇏ meet), so the face A ends on changes direction under A. The first corner of A's far face
        # is then the other end of A's root, and the two corners are joined by a straight chord.
        fk = far_corner_of(ink, regions, c1, c2, t, s + 1.5 * stroke_w, step, lambda rp, j, sg: True, corner)
        if fk is not None and inner_corner(ink, fk[0], fk[1]):
            rp2, jc, sg2 = fk; n2 = len(rp2)
            # two corners closer than 8 units are reported as one (the sharper): A's far face ends at
            # the first, so look for a local bend (2-sample arms) between the cut and that corner
            fr2 = far_ring(regions, c1, c2, t, step)
            if fr2 is not None and fr2[0] is rp2:
                j0 = fr2[2]
                for k in range(3, 6 * int(stroke_w / step)):
                    j = (j0 + sg2 * k) % n2
                    if j == jc:
                        break
                    d1 = ring_dir(rp2, (j - 2 * sg2) % n2, 2, forward=(sg2 > 0)); d2 = ring_dir(rp2, j, 2, forward=(sg2 > 0))
                    if _dot(d1, d2) < math.cos(math.radians(25.0)) and (sg2 * (jc - j)) % n2 <= 6:
                        jc = j; fk = (rp2, jc, sg2); break
            Cf = rp2[jc]; ch = math.dist(Cf, corner)
            chd = _unit((Cf[0] - corner[0], Cf[1] - corner[1]))
            qa, qb = rp2[(jc + sg2 * 4) % n2], rp2[(jc + sg2 * 16) % n2]
            Tk = _unit((qa[0] - qb[0], qa[1] - qb[1]))            # along the far face, towards the corner
            nk = (-Tk[1], Tk[0])
            if _dot(nk, (c2[0] - Cf[0], c2[1] - Cf[1])) < 0:
                nk = (-nk[0], -nk[1])                             # towards A (the air between A and that face)
            along_A = _dot((Cf[0] - corner[0], Cf[1] - corner[1]), t)
            # the ring's direction arriving at the far corner (along A's far face, towards the junction)
            d_in = ring_dir(rp2, (jc - 3 * sg2) % n2, 3, forward=(sg2 > 0))
            _dbg(corner, 'kink: chord %.0f (L_A %.0f) chord.t %.2f nk.nf %.2f along %.0f Tk.t %.2f din.Tk %.2f' % (ch, L_A, _dot(chd, t), _dot(nk, nf), along_A, _dot(Tk, t), _dot(d_in, Tk)))
            if KINK_LOG is not None:
                KINK_LOG.append(dict(corner=tuple(round(v) for v in corner), Cf=tuple(round(v) for v in Cf), ch=round(ch), L_A=round(L_A), chd_t=round(_dot(chd, t), 2),
                                     nk_nf=round(_dot(nk, nf), 2), along=round(along_A), Tk_t=round(_dot(Tk, t), 2), din_Tk=round(_dot(d_in, Tk), 2),
                                     Tk=(round(Tk[0], 2), round(Tk[1], 2)), t=(round(t[0], 2), round(t[1], 2)), a_before=a_before))
            if 0.6 * L_A <= ch <= 1.8 * L_A and abs(_dot(chd, t)) <= 0.75 and _dot(nk, nf) > 0.2:
                fc = fk; kink = True; nf3 = nk
                P3k = rp2[(jc + sg2 * 1) % n2]
                if OPTS['kinkface'] and min(abs(Tk[0]), abs(Tk[1])) < math.sin(math.radians(20.0)) and min(abs(t[0]), abs(t[1])) < math.sin(math.radians(20.0)):
                    # (A itself upright or level too: the rectangular gap is a property of straight strokes;
                    # the loops of kana keep the chord)
                    # the third stroke's face is upright or level: A's hidden face follows it up to A's near
                    # face (番: the bar starts square where the upright's right face, carried up through the
                    # bar, meets the bar's top) instead of running along the chord to the far corner
                    # ... up to whichever it meets first: A's near face (番: the bar's top) or B's face (魚: the
                    # ノ ends on the corner of 田, so its hidden end is that corner, top face then left face)
                    hits = []
                    for org, dirn, what in ((corner, t, 'A'), (P0, T0, 'B')):
                        den = Tk[0] * dirn[1] - Tk[1] * dirn[0]
                        if abs(den) > 1e-6:
                            lam = ((org[0] - Cf[0]) * dirn[1] - (org[1] - Cf[1]) * dirn[0]) / den
                            if 0.5 * L_A <= lam <= 2.5 * L_A:
                                hits.append((lam, (Cf[0] + Tk[0] * lam, Cf[1] + Tk[1] * lam), what))
                    if hits:
                        lam, c0, what = min(hits)
                        back = -_dot((c0[0] - corner[0], c0[1] - corner[1]), t)     # from the corner towards the cut
                        _dbg(corner, 'kinkface: lam %.0f c0 %s on %s back %.0f' % (lam, tuple(round(v) for v in c0), what, back))
                        if -2.0 <= back <= s:
                            kink_via = [c0]
                # the cut must be w_eff clear of the far face and of the chord (or the face) as well
                guide = LineString([(P3k[0] - Tk[0] * 300.0, P3k[1] - Tk[1] * 300.0), P3k] + kink_via + [P0,
                                    (P0[0] + T0[0] * 300.0, P0[1] + T0[1] * 300.0)])
                cut2 = None
                for jj, p, far, L, dmin, tt in plain:
                    if jj * step > usable:
                        break
                    if jj * step < s:
                        continue
                    if guide.distance(Point(p)) >= w_eff and guide.distance(Point(far)) >= w_eff:
                        cut2 = (((p[0] + far[0]) / 2, (p[1] + far[1]) / 2), tt, p, far, jj * step); break
                if cut2 is None:
                    return _reject('no cut position clear of the far face')
                mid, t, c1, c2, s = cut2
    if fc is not None:
        rp2, jc, sg2 = fc; n2 = len(rp2)
        P3 = rp2[(jc + sg2 * 1) % n2]
        qa, qb = rp2[(jc + sg2 * 4) % n2], rp2[(jc + sg2 * 16) % n2]
        T3 = _unit((qa[0] - qb[0], qa[1] - qb[1]))
        if not kink and _dot(T3, lf) < 0:
            T3 = (-T3[0], -T3[1])
        side2 = [rp2[(jc + sg2 * k) % n2] for k in range(2, 14)]
        u_far = _dot((P3[0] - corner[0], P3[1] - corner[1]), lf)
        far_pts_real = [rp2[(jc + sg2 * k) % n2] for k in (8, 6, 4, 3)]
    elif sq_end is not None:
        F, To, Co = sq_end
        cap = None
        # B really ends here only if there is air beyond A's far face across B's width, including just
        # inside B's outer face: where that face runs on as an ink edge (the bowl of e turning into its
        # lower arc) B continues and is not capped
        mB = ((Co[0] + F[0]) / 2.0, (Co[1] + F[1]) / 2.0)
        n_in = _unit((F[0] - Co[0], F[1] - Co[1])); wB = math.dist(F, Co)
        eB = (Co[0] + n_in[0] * 0.25 * wB, Co[1] + n_in[1] * 0.25 * wB)
        probes = [(q[0] + To[0] * k * stroke_w, q[1] + To[1] * k * stroke_w) for q in (mB, eB) for k in (0.3, 0.6)]
        ends = not any(ink.contains(Point(q)) for q in probes)
        # and only where B is clearly oblique to its outer face (the sweep of 鬱, 38 degrees): a wall that
        # stands square on A's far face (the bowl of e on its bar, 14 degrees) keeps its foot as drawn
        oblique = abs(_dot(To, T0)) < 0.9
        _dbg(corner, 'cap test: Co %s F %s To (%.2f, %.2f) ends %s oblique %s' % (tuple(round(v) for v in Co), tuple(round(v) for v in F), To[0], To[1], ends, oblique))
        if tcap is not None:
            # B ends with a cap square to its own axis through the top of its foot (12th round: the tip
            # of the sweep of 鬱 was still pointed); the merged start of A below the cap goes with the gap
            Qin, Qout, cdir = tcap
            P3 = (Qout[0] + cdir[0] * 0.3, Qout[1] + cdir[1] * 0.3)   # just outside B's outer face
            T3 = (-cdir[0], -cdir[1])                         # along the cap, from P3 towards B's near face
            nf3 = (-T3[1], T3[0])
            if _dot(nf3, T0) > 0:
                nf3 = (-nf3[0], -nf3[1])                      # the side of the cap that A's root is on
            end_face = (Qin, (-nf3[0], -nf3[1]))
            _dbg(corner, 'tip cap: Qin %s Qout %s' % (Qin, Qout))
        elif tip is not None:
            # B ends along its own visible end edge, extended across it to its near face (the reviewer's
            # sketch for 鬱, 11th round: the sweep keeps its tip; the merged start of A below that face goes
            # with the gap)
            Ct, Ca, E, d, _To = tip
            P3 = (Ct[0] - d[0] * 0.3, Ct[1] - d[1] * 0.3)      # just outside B's outer face, at the tip
            T3 = d                                            # along the end face, from the tip towards B's near face
            nf3 = (-d[1], d[0])
            if _dot(nf3, T0) > 0:
                nf3 = (-nf3[0], -nf3[1])                      # the side of the end face that A's root is on
            end_face = (Ct, (-nf3[0], -nf3[1]))
            _dbg(corner, 'tip: Ct %s Ca %s E %s' % (Ct, Ca, E))
        elif OPTS['cap'] and ends and oblique:
            # study option: B ends with a cap square to its own axis through the near corner, the way the
            # Light master ends the same stroke, and the whole root of A beside B's end (its start, hidden
            # under B) goes with the gap. Without it B's hidden face runs parallel to its outer face, which
            # shows the merged root of A as a continuation of B (鬱: the sweep seems to run on to the
            # bottom of the bar as an upright block)
            cdir = (-T0[1], T0[0])
            if _dot(cdir, nB) > 0:
                cdir = (-cdir[0], -cdir[1])                   # across B, away from the hole
            seg = LineString([P0, (P0[0] + cdir[0] * 1.5 * stroke_w, P0[1] + cdir[1] * 1.5 * stroke_w)])
            hits = [g for g in _pieces(seg.intersection(ink.boundary)) if g.geom_type == 'Point']
            hits = [h for h in hits if h.distance(Point(P0)) > 4.0]
            if hits:
                hq = min(hits, key=lambda g: g.distance(Point(P0)))
                cap = ((hq.x, hq.y), cdir)
            _dbg(corner, 'cap: P0 %s T0 (%.2f, %.2f) cdir (%.2f, %.2f) Q %s' % (P0, T0[0], T0[1], cdir[0], cdir[1], cap[0] if cap else None))
        if tip is not None:
            pass
        elif cap is not None:
            Q, cdir = cap
            P3 = (Q[0] + cdir[0] * 0.3, Q[1] + cdir[1] * 0.3)   # just outside B's outer face
            T3 = (-cdir[0], -cdir[1])                         # along the cap, from P3 towards P0
            nf3 = (-T0[0], -T0[1])                            # the side of the cap that A's root is on
            end_face = (P0, T0)
        else:
            P3 = (F[0] + To[0] * 0.3, F[1] + To[1] * 0.3)     # just past A's far face
            T3 = (-To[0], -To[1])
            nf3 = (-T3[1], T3[0])
            if _dot(nf3, t) > 0:
                nf3 = (-nf3[0], -nf3[1])                      # towards A's body
        u_far = _dot((P3[0] - corner[0], P3[1] - corner[1]), lf)
        far_pts_real = []
    else:
        sin_ab = abs(t[0] * lf[1] - t[1] * lf[0])
        u_far = -(L_A / max(sin_ab, 0.35) + 2.0)
        P3 = ray_face(ink, corner, lf, nf, u_far)
        _dbg(corner, 'no far corner: u_far %.1f ray point %s c2 %s t (%.2f, %.2f) face %s flush %s P0 %s T0 (%.2f, %.2f)' % (u_far, P3, tuple(round(v, 1) for v in c2), t[0], t[1], face.kind, flush, tuple(round(v, 1) for v in P0), T0[0], T0[1]))
        if P3 is not None and _o('flat') and flush and abs(_dot((P3[0] - c2[0], P3[1] - c2[1]), (-t[1], t[0]))) < 1.5:
            # the ray ran along A's own far face (B's end is flush with it: the frame of 口 under the
            # start of its top bar) and the point found is on that face, not on B: use the fitted face
            _dbg(corner, 'far point %s lies on the far face of A: fitted face instead' % (tuple(round(v, 1) for v in P3),))
            P3 = None
        sq_b = False
        rootish = False
        if P3 is None and _o('flat') and not flush:
            # A's far face bends gently (8-45 degrees, no corner) into a face that runs on beyond the
            # junction: B takes A over (the lowest bar of 龍 flowing into its hane in 聾, with no end face
            # for `root` to start from); B's near face is then carried on along its tangent as well
            fr4 = far_ring(regions, c1, c2_raw, t, step)
            if fr4 is not None:
                rp4, cs4, j4, sg4 = fr4; n4 = len(rp4); dev = 0.0; clear = True
                k0 = int((s + 4.0) / step); k1 = int((s + L_A + 30.0) / step)
                for k in range(1, k1 + 1):
                    j = (j4 + sg4 * k) % n4
                    if j in cs4:
                        clear = False; break
                    if k >= k0:
                        d4 = ring_dir(rp4, j, 4, forward=True) if sg4 > 0 else tuple(-v for v in ring_dir(rp4, j, 4, forward=False))
                        dev = max(dev, math.degrees(math.acos(max(-1.0, min(1.0, _dot(d4, t))))))
                rootish = clear and 8.0 <= dev <= 45.0
                _dbg(corner, 'far face beyond the junction: clear %s bend %.0f -> rootish %s' % (clear, dev, rootish))
        bface = next_corner_dist(corners_idx, i, -sgn, n) * step if corners_idx is not None else 1e9
        if P3 is None and _o('flat') and (flush or rootish):
            # nothing of B beyond A's far face to measure (B's end is flush with it): B's near face is
            # carried straight on along its tangent (a circle fitted through a slightly tapered side of
            # 口 put the far point 6 units off in 事)
            lam = u_far - _dot((P0[0] - corner[0], P0[1] - corner[1]), lf)
            P3 = (P0[0] + T0[0] * lam, P0[1] + T0[1] * lam)
        elif P3 is None and _o('flat') and bface < 0.5 * stroke_w:
            # B's face beside A is a short neck (the head of ム under the bar of 禸 in 愚, 18 units): its
            # direction says nothing about a face across A, and the gap ends square to A at the corner
            acr = _unit((c2[0] - c1[0], c2[1] - c1[1]))
            P3 = (P0[0] + acr[0] * (math.dist(c1, c2) + 2.0), P0[1] + acr[1] * (math.dist(c1, c2) + 2.0))
            sq_b = True
            _dbg(corner, 'short B face (%.0f): square across A' % bface)
        elif P3 is None:
            qf = (corner[0] + lf[0] * u_far, corner[1] + lf[1] * u_far)
            dd = face.dist(qf); P3 = (qf[0] - nf[0] * dd, qf[1] - nf[1] * dd)
        T3 = T0
        if sq_b:
            T3 = _unit((P0[0] - P3[0], P0[1] - P3[1]))
        far_pts_real = []
    # --- the gap: A's ink beyond the square cut and on the hole side of B's face, confined to A's
    # corridor (its width at the cut plus half a stroke width each side)
    E = 0.5 * L_A + 0.5 * stroke_w; D = s + 2.0 * stroke_w
    nn = (-t[1], t[0])
    if end_face is not None:
        # the cap reaches B's outer face, which may lie above A's corridor
        E = max(E, abs(_dot((P3[0] - mid[0], P3[1] - mid[1]), nn)) + 4.0)
    beyond = Polygon([(mid[0] + nn[0] * E, mid[1] + nn[1] * E), (mid[0] - nn[0] * E, mid[1] - nn[1] * E),
                      (mid[0] - nn[0] * E + t[0] * D, mid[1] - nn[1] * E + t[1] * D),
                      (mid[0] + nn[0] * E + t[0] * D, mid[1] + nn[1] * E + t[1] * D)])
    H = D + 2.0 * stroke_w
    # straight face: the real outline points next to the junction on both sides lie on the line P3-P0
    chord = _unit((P0[0] - P3[0], P0[1] - P3[1])); cn = (-chord[1], chord[0])
    dev = [abs(_dot((q[0] - P3[0], q[1] - P3[1]), cn)) for q in side1[1:14] + side2[:5]]
    straight = (not kink) and sq_end is None and bool(dev) and max(dev) <= 0.35 and _dot(T0, chord) > 0.9995 and _dot(T3, chord) > 0.9995
    near_pts = [pts[(i - sgn * k) % n] for k in range(3, 9)] if not straight else []
    far_pts = far_pts_real if not straight else []
    flat = False
    if _o('flat') and not straight and not kink and sq_end is None:
        a3 = math.degrees(math.asin(max(-1.0, min(1.0, T3[0] * chord[1] - T3[1] * chord[0]))))    # far tangent -> chord
        a0 = math.degrees(math.asin(max(-1.0, min(1.0, chord[0] * T0[1] - chord[1] * T0[0]))))    # chord -> near tangent
        lo, hi = sorted((abs(a3), abs(a0)))
        arc = a3 * a0 > 0 and lo >= 1.5 and _dot(T3, chord) > 0 and _dot(T0, chord) > 0
        flat = not arc
        _dbg(corner, 'flat: far %.1f near %.1f deg -> %s' % (a3, a0, 'chord' if flat else 'arc'))
        if FLAT_LOG is not None:
            FLAT_LOG.append((tuple(round(v) for v in corner), a_before, round(a3, 1), round(a0, 1), flat))
        if flat and not kink_via and abs(_dot(chord, t)) > math.sin(math.radians(8.0)):
            # the chord would slant by more than 8 degrees across A, the two corners being at different
            # heights (愚: above the bar the upright of 田, below it the head of the 厶 stroke): where one of
            # the two faces stands square on A it is carried across A instead, and the gap stays a rectangle
            best = None
            for Q, Tq, O in ((P3, T3, P0), (P0, T0, P3)):
                den = Tq[0] * t[1] - Tq[1] * t[0]
                if abs(_dot(Tq, t)) > math.sin(math.radians(20.0)) or abs(den) < 1e-6:
                    continue
                lam = ((O[0] - Q[0]) * t[1] - (O[1] - Q[1]) * t[0]) / den
                c0 = (Q[0] + Tq[0] * lam, Q[1] + Tq[1] * lam)
                run = math.dist(c0, O)
                if run > 0.7 * L_A or abs(lam) > 1.5 * L_A:
                    continue
                path = LineString([Q, c0, O])
                if path.difference(ink.buffer(1.0)).length > 1.0:
                    continue
                if best is None or abs(_dot(Tq, t)) < best[0]:
                    best = (abs(_dot(Tq, t)), c0)
            if best is not None:
                kink_via = [best[1]]
                _dbg(corner, 'flat: square corner via %s' % (tuple(round(v, 1) for v in best[1]),))
    if sq_end is not None and end_face is not None:
        # the region on A's side of the cap (or of B's natural end face), plus A's ink between the corner
        # and the cut below A's near face (the line continued past the corner would cut into that part obliquely)
        BIG = 3000.0
        def _half(origin, nrm, slack=0.3):
            """Half-plane dot(p - origin, nrm) <= slack as a large polygon."""
            o = (origin[0] + nrm[0] * slack, origin[1] + nrm[1] * slack); pp = (-nrm[1], nrm[0])
            return Polygon([(o[0] + pp[0] * BIG, o[1] + pp[1] * BIG), (o[0] - pp[0] * BIG, o[1] - pp[1] * BIG),
                            (o[0] - pp[0] * BIG - nrm[0] * BIG, o[1] - pp[1] * BIG - nrm[1] * BIG),
                            (o[0] + pp[0] * BIG - nrm[0] * BIG, o[1] + pp[1] * BIG - nrm[1] * BIG)])
        nin_A = (t[1], -t[0]) if a_before else (-t[1], t[0])  # into A's ink from its near face
        above = _half(*end_face).union(_half(corner, t).intersection(_half(corner, (-nin_A[0], -nin_A[1]))))
        if above.geom_type != 'Polygon':
            above = max(_pieces(above), key=lambda g: g.area)
        above_path = poly_path(above)
    else:
        above_path, above = above_region(P3, T3, P0, T0, nf, H, straight, far_pts=far_pts, near_pts=near_pts,
                                         wide_near=3.0 * stroke_w, wide_far=(3.0 * stroke_w if fc is not None else 0.0),
                                         chord=(kink or sq_end is not None or flat), nf_far=nf3, up=(-t[0], -t[1]), via=kink_via)
    region = beyond.intersection(above)
    # near B's face the region is limited to A's footprint on the face (+4 units): without this it
    # follows B's face sideways and slices a wedge off B where B bends (the tail of ね)
    def _fp(u, dd):
        return (corner[0] + lf[0] * u + nf[0] * dd, corner[1] + lf[1] * u + nf[1] * dd)
    big = 6.0 * stroke_w; hb = 0.45 * stroke_w; lo = -2.0 * stroke_w     # lo: B may curve away below the tangent
    wing_r = Polygon([_fp(4.0, lo), _fp(4.0 + big, lo), _fp(4.0 + big, hb), _fp(4.0, hb)])
    wing_l = Polygon([_fp(u_far - 4.0, lo), _fp(u_far - 4.0 - big, lo), _fp(u_far - 4.0 - big, hb), _fp(u_far - 4.0, hb)])
    wings = [wing_r] + ([wing_l] if fc is not None else [])    # the far limit is only trusted when measured
    fin_used = False
    if _o('fin') and fc is not None and not kink and trunc_j2 is None:
        # an outer corner on A's far side between the cut and the far corner: A's end face is exposed
        # there, and what lies beyond the far corner along B's face is the end of A, not B
        fr3 = far_ring(regions, c1, c2, t, step)
        if fr3 is not None and fr3[0] is fc[0]:
            rp3, cs3, j3, sg3 = fr3; n3 = len(rp3)
            for k in range(1, n3):
                j = (j3 + sg3 * k) % n3
                if j == fc[1]:
                    break
                if j in cs3 and not inner_corner(ink, rp3, j):
                    if math.dist(rp3[j], rp3[fc[1]]) >= 0.5 * L_A:      # a real end face, not a chamfered corner
                        _dbg(corner, 'fin: A has an exposed end face at %s: no far wing' % (tuple(round(v) for v in rp3[j]),))
                        wings = [wing_r]; fin_used = True
                    break
    if end_face is not None:
        wings = []          # the cap itself bounds the region on B's side; the wing would clip B's root below it
    for wg in wings:
        region = region.difference(wg)
        above_path = pathops.op(above_path, poly_path(wg), pathops.PathOp.DIFFERENCE, fix_winding=True, keep_starting_points=False)
        above = above.difference(wg)
    pieces = [g for g in _pieces(region.intersection(ink)) if g.geom_type == 'Polygon']
    if not pieces:
        return _reject('no pieces')
    ref = Point(mid[0] + t[0] * 3.0, mid[1] + t[1] * 3.0)
    piece = min(pieces, key=lambda g: g.distance(ref))
    if piece.distance(ref) > 2.0:
        return _reject('piece away')
    if _o('band') and sq_end is None and not kink:
        ts = [x[5] for x in plain if x[0] * step <= s + 1e-6]
        ws_ = [x[3] for x in plain if x[0] * step <= s + 1e-6]
        # (A straight and of one width between the junction and the cut: a stroke that widens towards
        # the junction, the foot of 予 in 務, has no band)
        if ts and min(_dot(tt, t) for tt in ts) > math.cos(math.radians(6.0)) and max(ws_) - min(ws_) <= 3.0:
            half = 0.5 * math.dist(c1, c2) + 3.0
            band = LineString([(mid[0] - t[0] * 2.0, mid[1] - t[1] * 2.0), (mid[0] + t[0] * D, mid[1] + t[1] * D)]).buffer(half, cap_style=2)
            # (only ink clear of B's face: where A's foot spreads along an oblique B the part outside the
            # band is the junction itself, and leaving it out left a wedge on B: 務)
            hid = LineString([P3, P0])
            away = [g for g in _pieces(piece.difference(band)) if g.geom_type == 'Polygon' and g.area > 1.0 and g.distance(hid) > 3.0]
            if sum(g.area for g in away) > 25.0:
                rest = piece
                for g in away:
                    rest = rest.difference(g.buffer(0.01))
                inb = [g for g in _pieces(rest) if g.geom_type == 'Polygon']
                if inb:
                    _dbg(corner, 'band: %.0f units of other ink left out' % sum(g.area for g in away))
                    piece = min(inb, key=lambda g: g.distance(ref))
    # the piece must stay within A's corridor (not merged with a neighbouring stroke)
    axis = LineString([mid, (mid[0] + t[0] * D, mid[1] + t[1] * D)]).buffer(0.85 * max(L_A, 0.6 * stroke_w) + 2.0)
    if piece.difference(axis).area > 0.35 * piece.area:
        return _reject('outside corridor %.0f%%' % (100 * piece.difference(axis).area / piece.area))
    # widen 2 units beyond A's faces (clean boolean against the outline), but keep the face-side edge
    # and the cut line exact
    strip = piece.buffer(2.0, join_style=2).intersection(beyond)
    if strip.geom_type != 'Polygon':
        strip = max(_pieces(strip), key=lambda g: g.area)
    gap = strip.intersection(above)
    if gap.geom_type != 'Polygon':
        gap = max(_pieces(gap), key=lambda g: g.area) if not gap.is_empty else piece
    # the same region with the face as a true curve, for the boolean cut
    gap_path = pathops.op(poly_path(strip), above_path, pathops.PathOp.INTERSECTION, fix_winding=True, keep_starting_points=False)
    # crumbs: small bits of A's flare that the cut would leave floating are removed with it
    gap, gap_path = absorb_crumbs(ink, gap, gap_path, 0.3 * w_eff * L_A)
    touched = [rid for rid, reg in regions.items() if reg.intersects(gap.buffer(0.5))]
    if len(touched) != 2:
        return _reject('touched %d' % len(touched))
    th = throat(gap, regions, touched)
    if th < 0.45 * w:
        return _reject('throat %.0f' % th)
    # the outline of the gap runs through ink only along the cut line and under A's root; more than
    # that means it slices another stroke (the straight extension of B's face through a third stroke)
    inner = gap.boundary.intersection(_ink_core(ink)).length
    expect = L_A + math.dist(P3, P0)
    if inner > expect + 0.6 * stroke_w:
        return _reject('cuts through other ink (%.0f vs %.0f)' % (inner, expect))
    thin = thin_remnant(ink, gap)
    if thin > THIN_MAX:
        return _reject('leaves a thin wedge (%.0f)' % thin)
    k_face = int(round(face_len / step))
    far_corner = pts[(i + sgn * k_face) % n] if corners_idx is not None else None
    dbg = {'corner': corner, 'a_before': a_before, 'P0': P0, 'P3': P3, 'T0': T0, 'T3': T3, 'straight': straight,
           'fc': ('kink' if kink else ('root-cap' if root else ('tip-cap' if tcap is not None else 'tip-edge') if tip is not None else 'cap' if cap is not None else 'square-end') if sq_end is not None else fc is not None),
           'inner': inner, 'expect': expect,
           'shapes': {'beyond': beyond, 'above': above, 'wings': wings, 'piece': piece, 'strip': strip}, 'u_far': u_far, 'c1': c1, 'c2': c2, 's': s, 't': t, 'lf': lf, 'nf': nf}
    return gap, touched, mid, t, s, w_eff, face_len, gap_path, {'stub': face_len - s, 'L_A': L_A, 'far_corner': far_corner, 'throat': th, 'dbg': dbg, 'w_t': w_t, 'trunc_j2': trunc_j2, 'flat': flat, 'fin': fin_used}


def _end_dir(st, kind, stroke_w):
    """Direction of travel into the junction at a stroke end, from the aligned (unsnapped) polyline."""
    pts = st.get('pts0', st['pts']); tot = poly_length(pts)
    if kind == 'END':
        a, _ = point_at(pts, max(0.0, tot - 1.8 * stroke_w)); b, _ = point_at(pts, max(0.0, tot - 0.4 * stroke_w))
    else:
        a, _ = point_at(pts, min(tot, 1.8 * stroke_w)); b, _ = point_at(pts, min(tot, 0.4 * stroke_w))
    return _unit((b[0] - a[0], b[1] - a[1]))          # START: against the direction of travel


def stroke_near(strokes, pt, stroke_w, skip=None):
    """(d, index, u, tot) of the stroke polyline nearest to pt within 1.2 stroke widths, or None."""
    best = None
    for si, st in enumerate(strokes):
        if skip is not None and si == skip:
            continue
        d, u, _, tot = nearest_on_polyline(st['pts'], pt)
        if best is None or d < best[0]:
            best = (d, si, u, tot)
    return best if best and best[0] <= 1.2 * stroke_w else None


def slot_at_corner(ink, regions, pts, i, corner, plain, L_A, w_eff, step, stroke_w, why=None,
                   tface=None, nB=None, anchor=None, face_len=None, along_face=False, w=None, far=None):
    """Slot across the through stroke A beside the junction. One edge is B's face line itself, extended
    through A; the other is parallel to it at the bridge width on the hole side. B's face therefore runs
    on through A as one straight line (no corner, nothing pointed left at the foot of B), and the gap
    is the same width everywhere. At a right-angle junction this is the plain square slot.
    Returns the same tuple as cut_at_corner."""
    near = [x for x in plain if x[0] * step <= w_eff + 0.5 * L_A]
    if not near:
        if why is not None: why.append('slot: no plain section')
        return None
    sec = near[-1]                                            # a plain section of A away from the foot
    tA = sec[5]
    p_s, far_s = sec[1], sec[2]
    ninA = _unit((far_s[0] - p_s[0], far_s[1] - p_s[1]))      # across A, from its near face to its far face
    if far is not None:
        # one edge is the face line of the stroke on A's far side, extended through A; the slot lies on
        # the side of that line away from the junction, so that face runs straight on as the slot's edge
        qf, Tk = far
        dB = Tk if _dot(Tk, ninA) > 0 else (-Tk[0], -Tk[1])
        cosang = _dot(dB, ninA)
        den = dB[0] * tA[1] - dB[1] * tA[0]
        if cosang < 0.8 or abs(den) < 1e-6:                   # that face must cross A nearly square
            if why is not None: why.append('slotx: far face too oblique')
            return None
        lam = ((p_s[0] - qf[0]) * tA[1] - (p_s[1] - qf[1]) * tA[0]) / den
        c0 = (qf[0] + dB[0] * lam, qf[1] + dB[1] * lam)       # where the far face line crosses A's near face
        nB = (-dB[1], dB[0])
        if _dot(nB, tA) > 0:                                  # tA points into the junction
            nB = (-nB[0], -nB[1])
        d0 = _dot((corner[0] - c0[0], corner[1] - c0[1]), tA)
        if d0 < -2.0 or d0 > 1.2 * L_A:                       # the line must cross A beside the corner, on A's side
            if why is not None: why.append('slotx: far face line away from the corner (%.0f)' % d0)
            return None
    elif tface is None:
        if why is not None: why.append('slot: no face')
        return None
    fB = (tface if _dot(tface, ninA) > 0 else (-tface[0], -tface[1])) if tface is not None else None   # along B's face, into A
    if far is not None:
        pass
    elif along_face:
        # one edge is B's face line extended through A; the other parallel to it on the hole side
        dB = fB
        cosang = _dot(dB, ninA)
        if cosang < 0.5 or cosang > 0.995:                    # too oblique, or square anyway (within 6 degrees; the
            # uprights of # lean 10 degrees, and a slot square to them left an 8-unit wedge under the bar)
            if why is not None: why.append('slot: face variant not applicable')
            return None
        k = _dot((corner[0] - anchor[0], corner[1] - anchor[1]), dB)
        c0 = (anchor[0] + dB[0] * k, anchor[1] + dB[1] * k)   # the corner projected on the face line
    else:
        # square to A, with one edge through the corner; the slot lies on the side away from B
        dB = ninA; cosang = 1.0; c0 = vertex_near(ink, corner) if _o('flat') else corner
        nB = (-tA[0], -tA[1])
    if _o('flat'):
        # the slot's far edge within 4 units of an outline vertex on A's faces (the next corner of a short
        # face: 蹙, 2 units past the underside of a side bar) is moved onto that vertex
        wsec0 = math.dist(p_s, far_s); offs = []
        for v in _ink_vertices(ink):
            if abs(v[0] - c0[0]) <= 3.0 * stroke_w and abs(v[1] - c0[1]) <= 3.0 * stroke_w:
                al = _dot((v[0] - c0[0], v[1] - c0[1]), nB)
                dv = _dot((v[0] - p_s[0], v[1] - p_s[1]), ninA)
                if abs(al - w_eff) <= 4.0 and -2.0 <= dv <= wsec0 + 2.0 and al >= 0.5 * (w or w_eff):
                    offs.append(al)
        if offs:
            w_eff = min(offs, key=lambda a_: abs(a_ - w_eff))
    # long enough that both edges of the band cross A completely even when it is oblique to A
    ext = w_eff * math.sqrt(max(0.0, 1.0 - cosang * cosang)) / cosang + 6.0
    reach = L_A / cosang + ext
    ca = (c0[0] - dB[0] * ext, c0[1] - dB[1] * ext); cb = (c0[0] + dB[0] * reach, c0[1] + dB[1] * reach)
    band = Polygon([ca, cb, (cb[0] + nB[0] * w_eff, cb[1] + nB[1] * w_eff), (ca[0] + nB[0] * w_eff, ca[1] + nB[1] * w_eff)])
    ref = Point(c0[0] + dB[0] * 0.5 * L_A / cosang + nB[0] * 0.5 * w_eff, c0[1] + dB[1] * 0.5 * L_A / cosang + nB[1] * 0.5 * w_eff)
    pieces = [g for g in _pieces(band.intersection(ink)) if g.geom_type == 'Polygon']
    if not pieces:
        if why is not None: why.append('slot: no pieces')
        return None
    piece = min(pieces, key=lambda g: g.distance(ref))
    if piece.distance(ref) > 2.0:
        if why is not None: why.append('slot: piece away')
        return None
    expect = w_eff * L_A / cosang
    if abs(piece.area - expect) > 0.35 * expect:
        if why is not None: why.append('slot: area %.0f vs %.0f' % (piece.area, expect))
        return None
    # the slot ends on A's own faces: where other ink continues beyond A's far face (a stem under the
    # bar) it stops exactly on that face line; where there is air it overshoots by 2 units
    big = 4.0 * stroke_w
    def _cor(d0, d1):
        a0 = (p_s[0] + ninA[0] * d0, p_s[1] + ninA[1] * d0); a1 = (p_s[0] + ninA[0] * d1, p_s[1] + ninA[1] * d1)
        return Polygon([(a0[0] - tA[0] * big, a0[1] - tA[1] * big), (a0[0] + tA[0] * big, a0[1] + tA[1] * big),
                        (a1[0] + tA[0] * big, a1[1] + tA[1] * big), (a1[0] - tA[0] * big, a1[1] - tA[1] * big)])
    wA = math.dist(p_s, far_s)
    if _o('flat'):
        # the far end of the slot on the true far face: an outline vertex within 2 units of the measured
        # face line beside the slot (the section was measured where the face is a fraction of a unit off)
        ds = []
        for v in _ink_vertices(ink):
            if abs(v[0] - c0[0]) <= 3.0 * stroke_w and abs(v[1] - c0[1]) <= 3.0 * stroke_w:
                dv = _dot((v[0] - p_s[0], v[1] - p_s[1]), ninA)
                al = _dot((v[0] - c0[0], v[1] - c0[1]), nB)
                if abs(dv - wA) <= 2.0 and -0.5 * w_eff <= al <= 1.5 * w_eff:
                    ds.append(dv)
        if ds:
            wA = min(ds, key=lambda d: abs(d - wA))
    inner = band.intersection(_cor(-3.0, wA))
    over = band.intersection(_cor(wA, wA + 2.0)).difference(ink.buffer(0.01))
    gap = inner.union(over)
    if _o('flat'):
        # a wedge of the junction between A's near face line and the room (the truncated apex of the room
        # beside the hook of 戈 in 載) goes with the slot: left behind it showed as a nub on the slot's edge
        wedge = band.intersection(_cor(-0.5 * L_A, -3.0)).intersection(ink)
        if not wedge.is_empty and 1.0 < wedge.area <= 0.2 * expect:
            gap = gap.union(wedge.buffer(0.4, join_style=2))
        # ... and a bit of it beyond A's far face line (not a stem that crosses there: under 6 % of the slot)
        wedge2 = band.intersection(_cor(wA, wA + 0.5 * L_A)).intersection(ink)
        if not wedge2.is_empty and 1.0 < wedge2.area <= 0.06 * expect:
            gap = gap.union(wedge2.buffer(0.4, join_style=2))
    if gap.geom_type != 'Polygon':
        gap = max(_pieces(gap), key=lambda g: g.area) if not gap.is_empty else piece
    gap, _ = absorb_crumbs(ink, gap, None, 0.3 * w_eff * L_A)
    touched = [rid for rid, reg in regions.items() if reg.intersects(gap.buffer(0.5))]
    if len(touched) != 2:
        if why is not None: why.append('slot: touched %d' % len(touched))
        return None
    th = throat(gap, regions, touched)
    if th < 0.45 * (w or w_eff):
        if why is not None: why.append('slot: throat %.0f' % th)
        return None
    thin = thin_remnant(ink, gap)
    if thin > (60.0 if (_o('flat') and not along_face and far is None) else THIN_MAX):
        # (a square slot leaves nothing thin at a square junction; 嚢: two spikes of the merge with the bar above)
        if why is not None: why.append('slot: leaves a thin wedge (%.0f)' % thin)
        return None
    mid = (ref.x, ref.y)
    return gap, touched, mid, tA, w_eff, w_eff, (face_len or 4.0 * stroke_w), None, {'stub': 4.0 * stroke_w, 'L_A': L_A, 'far_corner': None, 'throat': th}


def _is_dot(st):
    """A KanjiVG dot (㇔, also its variants such as ㇔/㇑)."""
    return str(st.get('type', '')).startswith('㇔')


def _is_sweep(st, loose=False):
    """A KanjiVG sweep or leg (㇒ ノ, ㇏, ㇀ 提), not a dot. Kana strokes carry no type and are never sweeps.
    loose (OPTS bend, cuts that no stroke end explains): the falling part of a ㇇ counts as well."""
    typ = str(st.get('type', ''))
    return not _is_dot(st) and any(k in typ for k in (('㇒', '㇏', '㇀', '㇇') if (loose and _o('bend')) else ('㇒', '㇏', '㇀')))


def classify(strokes, corner, tA, tB, nin, stroke_w, junction_tol=1.5, mid=None):
    """(kind, si, meet, sj) when a KanjiVG stroke ends at this corner approaching along tA, else None.
    mid: the cut's centre on A; among the strokes ending at the corner along tA, those running within
    0.75 stroke widths of the cut come first, the nearest end deciding among them as before (KanjiVG
    draws the dot of マ shorter than the font does: at the dot's head the nearest stroke end is the
    bar's start, 41 units away, and the ㇇ passes 62 units from the cut; the dot passes 8 units from it).
    When no stroke runs under the cut, the nearest end decides as before."""
    if not strokes:
        return None
    found = []
    for si, st in enumerate(strokes):
        pts = st['pts']
        if len(pts) < 2:
            continue
        d_mid = nearest_on_polyline(pts, mid)[0] if (mid is not None and not _os.environ.get('CORNERS_NO_MIDRANK')) else 0.0
        for kind, P in (('END', pts[-1]), ('START', pts[0])):
            d = math.dist(P, corner)
            if d > junction_tol * stroke_w:
                continue
            tdir = _end_dir(st, kind, stroke_w)
            if _dot(tdir, tA) < 0.7:
                continue
            found.append((d, kind, si, d_mid))
    if not found:
        return None
    under = [f for f in found if f[3] <= 0.75 * stroke_w]
    # (a further tier "the stroke within a quarter width of the cut first" was tried for 襲, where the
    # snapped end of the 乚 lies inside the bar 21 units from the bar's own cut and takes the label from
    # the bar; it relabelled 認 誌 and moved the cuts of 驚 郵 園, so the label stays as it is: same cost)
    _, kind, si, _ = min(under or found, key=lambda f: f[0])
    # the stroke met: nearest polyline to a point inside B, own stroke only far from the end in question
    pB = (corner[0] + tA[0] * 0.5 * stroke_w + nin[0] * 0.3 * stroke_w,
          corner[1] + tA[1] * 0.5 * stroke_w + nin[1] * 0.3 * stroke_w)
    bj = None
    for sj, st in enumerate(strokes):
        d, u, _, tot = nearest_on_polyline(st['pts'], pB)
        if sj == si:
            uP = tot if kind == 'END' else 0.0
            if abs(u - uP) < 2.5 * stroke_w:
                continue
        if bj is None or d < bj[0]:
            bj = (d, sj, u, tot)
    if bj is None or bj[0] > junction_tol * stroke_w:
        return kind, si, None, None
    _, sj, u, tot = bj
    meet = 'START' if u < 1.0 * stroke_w else ('END' if tot - u < 1.0 * stroke_w else 'THROUGH')
    return kind, si, meet, sj


def corner_candidates(ink, regions, ext_id, strokes, stroke_w, w, prefer_later=False, step=2.0):
    cands = []
    _CTX['kanji'] = bool(strokes) and any(st.get('type') for st in strokes)
    n_ink = len([g for g in _pieces(ink) if g.area > 50.0])
    # Latin keeps the nominal width: its strokes are thinner by design (e 55, # 53), not for density
    w_t = w if prefer_later else bridge_width(ink, stroke_w, w)
    for rid, reg in regions.items():
        if rid == ext_id:
            continue
        ring = orient(Polygon(reg.exterior.coords), 1.0).exterior
        pts = resample(list(ring.coords)[:-1], step)
        if len(pts) < 12:
            continue
        corners, turns, rounded = ring_corners(pts, step)
        jobs = [(i, mode, a_before, False) for i in corners for mode in ('end', 'slot', 'slotf', 'slotx') for a_before in (True, False)]
        # an acute corner of the hole truncated by a short face (the top left of マ) gets an end cut
        # whose A face runs on beyond the short face; it is dropped below when the far corner of the
        # short face already yields an end cut for the same face (角 解 観: the same cut, from the other corner)
        jobs += [(i, 'end', a_before, True) for i in corners for a_before in (True, False)
                 if truncated_face(pts, i, -1 if a_before else 1, corners, stroke_w, step) is not None]
        n_before = len(cands)
        for i, mode, a_before, trunc in jobs:
                why = []
                r = cut_at_corner(ink, regions, pts, i, a_before, stroke_w, w, step, why, corners_idx=corners, rounded=rounded.get(i, False), mode=mode, w_t=w_t, trunc=trunc)
                if r is None:
                    continue
                gap, touched, mid, t, removed, w_eff, face_len, gap_path, extra = r
                narrow = 0.1 * (1.0 - w_eff / extra.get('w_t', w))   # prefer the bridge width aimed at
                # an opening narrower than the gap itself (the far end partly blocked by another stroke)
                narrow += 0.3 * max(0.0, 1.0 - extra.get('throat', w_eff) / w_eff)
                tA = t                                             # direction of A into the junction
                tB = ring_dir(pts, i, 3, forward=a_before)
                sg = -1 if a_before else 1
                kb0, kb1 = (i - sg * 4) % len(pts), (i - sg * 16) % len(pts)
                tface = _unit((pts[kb1][0] - pts[kb0][0], pts[kb1][1] - pts[kb0][1]))   # along B's face
                if mode == 'slotf':
                    # the square slot first when the junction is square (within 6 degrees); where B's face
                    # is off square the slot along it comes first (the uprights of # lean 10 degrees: the
                    # square slot left an 8-unit wedge of the upright under the bar)
                    narrow += 0.03 if abs(_dot(tface, tA)) < 0.105 else -0.03
                if OPTS['oblique'] and mode in ('slot', 'slotx'):
                    # a slot square to A beside an oblique B leaves A's stub ending in a face that belongs
                    # to no stroke (鬱: the foot of the sweep merged with the end of the bar it sits on);
                    # the same slot at a square junction of A, or another cut, comes first
                    narrow += OPTS['oblique'] * max(0.0, abs(_dot(tface, tA)) - 0.17)
                # inward normal into A's ink (ring CCW: ink on the right of the ring direction)
                nin = (tA[1], -tA[0]) if a_before else (-tA[1], tA[0])
                # the stroke under the cut comes first (CJK: KanjiVG is exact there; for Latin, where its
                # strokes are rough sketches of the digits, the nearest end decides as before)
                cl = classify(strokes, pts[i], tA, tB, nin, stroke_w, mid=(None if prefer_later else mid)) if mode == 'end' else None
                # OPTS dot: a dot (㇔) that ends on the end of another stroke (the vertex of マ in 霧) is
                # shortened at its START, where it hangs from the bar; the vertex where the two strokes
                # end together stays (both end cuts there are put back), and the dot may be left shorter
                # than a stroke width (12th round: the reviewer marked the head of the dot for removal)
                dot_cut = False; dot_vertex = False
                if OPTS['dot'] and cl is not None:
                    k0, s0, m0, j0 = cl
                    if k0 == 'END' and m0 == 'END' and j0 is not None and _is_dot(strokes[s0]) != _is_dot(strokes[j0]):
                        dot_vertex = True
                    if k0 == 'START' and _is_dot(strokes[s0]):
                        # the dot's end and the other stroke's end at one point (霧: 23 units apart); a dot
                        # that merely ends near another stroke's end (病 響 欄, 50-100 units) is not one
                        end = strokes[s0].get('pts0', strokes[s0]['pts'])[-1]
                        dot_cut = any(not _is_dot(st) and math.dist(end, st.get('pts0', st['pts'])[-1]) <= 0.6 * stroke_w
                                      for k, st in enumerate(strokes) if k != s0 and len(st['pts']) >= 2)
                if dot_cut and extra.get('fin'):
                    # the start of such a dot keeps the form reviewed in the 12th round (霧)
                    keep = OPTS['fin']; OPTS['fin'] = False
                    try:
                        r = cut_at_corner(ink, regions, pts, i, a_before, stroke_w, w, step, None, corners_idx=corners, rounded=rounded.get(i, False), mode=mode, w_t=w_t, trunc=trunc)
                    finally:
                        OPTS['fin'] = keep
                    if r is None:
                        continue
                    gap, touched, mid, t, removed, w_eff, face_len, gap_path, extra = r
                # a short stroke that hangs from a bar by a narrow head and lands on another stroke (the
                # short ㇒ of 衣 in 讓): the bar is cut beside the head and the stroke keeps its square end
                # under the bar (the square-end form of the 8th round), instead of the stroke being cut at
                # its foot. The form that cuts the head itself left a nub under the bar (層) and is not used
                neck_cut = False
                if _o('bend') and trunc and cl is not None and cl[0] == 'START' and (extra.get('dbg') or {}).get('fc') == 'square-end':
                    st0 = strokes[cl[1]]; p0s = st0.get('pts0', st0['pts'])
                    if poly_length(p0s) <= 2.2 * stroke_w and str(st0.get('type', ''))[:1] in ('㇒', '㇔'):
                        neck_cut = any(k != cl[1] and len(o['pts']) >= 2 and nearest_on_polyline(o.get('pts0', o['pts']), p0s[-1])[0] <= 0.6 * stroke_w
                                       for k, o in enumerate(strokes))
                if trunc and not dot_cut and not neck_cut:
                    # the cut across a truncated acute corner exists for the start of such a dot only (at
                    # the top of 観 it would cut the ノ obliquely instead of the bar's start)
                    continue
                # long enough to see a loop bend, but not past the next corner of A's face
                span = max(8, int(min(2.5 * stroke_w, face_len - 0.3 * stroke_w) / step))
                face_len_b = next_corner_dist(corners, i, 1 if a_before else -1, len(pts)) * step
                span_b = max(8, int(min(2.5 * stroke_w, face_len_b - 0.3 * stroke_w) / step))
                curvA = face_curvature(pts, i, span, forward=not a_before)
                curvB = face_curvature(pts, i, span_b, forward=a_before)
                if cl is not None:
                    kind, si, meet, sj = cl
                    # legibility: a stroke that ENDS at the next corner too (its whole visible length is
                    # this face) must keep about one stroke width: 僕's 丷 would be left as a tick of
                    # 32-46 units, 懐's dividers keep 64. A stroke that runs on past the next corner
                    # (a frame side spanning several cells, 東) is not affected.
                    fc = extra['far_corner']
                    if mode == 'end' and fc is not None and not dot_cut and not neck_cut:
                        other = strokes[si]['pts'][0] if kind == 'END' else strokes[si]['pts'][-1]
                        if math.dist(other, fc) <= 1.5 * stroke_w and extra['stub'] < 0.9 * extra['L_A']:
                            narrow += 1.5
                    if _o('bend') and mode == 'end' and kind == 'START' and _is_dot(strokes[si]) and not dot_cut and removed > 1.6 * w_eff:
                        # a dot is shortened at its head by about a bridge width; a start cut that takes
                        # far more of it (愚: 146 units of the dot of 禸, the gap having to clear the neck
                        # it hangs from) comes after the slots
                        narrow += 1.5
                    base = COST[(kind, meet)]
                    tie = min(0.01 * si, 0.05) if prefer_later else min(0.004 * si, 0.03)
                    if kind == 'START' or prefer_later:
                        tie = -tie
                    cost = base + tie + 0.1 * max(0.0, removed - 1.5 * w) / w + narrow
                    if dot_cut:
                        cost -= 0.3                           # the dot's start opens the counter like an end cut would
                    if dot_vertex:
                        cost += 0.5                           # the vertex of the dot and the other stroke stays
                    info = 's%d:%s>%s' % (si + 1, kind, ('s%d:%s' % (sj + 1, meet)) if sj is not None else 'free')
                    stroke = si
                else:
                    # crossing: keep the straighter face; between straight strokes cut the later one
                    if _o('bend') and mode == 'end':
                        # a cut that no stroke end explains and that is narrower than the bridge aimed at
                        # (費: a 33-unit nick in the small room of 弗) comes after a full-width slot
                        narrow += 0.4 * (1.0 - w_eff / extra.get('w_t', w))
                    x0, y0, x1, y1 = reg.bounds; span = max(x1 - x0, y1 - y0, 1.0)
                    pos = ((x1 - mid[0]) + (mid[1] - y0)) / span
                    cost = 1.0 + 0.05 * removed / w + narrow + 0.02 * pos
                    if curvA + 5.0 < curvB:
                        cost += 0.3
                    sa = stroke_near(strokes, mid, stroke_w) if strokes else None
                    pB = (pts[i][0] + tA[0] * 0.5 * stroke_w, pts[i][1] + tA[1] * 0.5 * stroke_w)
                    sb = stroke_near(strokes, pB, stroke_w) if strokes else None
                    # a short stroke that both starts and ends on this counter (僕's 丷) is not cut at
                    # all when less than a stroke width of it would remain beside the gap
                    if sa:
                        sp = strokes[sa[1]]['pts']
                        fcorner = pts[(i + (-1 if a_before else 1) * int(round(face_len / step))) % len(pts)]
                        at_c = min(math.dist(sp[0], pts[i]), math.dist(sp[-1], pts[i])) <= 1.5 * stroke_w
                        at_f = min(math.dist(sp[0], fcorner), math.dist(sp[-1], fcorner)) <= 1.5 * stroke_w
                        if at_c and at_f and face_len - removed < 1.0 * extra['L_A']:
                            cost += 1.5
                    if sa and sb and sa[1] != sb[1]:
                        if sa[1] < sb[1]:
                            cost += 0.2
                        info = 's%d:%s>s%d' % (sa[1] + 1, mode if mode != 'end' else 'x', sb[1] + 1); stroke = sa[1]
                    else:
                        info = 'corner:' + mode; stroke = -2
                        if _o('bend') and mode == 'end' and sa and sb and sa[1] == sb[1] and str(strokes[sa[1]].get('type', ''))[:1] not in ('', '㇐', '㇑', '㇒', '㇏', '㇔', '㇀'):
                            # A and the stroke it "ends" on are one stroke: the cut parts it at its bend
                            cost += _o('bend'); info += '/bend'
                    # at a near-right-angle junction the end cut and the slot coincide in shape and the
                    # end cut (face-following edge) comes first; at an oblique one the slot keeps the
                    # gap width uniform and comes first
                    # a curved stroke meeting a straight one (the loop of は ほ ま returning to its stem)
                    # is shortened flush with it; a straight through stroke (僕's bar under the 丷) gets
                    # a square slot at the corner, which keeps the gap width uniform
                    if (mode == 'end') == (curvA <= 6.0):   # slot variants count as 'not end'
                        cost += 0.05
                # OPTS axis: the stroke cut runs obliquely at the cut (a sweep, a leg of 人): the cut edge is
                # oblique too, and the reviewer prefers the bar or upright it meets to be shortened instead
                # (only a sweep or leg by KanjiVG type, ㇒ ㇏ ㇀: kana strokes carry no type, and the crossing
                # cuts of their loops are oblique by nature. For a slot or crossing cut the stroke under the
                # cut decides: the slot through the ノ of 亻 in 鷹)
                sweep_cut = strokes and ((cl is not None and _is_sweep(strokes[cl[1]])) or (cl is None and sa is not None and _is_sweep(strokes[sa[1]], loose=True)))
                if OPTS['axis'] and sweep_cut and not dot_cut and min(abs(tA[0]), abs(tA[1])) > math.sin(math.radians(20.0)):
                    cost += OPTS['axis']; info += '/obl'
                    if mode != 'end' and _o('bend'):
                        cost += 0.1                           # a slot through a sweep comes after a cut that shortens a bar (憂)
                    if mode == 'end' and (extra.get('flat') or extra.get('fin')):
                        # a cut of a sweep that only the straight hidden face lets through (the curved face
                        # left a wedge and the cut was rejected: the ノ of 亻 in 鷹, where the reviewer asked
                        # for the bar to be shortened and the sweep kept) stays rejected
                        keep = (OPTS['flat'], OPTS['fin']); OPTS['flat'] = False; OPTS['fin'] = False
                        try:
                            r0 = cut_at_corner(ink, regions, pts, i, a_before, stroke_w, w, step, None, corners_idx=corners, rounded=rounded.get(i, False), mode=mode, w_t=w_t, trunc=trunc)
                        finally:
                            OPTS['flat'], OPTS['fin'] = keep
                        if r0 is None:
                            continue
                # a cut must not leave a piece of ink attached to nothing (a floating dash)
                n_after = len([g for g in _pieces(ink.difference(gap)) if g.area > 50.0])
                if n_after > n_ink:
                    cost += _o('orphan'); info += '!orphan'
                c = Cand(touched[0], touched[1], mid, mid, t, w_eff, gap, cost, info)
                c.stroke = stroke; c.removed = removed; c.corner = (rid, i); c.w = w_eff; c.gap_path = gap_path
                c.dbg = extra.get('dbg'); c.L_A = extra.get('L_A')
                c.mode = mode; c.a_before = a_before; c.trunc_j2 = extra.get('trunc_j2') if trunc else None
                cands.append(c)
        # the truncated-corner cut only where the far corner of the short face gave no end cut of its own
        new = cands[n_before:]
        plain_ends = {(c.corner[1], c.a_before) for c in new if c.mode == 'end' and c.trunc_j2 is None}
        cands[n_before:] = [c for c in new if c.trunc_j2 is None or (c.trunc_j2, c.a_before) not in plain_ends]
    return cands
