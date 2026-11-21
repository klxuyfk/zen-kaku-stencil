"""Outline post-processing for CAD cleanliness and TrueType output."""
import math
import pathops
from .core import path_polys, signed_area

def segs_to_path(segs):
    p = pathops.Path(); pen = p.getPen()
    for verb, pts in segs:
        if verb == 'moveTo':
            pen.moveTo(pts[0])
        elif verb == 'lineTo':
            pen.lineTo(pts[0])
        elif verb == 'qCurveTo':
            pen.qCurveTo(*pts)
        elif verb == 'curveTo':
            pen.curveTo(*pts)
        elif verb == 'closePath':
            pen.closePath()
        elif verb == 'endPath':
            pen.endPath()
    return p

def _r(p):
    return (float(round(p[0])), float(round(p[1])))

def round_path(path):
    """Round all coordinates to integers (TrueType requirement)."""
    out = pathops.Path(); pen = out.getPen()
    for verb, pts in path.segments:
        if verb == 'moveTo':
            pen.moveTo(_r(pts[0]))
        elif verb == 'lineTo':
            pen.lineTo(_r(pts[0]))
        elif verb == 'qCurveTo':
            pen.qCurveTo(*[(_r(p) if p is not None else None) for p in pts])
        elif verb == 'curveTo':
            pen.curveTo(*[_r(p) for p in pts])
        elif verb == 'closePath':
            pen.closePath()
        elif verb == 'endPath':
            pen.endPath()
    return out

def drop_short_lines(path, min_len=2.0, min_area=400.0):
    """Merge on-curve points closer than min_len along line segments (including the implicit closing
    segment) and drop contours smaller than min_area (slivers)."""
    out = pathops.Path(); pen = out.getPen()
    for contour in path.contours:
        segs = list(contour.segments)
        pts = contour_points_plain(contour)
        if len(pts) >= 3 and abs(signed_area(pts)) < min_area:
            continue
        # rebuild the segment list: drop lineTo points that are too close to the previous point,
        # and a trailing point too close to the start (closing segment)
        kept = []; cur = None; start = None
        for verb, p in segs:
            if verb == 'moveTo':
                cur = start = p[0]; kept.append((verb, p))
            elif verb == 'lineTo':
                q = p[0]
                if cur is not None and math.dist(cur, q) < min_len:
                    continue
                kept.append((verb, p)); cur = q
            elif verb in ('qCurveTo', 'curveTo'):
                kept.append((verb, p)); cur = p[-1] if p[-1] is not None else cur
            else:
                kept.append((verb, p))
        # closing segment: last explicit lineTo point near the start
        if start is not None and len(kept) >= 3 and kept[-1][0] == 'closePath' and kept[-2][0] == 'lineTo':
            if math.dist(kept[-2][1][0], start) < min_len:
                del kept[-2]
        for verb, p in kept:
            if verb == 'moveTo':
                pen.moveTo(p[0])
            elif verb == 'lineTo':
                pen.lineTo(p[0])
            elif verb == 'qCurveTo':
                pen.qCurveTo(*p)
            elif verb == 'curveTo':
                pen.curveTo(*p)
            elif verb == 'closePath':
                pen.closePath()
            elif verb == 'endPath':
                pen.endPath()
    return out

def merge_collinear(path, tol=0.5):
    """Remove on-curve points that join two line segments and lie on the straight line between their
    neighbours (within tol). A cut that ends flush with a straight face leaves such points where the
    face used to meet the removed stroke; without them the face is one line again."""
    out = pathops.Path(); pen = out.getPen()
    for contour in path.contours:
        segs = list(contour.segments)
        nodes = []; start = None
        for verb, pts in segs:
            if verb == 'moveTo':
                start = pts[0]
            elif verb == 'lineTo':
                nodes.append((pts[0], 'L', None))
            elif verb in ('qCurveTo', 'curveTo'):
                nodes.append((pts[-1], verb, pts[:-1]))
        if start is None or len(nodes) < 2:
            for verb, pts in segs:
                getattr(pen, verb)(*pts)
            continue
        if math.dist(nodes[-1][0], start) > 1e-6:
            nodes.append((start, 'L', None))                 # implicit closing line
        # nodes[k] = (point, type of the segment arriving at it, controls); cyclic
        changed = True
        while changed and len(nodes) > 3:
            changed = False
            n = len(nodes)
            for k in range(n):
                q, tq, _ = nodes[k]; nxt = nodes[(k + 1) % n]; prv = nodes[(k - 1) % n]
                if tq != 'L' or nxt[1] != 'L':
                    continue
                pp, r = prv[0], nxt[0]
                dx, dy = r[0] - pp[0], r[1] - pp[1]; L = math.hypot(dx, dy)
                if L < 1e-9:
                    continue
                dist = abs((q[0] - pp[0]) * dy - (q[1] - pp[1]) * dx) / L
                tpar = ((q[0] - pp[0]) * dx + (q[1] - pp[1]) * dy) / (L * L)
                if dist <= tol and 0.0 < tpar < 1.0:
                    del nodes[k]; changed = True; break
        pen.moveTo(nodes[-1][0])
        for q, tq, ctrl in nodes:
            if tq == 'L':
                pen.lineTo(q)
            elif tq == 'qCurveTo':
                pen.qCurveTo(*(list(ctrl) + [q]))
            else:
                pen.curveTo(*(list(ctrl) + [q]))
        pen.closePath()
    return out


def collapse_hairpins(path, max_arm=12.0, min_cos=0.9962):
    """Remove line vertices where the outline turns back on itself (< ~5 deg) with a short arm:
    hairline slivers/notches left by cuts near junctions."""
    out = pathops.Path(); pen = out.getPen()
    for contour in path.contours:
        segs = list(contour.segments)
        # indices of on-curve points coming from line segments
        pts = []
        for i, (verb, p) in enumerate(segs):
            if verb in ('moveTo', 'lineTo'):
                pts.append((i, p[0]))
            elif verb in ('qCurveTo', 'curveTo') and p[-1] is not None:
                pts.append((i, p[-1]))
        drop = set()
        n = len(pts)
        if n >= 4:
            for k in range(n):
                i0, p0 = pts[k-1]; i1, p1 = pts[k]; i2, p2 = pts[(k+1) % n]
                if segs[i1][0] != 'lineTo' or segs[i2][0] != 'lineTo':
                    continue
                v1 = (p0[0]-p1[0], p0[1]-p1[1]); v2 = (p2[0]-p1[0], p2[1]-p1[1])
                l1 = math.hypot(*v1); l2 = math.hypot(*v2)
                if l1 < 1e-6 or l2 < 1e-6:
                    continue
                if (v1[0]*v2[0] + v1[1]*v2[1])/(l1*l2) > min_cos and min(l1, l2) <= max_arm:
                    drop.add(i1)
        for i, (verb, p) in enumerate(segs):
            if i in drop:
                continue
            if verb == 'moveTo':
                pen.moveTo(p[0])
            elif verb == 'lineTo':
                pen.lineTo(p[0])
            elif verb == 'qCurveTo':
                pen.qCurveTo(*p)
            elif verb == 'curveTo':
                pen.curveTo(*p)
            elif verb == 'closePath':
                pen.closePath()
            elif verb == 'endPath':
                pen.endPath()
    return out

NEEDLE_ARM = float(__import__('os').environ.get('STENCIL_NEEDLE_ARM', 12.0))   # Bold uses 30

def clip_needles(path, max_arm=12.0, max_deg=15.0, is_old=None):
    """Remove hairpin vertices where the outline turns back on itself within max_deg and one arm is
    short (<= max_arm): hair-thin ink needles or slits (e.g. a stroke tip grazing another stroke in the
    base design). Works for line and curve arms: the short arm is dropped and the long arm is re-ended at
    the short arm's far point (a shift of at most max_arm units at the end of that segment).
    SolidWorks reports such hairpins as self-intersecting entities after its spline fit.
    is_old: a predicate for points; hairpins whose three points all satisfy it are left alone."""
    min_cos = math.cos(math.radians(max_deg))
    out = pathops.Path(); pen = out.getPen()
    for contour in path.contours:
        segs = list(contour.segments)
        if not segs:
            continue
        if segs[0][0] != 'moveTo':
            # all-off-curve contour (round dot): keep as it is
            for verb, pts in segs:
                getattr(pen, verb)(*pts) if verb not in ('closePath', 'endPath') else getattr(pen, verb)()
            continue
        start = segs[0][1][0]
        edges = []
        bad = False
        for verb, pts in segs[1:]:
            if verb in ('closePath', 'endPath'):
                continue
            if any(q is None for q in pts):
                bad = True; break
            edges.append([verb, list(pts)])
        if bad or len(edges) < 3:
            # all-off-curve or two-segment contours (e.g. a round dot): keep as they are
            for verb, pts in segs:
                getattr(pen, verb)(*pts) if verb not in ('closePath', 'endPath') else getattr(pen, verb)()
            continue
        if math.dist(edges[-1][1][-1], start) > 1e-9:
            edges.append(['lineTo', [start]])
        changed = True; guard = 0
        while changed and guard < 8:
            changed = False; guard += 1
            # purge zero-length line edges (left behind by a previous clip) so hairpins next to them are seen
            edges = [e for i, e in enumerate(edges)
                     if not (e[0] == 'lineTo' and math.dist(edges[i-1][1][-1], e[1][-1]) < 1e-6)]
            n = len(edges)
            if n < 3:
                break
            for k in range(n):
                e_in = edges[k]; e_out = edges[(k+1) % n]; e_prev = edges[k-1]
                P0 = e_prev[1][-1]; V = e_in[1][-1]; P2 = e_out[1][-1]
                c_in = e_in[1][-2] if len(e_in[1]) > 1 else P0
                c_out = e_out[1][0] if len(e_out[1]) > 1 else P2
                t_in = (V[0]-c_in[0], V[1]-c_in[1]); t_out = (c_out[0]-V[0], c_out[1]-V[1])
                l1 = math.hypot(*t_in); l2 = math.hypot(*t_out)
                if l1 < 1e-9 or l2 < 1e-9:
                    continue
                cosang = -(t_in[0]*t_out[0] + t_in[1]*t_out[1]) / (l1*l2)
                if cosang <= min_cos:
                    continue
                if is_old is not None and is_old(P0) and is_old(V) and is_old(P2):
                    continue                                   # a hairpin of the uncut outline
                cin = math.dist(P0, V); cout = math.dist(V, P2)
                if cout <= max_arm and cout <= cin:
                    # drop V and the outgoing arm; the incoming arm now ends at P2
                    e_in[1][-1] = P2
                    del edges[(k+1) % n]
                elif cin <= max_arm:
                    # drop the incoming arm and V; the outgoing arm now starts at P0
                    del edges[k]
                else:
                    continue
                changed = True
                break
        if len(edges) < 2:
            continue  # collapsed to nothing
        s0 = edges[-1][1][-1]
        pen.moveTo(s0)
        for verb, pts in edges:
            getattr(pen, verb)(*pts)
        pen.closePath()
    return out

def contour_points_plain(contour):
    """On-curve/off-curve points of a contour as a polygon (coarse, for area tests)."""
    pts = []
    for verb, p in contour.segments:
        if verb in ('moveTo', 'lineTo'):
            pts.append(p[0])
        elif verb in ('qCurveTo', 'curveTo'):
            pts.extend(q for q in p if q is not None)
    return pts

def topology(path):
    """(n_contours, n_holes, total_abs_area) of a cleaned path."""
    polys = path_polys(path, 1.0)
    return len(polys), sum(1 for _, h in polys if h), sum(abs(signed_area(p)) for p, _ in polys)

def drop_tiny_segments(path, min_len=3.0):
    """Absorb segments (lines and curves) whose chord is shorter than min_len: where a cut edge meets
    the outline next to an existing node, the boolean leaves a 1-2 unit piece of the original segment.
    The piece is removed by moving the end of its neighbour onto the node that is the sharper corner
    (a shift of less than min_len units; control points stay)."""
    out = pathops.Path(); pen = out.getPen()
    def _dir(a, b):
        L = math.dist(a, b)
        return ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L > 1e-9 else None
    def _turn(d1, d2):
        if d1 is None or d2 is None:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))))
    for contour in path.contours:
        segs = list(contour.segments)
        nodes = []; start = None
        for verb, pts in segs:
            if verb == 'moveTo':
                start = pts[0]
            elif verb == 'lineTo':
                nodes.append([pts[0], 'lineTo', []])
            elif verb in ('qCurveTo', 'curveTo'):
                nodes.append([pts[-1], verb, list(pts[:-1])])
        if start is None or len(nodes) < 4 or any(c is None for nd in nodes for c in nd[2]) or any(nd[0] is None for nd in nodes):
            for verb, pts in segs:
                getattr(pen, verb)(*pts)
            continue
        if math.dist(nodes[-1][0], start) > 1e-6:
            nodes.append([start, 'lineTo', []])
        def tangents(k):
            a = nodes[k - 1][0]; b, verb, ctrl = nodes[k]
            chain = [a] + list(ctrl) + [b]
            t0 = next((_dir(chain[0], c) for c in chain[1:] if math.dist(chain[0], c) > 1e-6), None)
            t1 = next((_dir(c, chain[-1]) for c in reversed(chain[:-1]) if math.dist(chain[-1], c) > 1e-6), None)
            return t0, t1
        changed = True
        while changed and len(nodes) > 4:
            changed = False
            n = len(nodes)
            for k in range(n):
                a = nodes[k - 1][0]; b = nodes[k][0]
                L = math.dist(a, b)
                if L >= min_len:
                    continue
                t0, t1 = tangents(k)
                turn_in = _turn(tangents((k - 1) % n)[1], t0)
                turn_out = _turn(t1, tangents((k + 1) % n)[0])
                if turn_in > turn_out:
                    # keep the start node a: the next segment now starts there
                    del nodes[k]
                else:
                    # keep the end node b: the previous segment now ends there
                    nodes[k - 1][0] = b
                    del nodes[k]
                changed = True; break
        pen.moveTo(nodes[-1][0])
        for q, verb, ctrl in nodes:
            if verb == 'lineTo':
                pen.lineTo(q)
            elif verb == 'qCurveTo':
                pen.qCurveTo(*(ctrl + [q]))
            else:
                pen.curveTo(*(ctrl + [q]))
        pen.closePath()
    return out


def drop_steps(path, base, lim=6.0, min_turn=12.0, tol=1.5):
    """Absorb the steps that a cut leaves next to the outline: a NEW segment shorter than lim (not one
    whose two ends are both nodes of the uncut outline `base`) at which the outline turns by more than
    min_turn at both ends (a step or a chamfer, 3-5 units in 麦 響 慣). The end that is a node of the
    uncut outline stays and the cut edge moves onto it; when neither or both are, the sharper corner
    stays as in drop_tiny_segments. Segments that continue smoothly on one side (short remainders of
    a curve) are left alone."""
    old = []
    for contour in base.contours:
        old += [q for q, _, _ in _contour_nodes(contour)]
    is_old = lambda q: any(abs(q[0] - o[0]) <= tol and abs(q[1] - o[1]) <= tol for o in old)
    out = pathops.Path(); pen = out.getPen()
    def _dir(a, b):
        L = math.dist(a, b)
        return ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L > 1e-9 else None
    def _turn(d1, d2):
        if d1 is None or d2 is None:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))))
    for contour in path.contours:
        segs = list(contour.segments)
        nodes = []; start = None
        for verb, pts in segs:
            if verb == 'moveTo':
                start = pts[0]
            elif verb == 'lineTo':
                nodes.append([pts[0], 'lineTo', []])
            elif verb in ('qCurveTo', 'curveTo'):
                nodes.append([pts[-1], verb, list(pts[:-1])])
        if start is None or len(nodes) < 4 or any(c is None for nd in nodes for c in nd[2]) or any(nd[0] is None for nd in nodes):
            for verb, pts in segs:
                getattr(pen, verb)(*pts)
            continue
        if math.dist(nodes[-1][0], start) > 1e-6:
            nodes.append([start, 'lineTo', []])
        def tangents(k):
            a = nodes[k - 1][0]; b, verb, ctrl = nodes[k]
            chain = [a] + list(ctrl) + [b]
            t0 = next((_dir(chain[0], c) for c in chain[1:] if math.dist(chain[0], c) > 1e-6), None)
            t1 = next((_dir(c, chain[-1]) for c in reversed(chain[:-1]) if math.dist(chain[-1], c) > 1e-6), None)
            return t0, t1
        changed = True
        while changed and len(nodes) > 4:
            changed = False
            n = len(nodes)
            for k in range(n):
                a = nodes[k - 1][0]; b = nodes[k][0]
                L = math.dist(a, b)
                if L >= lim or L < 1e-9 or nodes[k][1] != 'lineTo':
                    continue
                oa, ob = is_old(a), is_old(b)
                if oa and ob:
                    continue                                   # part of the design
                t0, t1 = tangents(k)
                turn_in = _turn(tangents((k - 1) % n)[1], t0)
                turn_out = _turn(t1, tangents((k + 1) % n)[0])
                if min(turn_in, turn_out) <= min_turn:
                    continue                                   # a smooth remainder, not a step
                keep_a = oa if oa != ob else (turn_in > turn_out)
                if keep_a:
                    del nodes[k]                               # the next segment now starts at a
                else:
                    nodes[k - 1][0] = b; del nodes[k]          # the previous segment now ends at b
                changed = True; break
        pen.moveTo(nodes[-1][0])
        for q, verb, ctrl in nodes:
            if verb == 'lineTo':
                pen.lineTo(q)
            elif verb == 'qCurveTo':
                pen.qCurveTo(*(ctrl + [q]))
            else:
                pen.curveTo(*(ctrl + [q]))
        pen.closePath()
    return out


_HEAL_DEBUG = bool(__import__('os').environ.get('STENCIL_HEAL_DEBUG'))
HEAL_LOG = []          # pieces heal_cut_edges could not remove in the last finalize calls: (kind, point, length)


def finalize_record(rec, **kw):
    """finalize() for a record of batch.py: glyphs cut by the revised engine are finalized against their uncut
    outline (steps and, with the option `heal`, all short pieces beside the cuts are removed); everything else
    exactly as in the first release."""
    path = segs_to_path(rec['segs'])
    base = segs_to_path(rec['orig_segs']) if rec.get('engine') == 'corners' and rec.get('chosen') else None
    return finalize(path, base=base, **kw)


def _path_nodes(contour):
    """(nodes, ok): nodes[k] = [end point, verb, controls] for the segments of a contour, the implicit
    closing line included; ok is False for contours that cannot be edited node by node."""
    nodes = []; start = None
    for verb, pts in contour.segments:
        if verb == 'moveTo':
            start = pts[0]
        elif verb == 'lineTo':
            nodes.append([pts[0], 'lineTo', []])
        elif verb in ('qCurveTo', 'curveTo'):
            nodes.append([pts[-1], verb, list(pts[:-1])])
    if start is None or len(nodes) < 4 or any(c is None for nd in nodes for c in nd[2]) or any(nd[0] is None for nd in nodes):
        return nodes, False
    if math.dist(nodes[-1][0], start) > 1e-6:
        nodes.append([start, 'lineTo', []])
    return nodes, True


def _emit_nodes(pen, nodes):
    pen.moveTo(nodes[-1][0])
    for q, verb, ctrl in nodes:
        if verb == 'lineTo':
            pen.lineTo(q)
        elif verb == 'qCurveTo':
            pen.qCurveTo(*(list(ctrl) + [q]))
        else:
            pen.curveTo(*(list(ctrl) + [q]))
    pen.closePath()


def _blossom(pts, ts):
    cur = list(pts)
    for t in ts:
        cur = [(cur[i][0] + t * (cur[i + 1][0] - cur[i][0]), cur[i][1] + t * (cur[i + 1][1] - cur[i][1])) for i in range(len(cur) - 1)]
    return cur[0]


def _bez_sub(pts, t0, t1):
    """Control points of the part [t0, t1] of the Bezier `pts` (t outside 0..1 extrapolates the same curve)."""
    n = len(pts) - 1
    return [_blossom(pts, [t0] * (n - i) + [t1] * i) for i in range(n + 1)]


def _retrim(nodes, j, q, d, start, reach=0.6):
    """Segment j of `nodes` re-ended where it (or its continuation) crosses the line through q with
    direction d: (new end point, new controls) for its start (start=True) or its end, or None when the
    crossing is not within `reach` of that end (as a share of the segment) or the segment cannot be
    handled. The far end of the segment stays."""
    n = len(nodes)
    p0 = nodes[(j - 1) % n][0]; p1, verb, ctrl = nodes[j % n]
    if verb == 'qCurveTo' and len(ctrl) != 1:
        return None
    pts = [p0] + list(ctrl) + [p1]
    f = lambda t: (lambda x: (x[0] - q[0]) * d[1] - (x[1] - q[1]) * d[0])(_blossom(pts, [t] * (len(pts) - 1)))
    t_end = 0.0 if start else 1.0
    best = None; N = 60
    prev_t = t_end - reach; prev_f = f(prev_t)
    for i in range(1, N + 1):
        t = t_end - reach + 2.0 * reach * i / N
        ft = f(t)
        if prev_f == 0.0 or prev_f * ft < 0.0:
            lo, hi, flo = prev_t, t, prev_f
            for _ in range(40):
                mid = 0.5 * (lo + hi); fm = f(mid)
                if flo * fm <= 0.0:
                    hi = mid
                else:
                    lo, flo = mid, fm
            tc = 0.5 * (lo + hi)
            if best is None or abs(tc - t_end) < abs(best - t_end):
                best = tc
        prev_t, prev_f = t, ft
    if best is None:
        return None
    sub = _bez_sub(pts, best, 1.0) if start else _bez_sub(pts, 0.0, best)
    return (sub[0] if start else sub[-1]), [tuple(x) for x in sub[1:-1]]


def heal_cut_edges(path, base, lim=12.0, smooth_deg=14.0, max_dev=2.0, tol=1.5, log=None, min_gap=30.0):
    """Remove the short pieces (chord < lim) that a cut leaves in the outline. Only NEW pieces are touched
    (not both ends nodes of the uncut outline `base`), and a segment that lies on the uncut outline is never
    moved sideways: it is only extended or trimmed along itself.
    remainder: the piece continues one of its neighbours smoothly (turn <= smooth_deg): a few units of an
        original segment between a node and the cut edge, or the straight run-out of a fitted face. The
        neighbour is extended over it (sideways error at most max_dev; a curve is continued along itself).
    step: the outline turns at both ends. In this order: (1) the two neighbours are extended or trimmed
        along themselves until they meet; (2) a neighbour that is a cut edge is moved parallel to itself
        onto the other end of the piece, its far end sliding along the segment it meets; (3) a cut edge is
        re-ended on that end (a fitted curve with its control point).
    A cut edge is not moved into its gap when that would leave the gap narrower than min_gap (the floor of
    the bridge width) in front of it.
    Before the single pieces, per contour:
    snap: a new node within 3 units of a node of the uncut outline, at the end of a short piece whose other
        end is such a node, is moved onto it (the piece is then a segment of the design again: a 9-unit end
        face shortened by 2 units, 耆).
    excursion: the outline leaves a straight (or smoothly continuing) run, stays within lim of it for at
        most four new nodes and comes back onto it: a nub of a cut stroke left on the face it met, a bite
        of the cut into that face, a stub thinner than lim (☝ 偐 羃). The run goes straight across.
    needle: a tip sharper than 15 degrees whose base is at most lim wide is dropped; a tip sharper than 35
        degrees is cut off by extending the edge beside it by at most lim (☜ 瘉 奩 黷).
    chain: two or three consecutive short pieces between two long segments are replaced by the point
        where those segments meet (宰 戴).
    log: a list that receives (kind, point, length) for every piece that could not be removed."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    _polys = path_polys(path, 0.05)
    _outer = [Polygon(pts).buffer(0) for pts, h in _polys if not h and len(pts) >= 3]
    _holes = [Polygon(pts).buffer(0) for pts, h in _polys if h and len(pts) >= 3]
    ink_now = unary_union(_outer) if _outer else None
    if ink_now is not None and _holes:
        ink_now = ink_now.difference(unary_union(_holes))
    def narrows(pts, at_start, v):
        """The segment with control polygon `pts` is displaced by v at its start (at_start) or its end:
        True when that pushes it into a gap that would become narrower than min_gap."""
        if ink_now is None:
            return False
        deg = len(pts) - 1
        t = 0.15 if at_start else 0.85
        m = _blossom(pts, [t] * deg); m2 = _blossom(pts, [t + 0.02] * deg)
        ex, ey = m2[0] - m[0], m2[1] - m[1]; el = math.hypot(ex, ey)
        if el < 1e-9:
            return False
        nx, ny = -ey / el, ex / el
        if ink_now.contains(Point(m[0] + 1.0 * nx, m[1] + 1.0 * ny)):
            nx, ny = -nx, -ny                                  # n points to the white side
        d = v[0] * nx + v[1] * ny
        if d <= 0.5:
            return False                                       # the edge retreats: the gap widens
        ray = LineString([(m[0] + 1.0 * nx, m[1] + 1.0 * ny), (m[0] + 200.0 * nx, m[1] + 200.0 * ny)])
        hit = ray.intersection(ink_now)
        if hit.is_empty:
            return False
        gap = 1.0 + Point(m[0] + 1.0 * nx, m[1] + 1.0 * ny).distance(hit)
        return gap - d < min_gap
    old = []
    for contour in base.contours:
        old += [q for q, _, _ in _contour_nodes(contour)]
    is_old = lambda q: any(abs(q[0] - o[0]) <= tol and abs(q[1] - o[1]) <= tol for o in old)
    rings = [LineString(list(pts) + [pts[0]]) for pts, _h in path_polys(base, 0.05) if len(pts) >= 3]
    base_line = unary_union(rings) if rings else None
    on_base = lambda q: base_line is not None and base_line.distance(Point(q)) <= 0.8
    out = pathops.Path(); pen = out.getPen()
    def _dir(a, b):
        L = math.dist(a, b)
        return ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L > 1e-9 else None
    def _ang(d1, d2):
        if d1 is None or d2 is None:
            return 0.0
        return math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
    def _line_x(p, d, q, e):
        """Intersection of the lines p + s d and q + u e, or None when they are parallel."""
        den = d[0] * e[1] - d[1] * e[0]
        if abs(den) < 1e-6:
            return None
        u = -((p[0] - q[0]) * d[1] - (p[1] - q[1]) * d[0]) / den
        return (q[0] + u * e[0], q[1] + u * e[1])
    for contour in path.contours:
        nodes, ok = _path_nodes(contour)
        if not ok:
            for verb, pts in contour.segments:
                getattr(pen, verb)(*pts)
            continue
        def seg_pts(k):
            n = len(nodes)
            return [nodes[(k - 1) % n][0]] + list(nodes[k % n][2]) + [nodes[k % n][0]]
        def tangents(k):
            chain = seg_pts(k)
            t0 = next((_dir(chain[0], c) for c in chain[1:] if math.dist(chain[0], c) > 1e-6), None)
            t1 = next((_dir(c, chain[-1]) for c in reversed(chain[:-1]) if math.dist(chain[-1], c) > 1e-6), None)
            return t0, t1
        def seg_on_base(k):
            # the segment arriving at node k is a piece of the uncut outline
            pts = seg_pts(k)
            if nodes[k % len(nodes)][1] == 'qCurveTo' and len(pts) != 3:
                return True
            return all(on_base(_blossom(pts, [t] * (len(pts) - 1))) for t in (0.25, 0.5, 0.75))
        def seg_len(k):
            pts = seg_pts(k)
            return math.dist(pts[0], pts[-1])
        skip = set(); guard = 0; phase = 0; touched = False

        def rot(i):
            i %= len(nodes)
            nodes[:] = nodes[i:] + nodes[:i]

        def is_new_short(k):
            a_ = nodes[(k - 1) % len(nodes)][0]; b_ = nodes[k % len(nodes)][0]
            L_ = math.dist(a_, b_)
            return 1e-9 < L_ < lim and not (is_old(a_) and is_old(b_))

        def fix_excursion(both=True, tip=None):
            n = len(nodes)
            if n < 7:
                return False
            for s_ in range(n):
                a_ = nodes[s_ - 1][0]; tP = tangents(s_ - 1)[1]
                if tP is None:
                    continue
                for cnt in range(1, 5):
                    e_ = s_ + cnt                              # the run ends at node e_ (= d); interior s_ .. e_-1
                    inner = [nodes[j % n][0] for j in range(s_, e_)]
                    if all(is_old(q) for q in inner):
                        continue                               # nothing new inside: the design
                    d_ = nodes[e_ % n][0]; span = math.dist(a_, d_)
                    if span < 4.0 or span > 150.0:
                        continue
                    chord = _dir(a_, d_); tQ = tangents(e_ + 1)[0]
                    if tQ is None:
                        continue
                    # the run leaves a line and comes back onto it: in line with the segment before it, or
                    # with the segment after it (the other end may be a corner)
                    in_p = abs(_ang(tP, chord)) <= 8.0; in_q = abs(_ang(chord, tQ)) <= 8.0
                    if not (in_p and in_q) and (both or not (in_p or in_q)):
                        continue
                    pts = []
                    for j in range(s_, e_ + 1):
                        pts += list(nodes[j % n][2]) + [nodes[j % n][0]]
                    dev = max(abs((q[0] - a_[0]) * chord[1] - (q[1] - a_[1]) * chord[0]) for q in pts[:-1])
                    has_short = any(is_new_short(j) for j in range(s_, e_ + 1))
                    if tip is None and not has_short:
                        continue                               # only where there is a short piece to remove,
                    if tip is not None and not any(math.dist(q, tip) < 1e-6 for q in inner):
                        continue                               # or around a sharp tip (fix_needle)
                    if dev > (1.25 * lim if has_short else 0.75 * lim) or dev < 1.5:
                        continue
                    turns = [abs(_ang(tangents(j)[1], tangents(j + 1)[0])) for j in range(s_ - 1, e_ + 1)
                             if tangents(j)[1] is not None and tangents(j + 1)[0] is not None]
                    if not turns or max(turns) < 25.0:
                        continue                               # a smooth bulge (a fitted face), not a step
                    if any(seg_len(j) >= 2.0 * lim and seg_on_base(j) for j in range(s_, e_ + 1)):
                        continue                               # a long piece of the uncut outline is never swung aside
                    if _HEAL_DEBUG:
                        print('heal: excursion %s .. %s (%d nodes, depth %.1f) straightened' % (a_, d_, cnt, dev))
                    rot(s_ - 1)                                # a at index 0, interior 1 .. cnt, d at cnt + 1
                    nodes[cnt + 1][1] = 'lineTo'; nodes[cnt + 1][2] = []
                    del nodes[1:cnt + 1]
                    return True
            return False

        def fix_needle():
            n = len(nodes)
            if n < 7:
                return False
            for k_ in range(n):
                P0 = nodes[k_ - 1][0]; V = nodes[k_][0]; P2 = nodes[(k_ + 1) % n][0]
                if is_old(P0) and is_old(V) and is_old(P2):
                    continue
                t_i = tangents(k_)[1]; t_o = tangents(k_ + 1)[0]
                if t_i is None or t_o is None:
                    continue
                tip = 180.0 - abs(_ang(t_i, t_o))
                if tip >= 35.0:
                    continue
                if tip < 15.0 and math.dist(P0, P2) <= lim and math.dist(P0, P2) > 1e-6:
                    if _HEAL_DEBUG:
                        print('heal: needle at %s (tip %.0f, base %.1f) dropped' % (V, tip, math.dist(P0, P2)))
                    rot(k_ - 1)                                # P0 0, V 1, P2 2
                    nodes[2][1] = 'lineTo'; nodes[2][2] = []
                    del nodes[1]
                    return True
                best = None
                P3 = nodes[(k_ + 2) % n][0]; Pm = nodes[k_ - 2][0]
                if nodes[(k_ + 2) % n][1] == 'lineTo' and math.dist(P2, P3) > 1e-6:
                    db = _dir(P3, P2)
                    new = _retrim(nodes, k_, P2, db, start=False, reach=1.0)
                    if new is not None:
                        X = new[0]; ext = math.dist(X, P2)
                        if (X[0] - P2[0]) * db[0] + (X[1] - P2[1]) * db[1] > 0 and ext <= lim \
                                and math.dist(P0, X) <= math.dist(P0, V) + 1.0 and math.dist(X, V) <= math.dist(P0, V) + 1.0:
                            best = ('b', ext, new)
                if nodes[k_ - 1][1] == 'lineTo' and math.dist(Pm, P0) > 1e-6:
                    dc = _dir(Pm, P0)
                    new = _retrim(nodes, k_ + 1, P0, dc, start=True, reach=1.0)
                    if new is not None:
                        X = new[0]; ext = math.dist(X, P0)
                        if (X[0] - P0[0]) * dc[0] + (X[1] - P0[1]) * dc[1] > 0 and ext <= lim \
                                and math.dist(P2, X) <= math.dist(P2, V) + 1.0 and math.dist(X, V) <= math.dist(P2, V) + 1.0 \
                                and (best is None or ext < best[1]):
                            best = ('c', ext, new)
                if best is None:
                    if fix_excursion(both=True, tip=V):        # a thin stub with slanted ends (羃)
                        return True
                    continue
                if _HEAL_DEBUG:
                    print('heal: tip at %s (%.0f deg) cut off by extending the %s edge by %.1f' % (V, tip, 'next' if best[0] == 'b' else 'previous', best[1]))
                rot(k_ - 2)                                    # Pm 0, P0 1, V 2, P2 3, P3 4
                X, ctrl = best[2]
                if best[0] == 'b':
                    nodes[2][0] = X; nodes[2][2] = ctrl        # the arm P0 -> V now ends at X
                    del nodes[3]                               # P2: the next edge now runs X -> P3
                    if math.dist(nodes[1][0], X) < 1.5:
                        del nodes[2]
                else:
                    nodes[3][2] = ctrl                         # the arm V -> P2 now starts at X
                    nodes[1][0] = X                            # the previous edge now ends at X
                    del nodes[2]                               # V
                return True
            return False

        def fix_chain(wide=False):
            n = len(nodes)
            if n < 8:
                return False
            def is_new_piece(k, top):
                a2 = nodes[(k - 1) % n][0]; b2 = nodes[k % n][0]; L2 = math.dist(a2, b2)
                return 1e-9 < L2 < top and not (is_old(a2) and is_old(b2))
            top = 2.2 * lim if wide else lim
            for k_ in range(n):
                if not is_new_short(k_):
                    continue
                for s_, m in ((k_, 2), (k_ - 1, 2), (k_ - 1, 3), (k_, 3), (k_ - 2, 3)):
                    if not all(is_new_piece(s_ + i_, top) for i_ in range(m)):
                        continue
                    if not wide and (is_new_short(s_ - 1) or is_new_short(s_ + m)):
                        continue                               # the whole run of short pieces, not a part of it
                    a_ = nodes[(s_ - 1) % n][0]; d_ = nodes[(s_ + m - 1) % n][0]
                    kp_ = (s_ - 1) % n; kq_ = (s_ + m) % n
                    tP = tangents(kp_)[1]; tQ = tangents(kq_)[0]
                    if tP is None or tQ is None:
                        continue
                    p_ln = nodes[kp_][1] == 'lineTo'; q_ln = nodes[kq_][1] == 'lineTo'
                    X = None; ctrl_p = ctrl_q = None
                    if p_ln and q_ln:
                        X = _line_x(a_, tP, d_, tQ)
                    elif p_ln:
                        new = _retrim(nodes, kq_, a_, tP, start=True, reach=min(1.5, 2.0 * lim / max(seg_len(kq_), 1e-6)))
                        if new is not None:
                            X, ctrl_q = new
                    elif q_ln:
                        new = _retrim(nodes, kp_, d_, tQ, start=False, reach=min(1.5, 2.0 * lim / max(seg_len(kp_), 1e-6)))
                        if new is not None:
                            X, ctrl_p = new
                    if X is None:
                        continue
                    pp = nodes[(s_ - 2) % n][0]; cc = nodes[kq_][0]
                    if math.dist(X, a_) > 1.5 * lim or math.dist(X, d_) > 1.5 * lim or math.dist(pp, X) < 0.3 * math.dist(pp, a_) \
                            or math.dist(X, cc) < 0.3 * math.dist(d_, cc) \
                            or (X[0] - pp[0]) * tP[0] + (X[1] - pp[1]) * tP[1] <= 0 or (cc[0] - X[0]) * tQ[0] + (cc[1] - X[1]) * tQ[1] <= 0:
                        continue
                    if ink_now is not None and abs(_ang(tP, tQ)) > 110.0 \
                            and not ink_now.contains(Point((a_[0] + d_[0] + X[0]) / 3.0, (a_[1] + d_[1] + X[1]) / 3.0)):
                        continue
                    if _HEAL_DEBUG:
                        print('heal: chain of %d pieces %s .. %s closed at %s' % (m, a_, d_, (round(X[0], 1), round(X[1], 1))))
                    rot(s_ - 2)                                # pp 0, a 1, chain nodes 2 .. m + 1 (d = m + 1), Q m + 2
                    nodes[1][0] = X
                    if ctrl_p is not None:
                        nodes[1][2] = ctrl_p
                    if ctrl_q is not None:
                        nodes[m + 2][2] = ctrl_q
                    del nodes[2:m + 2]
                    return True
            return False

        def fix_tiny():
            """A new piece of at most 6 units with one end on a node of the uncut outline: the new end goes onto
            that node (lines and curves; drop_steps does this for line steps only)."""
            n = len(nodes)
            if n < 6:
                return False
            for k_ in range(n):
                a2 = nodes[k_ - 1][0]; b2 = nodes[k_][0]; L2 = math.dist(a2, b2)
                if not (1e-9 < L2 <= 6.0) or is_old(a2) == is_old(b2):
                    continue
                if is_old(b2):
                    if math.dist(nodes[k_ - 2][0], a2) < 4.0 * L2:
                        continue
                    if _HEAL_DEBUG:
                        print('heal: tiny piece %s -> %s merged into its end node' % (a2, b2))
                    rot(k_ - 2)                                # .. 0, a 1, b 2
                    nodes[1][0] = b2; del nodes[2]
                else:
                    if math.dist(b2, nodes[(k_ + 1) % n][0]) < 4.0 * L2:
                        continue
                    if _HEAL_DEBUG:
                        print('heal: tiny piece %s -> %s merged into its start node' % (a2, b2))
                    rot(k_ - 1)                                # a 0, b 1, next 2
                    del nodes[1]
                return True
            return False

        def fix_merge():
            """Two consecutive pieces, one of them short and new, meeting at a new node at a small angle, become
            one cubic with their outer tangents (two pieces of a tip rounding, 僘)."""
            n = len(nodes)
            if n < 7:
                return False
            for k_ in range(n):
                if not is_new_short(k_):
                    continue
                for s_ in (k_ - 1, k_):                       # merge segments s_ and s_ + 1 (joint = node s_)
                    mid = nodes[s_ % n][0]
                    if is_old(mid):
                        continue
                    p0 = nodes[(s_ - 1) % n][0]; p3 = nodes[(s_ + 1) % n][0]
                    L01 = math.dist(p0, mid); L12 = math.dist(mid, p3); L = math.dist(p0, p3)
                    if L < lim or max(L01, L12) > 3.0 * lim:
                        continue
                    t0_ = tangents(s_)[0]; t1_ = tangents(s_ + 1)[1]; tj_a = tangents(s_)[1]; tj_b = tangents(s_ + 1)[0]
                    if None in (t0_, t1_, tj_a, tj_b) or abs(_ang(tj_a, tj_b)) > 20.0 or abs(_ang(t0_, t1_)) > 75.0:
                        continue
                    c1 = (p0[0] + t0_[0] * L / 3.0, p0[1] + t0_[1] * L / 3.0); c2 = (p3[0] - t1_[0] * L / 3.0, p3[1] - t1_[1] * L / 3.0)
                    cub = [p0, c1, c2, p3]
                    dev = min(math.dist(mid, _blossom(cub, [t / 40.0] * 3)) for t in range(41))
                    if dev > max_dev:
                        continue
                    if _HEAL_DEBUG:
                        print('heal: two pieces at %s merged into one curve (off by %.1f)' % (mid, dev))
                    rot(s_ - 1)                                # p0 0, mid 1, p3 2
                    nodes[2][1] = 'curveTo'; nodes[2][2] = [c1, c2]
                    del nodes[1]
                    return True
            return False

        def fix_snap():
            """A short new piece that nothing else removed, with one end on a node of the uncut outline and the
            other within 4 units of another such node: that end goes onto the node (the piece is a segment of
            the design again). Not when that would swing a long segment of the uncut outline sideways."""
            n = len(nodes)
            for i_ in range(n):
                q = nodes[i_][0]
                if is_old(q) or not old:
                    continue
                pv = nodes[i_ - 1][0]; nx_ = nodes[(i_ + 1) % n][0]
                if not ((math.dist(pv, q) < lim and is_old(pv)) or (math.dist(nx_, q) < lim and is_old(nx_))):
                    continue
                near = min(old, key=lambda o: (o[0] - q[0]) ** 2 + (o[1] - q[1]) ** 2)
                if math.dist(near, q) > 4.0 or math.dist(near, pv) < 1e-6 or math.dist(near, nx_) < 1e-6:
                    continue
                ok_ = True
                for j_, far_ in ((i_, pv), ((i_ + 1) % n, nx_)):
                    L_ = math.dist(far_, q)
                    if L_ >= lim and seg_on_base(j_):
                        perp = abs((near[0] - q[0]) * (far_[1] - q[1]) - (near[1] - q[1]) * (far_[0] - q[0])) / L_
                        if perp > 0.8:
                            ok_ = False
                if not ok_:
                    continue
                if _HEAL_DEBUG:
                    print('heal: node %s snapped to the outline node %s' % (q, near))
                nodes[i_][0] = (float(near[0]), float(near[1]))
                return True
            return False

        while len(nodes) > 4 and guard < 300:
            guard += 1; changed = False
            if phase == 1 and (fix_chain() or fix_excursion(both=True) or fix_needle()):
                phase = 0; touched = True
                continue
            n = len(nodes)
            for k in range(n):
                a = nodes[k - 1][0]; b = nodes[k][0]
                L = math.dist(a, b)
                if L >= lim or L < 1e-9 or (a, b) in skip:
                    continue
                oa, ob = is_old(a), is_old(b)
                if oa and ob:
                    continue                                   # part of the design
                kp = (k - 1) % n; kq = (k + 1) % n
                t0, t1 = tangents(k)
                t_in = tangents(kp)[1]; t_out = tangents(kq)[0]
                if t0 is None or t1 is None or t_in is None or t_out is None:
                    continue
                turn_a = _ang(t_in, t0); turn_b = _ang(t1, t_out)
                ch = _dir(a, b)
                p = nodes[k - 2][0]; c = nodes[kq][0]
                p_line = nodes[kp][1] == 'lineTo'; q_line = nodes[kq][1] == 'lineTo'
                is_rem = min(abs(turn_a), abs(turn_b)) <= smooth_deg
                if _HEAL_DEBUG and phase == (0 if is_rem else 1):
                    print('heal: piece %s -> %s L %.1f old %s/%s turns %+.0f/%+.0f prev %s %.0f next %s %.0f' % (
                        a, b, L, oa, ob, turn_a, turn_b, nodes[kp][1], math.dist(p, a), nodes[kq][1], math.dist(b, c)))
                if is_rem:
                    # remainder: extend the smooth neighbour over the piece
                    order = ('prev', 'next') if abs(turn_a) <= abs(turn_b) else ('next', 'prev')
                    done = False
                    for side in order:
                        if side == 'prev' and abs(turn_a) <= smooth_deg:
                            dev = L * abs(math.sin(math.radians(_ang(t_in, ch))))
                            if dev <= (max_dev if math.dist(p, a) >= L else (1.0 if math.dist(p, a) >= 0.5 * L else -1.0)):
                                nodes[kp][0] = b; del nodes[k]; done = True; break
                            if not p_line:
                                # continue the curve along itself up to the far end of the piece
                                new = _retrim(nodes, kp, b, (-t1[1], t1[0]), start=False, reach=1.5)
                                if new is not None and math.dist(new[0], b) <= 1.0:
                                    nodes[kp][0] = b; nodes[kp][2] = new[1]; del nodes[k]; done = True; break
                        if side == 'next' and abs(turn_b) <= smooth_deg:
                            dev = L * abs(math.sin(math.radians(_ang(ch, t_out))))
                            if dev <= (max_dev if math.dist(b, c) >= L else (1.0 if math.dist(b, c) >= 0.5 * L else -1.0)):
                                del nodes[k]; done = True; break
                            if not q_line:
                                new = _retrim(nodes, kq, a, (-t0[1], t0[0]), start=True, reach=1.5)
                                if new is not None and math.dist(new[0], a) <= 1.0:
                                    nodes[kq][2] = new[1]; del nodes[k]; done = True; break
                    if done:
                        changed = True; break
                    # not absorbed: treated as a step below (its sharp end may still be re-ended)
                if phase == 0:
                    continue                                   # steps after all remainders are absorbed
                # step: the outline turns at both ends of the piece
                done = False
                # (1) the neighbours meet when extended or trimmed along themselves
                X = None; ctrl_p = ctrl_q = None
                if p_line and q_line:
                    X = _line_x(a, t_in, b, t_out)
                elif p_line:
                    new = _retrim(nodes, kq, a, t_in, start=True, reach=min(1.5, 2.0 * lim / max(seg_len(kq), 1e-6)))
                    if new is not None:
                        X, ctrl_q = new
                elif q_line:
                    new = _retrim(nodes, kp, b, t_out, start=False, reach=min(1.5, 2.0 * lim / max(seg_len(kp), 1e-6)))
                    if new is not None:
                        X, ctrl_p = new
                if X is not None and ink_now is not None and abs(turn_a) + abs(turn_b) > 110.0                         and not ink_now.contains(Point((a[0] + b[0] + X[0]) / 3.0, (a[1] + b[1] + X[1]) / 3.0)):
                    X = None                                   # would grow a blunt ink tip into a point
                far = 1.5 * lim
                if X is not None and ink_now is not None and max(math.dist(X, a), math.dist(X, b)) > far \
                        and ink_now.contains(Point((a[0] + b[0] + X[0]) / 3.0, (a[1] + b[1] + X[1]) / 3.0)):
                    far = 6.0 * lim                            # a fin thinner than lim: cut off back to its root
                if X is not None and math.dist(X, a) <= far and math.dist(X, b) <= far \
                        and math.dist(p, X) >= max(L, 0.3 * math.dist(p, a)) and math.dist(X, c) >= max(L, 0.3 * math.dist(b, c)) \
                        and (X[0] - p[0]) * t_in[0] + (X[1] - p[1]) * t_in[1] > 0 and (c[0] - X[0]) * t_out[0] + (c[1] - X[1]) * t_out[1] > 0:
                    nodes[kp][0] = X
                    if ctrl_p is not None:
                        nodes[kp][2] = ctrl_p
                    if ctrl_q is not None:
                        nodes[kq][2] = ctrl_q
                    del nodes[k]; done = True
                if not done:
                    # (2), (3) move a neighbour that is a cut edge onto the other end of the piece
                    p_orig = seg_on_base(kp); q_orig = seg_on_base(kq)
                    opts = []
                    if not q_orig and not ob:
                        opts.append(('q', math.dist(b, c)))
                    if not p_orig and not oa:
                        opts.append(('p', math.dist(p, a)))
                    opts.sort(key=lambda o: o[1])
                    for which, _len in opts:
                        if _len < 1.5 * L:
                            continue
                        if which == 'q':
                            # Q = (b -> c) now starts at a
                            j = (k + 2) % n
                            if narrows(seg_pts(kq), True, (a[0] - b[0], a[1] - b[1])):
                                continue
                            new = _retrim(nodes, j, a, t_out, start=True) if (q_line and not is_old(c)) else None
                            if new is not None and math.dist(new[0], c) <= 2.0 * lim and math.dist(new[0], nodes[j][0]) >= L:
                                nodes[kq][0] = new[0]; nodes[j][2] = new[1]
                                del nodes[k]; done = True; break
                            if _len >= (4.0 if q_line else 2.5) * L:
                                if not q_line and nodes[kq][2]:
                                    c0 = nodes[kq][2][0]
                                    nodes[kq][2] = [(c0[0] + a[0] - b[0], c0[1] + a[1] - b[1])] + list(nodes[kq][2][1:])
                                del nodes[k]; done = True; break
                        else:
                            # P = (p -> a) now ends at b
                            j = (k - 2) % n
                            if narrows(seg_pts(kp), False, (b[0] - a[0], b[1] - a[1])):
                                continue
                            new = _retrim(nodes, j, b, t_in, start=False) if (p_line and not is_old(p)) else None
                            if new is not None and math.dist(new[0], p) <= 2.0 * lim and math.dist(new[0], nodes[(j - 1) % n][0]) >= L:
                                nodes[j][0] = new[0]; nodes[j][2] = new[1]
                                nodes[kp][0] = b; del nodes[k]; done = True; break
                            if _len >= (4.0 if p_line else 2.5) * L:
                                if not p_line and nodes[kp][2]:
                                    c1 = nodes[kp][2][-1]
                                    nodes[kp][2] = list(nodes[kp][2][:-1]) + [(c1[0] + b[0] - a[0], c1[1] + b[1] - a[1])]
                                nodes[kp][0] = b; del nodes[k]; done = True; break
                if done:
                    changed = True; break
                skip.add((a, b))
                if log is not None:
                    log.append(('remainder' if is_rem else 'step', a, L))
            if changed:
                phase = 0; touched = True
            elif phase == 0:
                phase = 1
            elif fix_excursion(both=False) or fix_chain(wide=True) or fix_merge() or fix_snap() or fix_tiny():
                phase = 0; touched = True
            else:
                break
        if touched:
            # the new points are intersections: back to integer coordinates (TrueType)
            for nd in nodes:
                nd[0] = _r(nd[0]); nd[2] = [_r(c) for c in nd[2]]
        _emit_nodes(pen, nodes)
    return out


def finalize(path, min_len=2.0, needle_arm=None, base=None):
    """Round, drop micro-segments, re-simplify, weld any self-touch created by rounding;
    return (final_path, report dict). base: the uncut outline; with it, steps under 6 units that a cut
    left next to the outline are absorbed (drop_steps)."""
    from .weld import problems, weld_guarded
    before = topology(path)
    p = round_path(path)
    p.simplify(fix_winding=True, keep_starting_points=False)
    # rounding can create self-touching rings or hair gaps: weld them (never closing a bridge),
    # then round/clean once more
    for _ in range(2):
        if not problems(p, 3.0):
            break
        p, _n = weld_guarded(p, min_gap=3.0, r=10.0)
        if not _n:
            break
        p = round_path(p)
        p.simplify(fix_winding=True, keep_starting_points=False)
    # the boolean/simplify steps can leave 1-unit steps where a cut edge meets a rounded vertex;
    # clean those last (no further simplify, which would re-introduce them)
    p = drop_short_lines(p, min_len)
    p = collapse_hairpins(p)
    p = clip_needles(p, max_arm=needle_arm or NEEDLE_ARM)
    p = drop_short_lines(p, min_len)
    p = merge_collinear(p)
    p = drop_tiny_segments(p)
    if base is not None:
        from .corners import OPTS as _COPTS
        heal = float(_COPTS.get('heal') or 0.0)
        if heal:
            # slivers a cut leaves on a face (one leg of a junction fillet: 陰 躑), arms up to heal + 6
            _old = [q for contour in base.contours for q, _, _ in _contour_nodes(contour)]
            p = clip_needles(p, max_arm=max(needle_arm or NEEDLE_ARM, heal + 6.0),
                             is_old=lambda q: any(abs(q[0] - o[0]) <= 1.5 and abs(q[1] - o[1]) <= 1.5 for o in _old))
            p = merge_collinear(p)
            p = heal_cut_edges(p, base, lim=heal, log=HEAL_LOG)
            # a strip thinner than `heal` whose two ends were short pieces has been closed to a line
            p = collapse_hairpins(p, max_arm=1e9, min_cos=0.9995)
            p = drop_short_lines(p, min_len)
            p = merge_collinear(p)
        p = drop_steps(p, base)
    p = merge_collinear(p)
    after = topology(p)
    rep = {'contours_before': before[0], 'holes_before': before[1], 'contours_after': after[0], 'holes_after': after[1],
           'area_change': abs(after[2] - before[2]) / max(before[2], 1.0)}
    # tiny contours / short segments remaining
    min_seg = float('inf'); tiny = 0
    for contour in p.contours:
        cur = None
        for verb, pts in contour.segments:
            if verb in ('moveTo', 'lineTo'):
                q = pts[0]
                if cur is not None and verb == 'lineTo':
                    min_seg = min(min_seg, math.dist(cur, q))
                cur = q
            elif verb == 'qCurveTo':
                cur = pts[-1] if pts[-1] is not None else cur
    for pts, h in path_polys(p, 1.0):
        if abs(signed_area(pts)) < 150:
            tiny += 1
    rep['min_line_seg'] = min_seg; rep['tiny_contours'] = tiny
    rep['ok'] = (after[1] == 0 and tiny == 0 and rep['area_change'] < 0.01)
    return p, rep


def _contour_nodes(contour):
    """[(end point, verb, controls)] for the segments of a contour, the implicit closing line included."""
    nodes = []; start = None
    for verb, pts in contour.segments:
        if verb == 'moveTo':
            start = pts[0]
        elif verb == 'lineTo':
            nodes.append((pts[0], 'L', ()))
        elif verb in ('qCurveTo', 'curveTo'):
            nodes.append((pts[-1], 'C', tuple(pts[:-1])))
    if any(q is None for q, _, _ in nodes):
        return []                                   # a contour without on-curve points (a round dot)
    if start is not None and nodes and math.dist(nodes[-1][0], start) > 1e-6:
        nodes.append((start, 'L', ()))
    return nodes


def short_edges(path, base=None, lim=6.0, smooth_deg=12.0, tol=1.5):
    """Short segments (chord < lim) of the outline, for inspection. Each item is a dict with a, b,
    length, curve (bool) and step: True when the outline turns by more than smooth_deg at BOTH ends (a
    step or a chamfer, visible when zoomed in), False when one end continues smoothly (a short remainder
    of an original segment next to a cut corner). With `base` (the uncut outline) segments whose two end
    points are both nodes of the base outline (within tol) are left out: they belong to the design."""
    old = []
    if base is not None:
        for contour in base.contours:
            old += [q for q, _, _ in _contour_nodes(contour)]
    is_old = lambda q: any(abs(q[0] - o[0]) <= tol and abs(q[1] - o[1]) <= tol for o in old)
    def _dir(a, b):
        L = math.dist(a, b)
        return ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L > 1e-9 else None
    def _turn(d1, d2):
        if d1 is None or d2 is None:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))))
    out = []
    for contour in path.contours:
        nodes = _contour_nodes(contour); n = len(nodes)
        if n < 3:
            continue
        def tangents(k):
            a = nodes[k - 1][0]; b, verb, ctrl = nodes[k]
            chain = [a] + [c for c in ctrl if c is not None] + [b]
            t0 = next((_dir(chain[0], c) for c in chain[1:] if math.dist(chain[0], c) > 1e-6), None)
            t1 = next((_dir(c, chain[-1]) for c in reversed(chain[:-1]) if math.dist(chain[-1], c) > 1e-6), None)
            return t0, t1
        for k in range(n):
            a = nodes[k - 1][0]; b, verb, ctrl = nodes[k]
            L = math.dist(a, b)
            if L >= lim or L < 1e-6:
                continue
            if base is not None and is_old(a) and is_old(b):
                continue
            t0, t1 = tangents(k)
            turn_in = _turn(tangents((k - 1) % n)[1], t0)
            turn_out = _turn(t1, tangents((k + 1) % n)[0])
            out.append({'a': a, 'b': b, 'length': L, 'curve': verb == 'C', 'step': min(turn_in, turn_out) > smooth_deg,
                        'turns': (turn_in, turn_out)})
    return out
