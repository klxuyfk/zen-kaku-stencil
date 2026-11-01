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

def clip_needles(path, max_arm=12.0, max_deg=15.0):
    """Remove hairpin vertices where the outline turns back on itself within max_deg and one arm is
    short (<= max_arm): hair-thin ink needles or slits (e.g. a stroke tip grazing another stroke in the
    base design). Works for line and curve arms: the short arm is dropped and the long arm is re-ended at
    the short arm's far point (a shift of at most max_arm units at the end of that segment).
    SolidWorks reports such hairpins as self-intersecting entities after its spline fit."""
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

def finalize(path, min_len=2.0, needle_arm=None):
    """Round, drop micro-segments, re-simplify, weld any self-touch created by rounding;
    return (final_path, report dict)."""
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
