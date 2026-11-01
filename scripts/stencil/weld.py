"""Weld near-touching / self-touching ink so that every contour keeps a minimum clearance.
Two cut-out regions separated by a hair-thin wall of material can neither be modelled cleanly in CAD
nor survive physically, so such strokes are joined by a small local fill (convex hull of the ink
around the contact point)."""
import math
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union, nearest_points
from shapely.validation import explain_validity
import pathops
from .core import path_polys, signed_area

MIN_GAP = 12.0     # font units; contours closer than this are welded
WELD_R = 16.0      # radius of the local hull used to fill the contact

def _rings(path):
    return [(Polygon(p), h) for p, h in path_polys(path, 0.5) if len(p) >= 3]

def ring_self_contacts(coords, gap, min_arc=80.0, step=4.0):
    """Points where a closed ring comes within `gap` of itself at places more than `min_arc`
    apart along the ring (a narrow channel), as opposed to the two sides of an acute corner."""
    import numpy as np
    pts = []; s = []; acc = 0.0
    n = len(coords)
    for i in range(n):
        p = coords[i]; q = coords[(i + 1) % n]
        seg = math.dist(p, q)
        if seg < 1e-9:
            continue
        k = max(1, int(seg // step))
        for j in range(k):
            t = j / k
            pts.append((p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t)); s.append(acc + seg*t)
        acc += seg
    if len(pts) < 8:
        return []
    P = np.asarray(pts); S = np.asarray(s); total = acc
    out = []
    used = np.zeros(len(P), dtype=bool)
    chunk = 2048
    for a in range(0, len(P), chunk):
        D = np.hypot(P[a:a+chunk, None, 0] - P[None, :, 0], P[a:a+chunk, None, 1] - P[None, :, 1])
        A = np.abs(S[a:a+chunk, None] - S[None, :]); A = np.minimum(A, total - A)
        ii, jj = np.nonzero((D < gap) & (A > min_arc))
        for i, j in zip(ii + a, jj):
            if i < j and not used[i] and not used[j]:
                out.append(((P[i, 0] + P[j, 0]) / 2, (P[i, 1] + P[j, 1]) / 2))
                # mark a neighbourhood as handled so one channel yields one weld
                near = np.hypot(P[:, 0] - P[i, 0], P[:, 1] - P[i, 1]) < 3*gap
                used |= near
    return out

def problems(path, min_gap=MIN_GAP, self_contacts=True):
    """Return list of (x, y) contact points needing a weld: invalid rings (self-touch), contour
    pairs closer than min_gap, and narrow channels where a ring nearly touches itself."""
    pts = []
    rings = _rings(path)
    if self_contacts:
        for poly, h in rings:
            pts.extend(ring_self_contacts(list(poly.exterior.coords)[:-1], min_gap))
    for poly, h in rings:
        if not poly.is_valid:
            msg = explain_validity(poly)
            # e.g. "Ring Self-intersection[559 323]"
            if '[' in msg:
                xy = msg[msg.index('[')+1:msg.index(']')].split()
                pts.append((float(xy[0]), float(xy[1])))
    for i in range(len(rings)):
        for j in range(i + 1, len(rings)):
            a, b = rings[i][0], rings[j][0]
            try:
                nested = a.contains(b) or b.contains(a)
            except Exception:
                nested = False
            ga, gb = (a.exterior, b.exterior) if nested else (a, b)
            d = ga.distance(gb)
            if d < min_gap:
                p, q = nearest_points(ga, gb)
                pts.append(((p.x + q.x) / 2, (p.y + q.y) / 2))
    return pts

def _ink(path):
    from .bridges import ink_polygons
    return ink_polygons(path, 0.5)

def _poly_to_path(geom):
    p = pathops.Path(); pen = p.getPen()
    polys = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    for poly in polys:
        for ring in [poly.exterior] + list(poly.interiors):
            coords = list(ring.coords)[:-1]
            pen.moveTo(coords[0])
            for c in coords[1:]:
                pen.lineTo(c)
            pen.closePath()
    return p

def _pieces(geom):
    return [g for g in (geom.geoms if hasattr(geom, 'geoms') else [geom]) if not g.is_empty]

def channels(ink, width=MIN_GAP, min_area=8.0):
    """Material channels/notches narrower than `width` (morphological closing residue): a hair-thin
    wall between two cut-outs, or a near-touch inside one contour. Returns patch polygons."""
    h = width / 2.0
    closed = ink.buffer(h).buffer(-h)
    out = []
    for g in _pieces(closed.difference(ink)):
        if g.area <= min_area:
            continue
        if 2*g.area/max(g.length, 1e-6) < width:
            out.append(g.buffer(0.6, 1))
    return out

def _holes(path):
    from .bridges import material_regions
    regions, ext = material_regions(_ink(path))
    return len(regions) - 1

def desliver(path, h=3.5, max_area=150.0, max_thick=2.5):
    """Post-cut cleanup: remove hairline ink slivers; fill hairline material notches only when the
    fill does not re-close a bridge (hole count unchanged). Returns (path, n_fixes)."""
    ink = _ink(path)
    cur = path; n = 0
    opened = ink.buffer(-h).buffer(h)
    for g in _pieces(ink.difference(opened)):
        if g.area <= 8.0 or g.area > max_area or 2*g.area/max(g.length, 1e-6) >= max_thick:
            continue
        cur = pathops.op(cur, _poly_to_path(g.buffer(0.4, 1)), pathops.PathOp.DIFFERENCE, fix_winding=True, keep_starting_points=False); n += 1
    closed = ink.buffer(h).buffer(-h)
    fills = [g for g in _pieces(closed.difference(ink)) if 8.0 < g.area <= max_area and 2*g.area/max(g.length, 1e-6) < max_thick]
    if fills:
        before = _holes(cur)
        for g in fills:
            cand = pathops.op(cur, _poly_to_path(g.buffer(0.4, 1)), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False)
            if _holes(cand) == before:
                cur = cand; n += 1
    if n:
        cur.simplify(fix_winding=True, keep_starting_points=False)
    return cur, n

def trim_remnants(path, rects, r=3.0, min_area=20.0, max_area=200.0, max_thick=2.6, reach=1.0):
    """Post-cut cleanup: a bridge whose side runs almost parallel to a stroke edge, or whose end leaves
    an acute corner, can leave a hair-thin strip of ink (thinner than 2*r) beside the bridge. Such a
    strip would be a fragile sliver on a real stencil and trips SolidWorks' contour check, so it is
    removed: the cut edge then follows the stroke's own edge. Only pieces touching a bridge rectangle
    are considered (acute stroke tips elsewhere are part of the design). Returns (path, n_trimmed)."""
    if not rects:
        return path, 0
    ink = _ink(path)
    opened = ink.buffer(-r).buffer(r)
    cur = path; n = 0
    for g in _pieces(ink.difference(opened)):
        if g.area < min_area or g.area > max_area or 2*g.area/max(g.length, 1e-6) >= max_thick:
            continue
        if not any(g.distance(rc) < reach for rc in rects):
            continue
        cur = pathops.op(cur, _poly_to_path(g.buffer(0.4, 1)), pathops.PathOp.DIFFERENCE, fix_winding=True, keep_starting_points=False); n += 1
    if n:
        cur.simplify(fix_winding=True, keep_starting_points=False)
    return cur, n

def _patches_for(ink, pts, r):
    patches = []
    for (x, y) in pts:
        piece = ink.intersection(Point(x, y).buffer(r, 6))
        if piece.is_empty:
            continue
        hull = piece.convex_hull
        if hull.geom_type != 'Polygon' or hull.area < 1.0:
            continue
        patches.append(hull.buffer(1.5, 1))
    return patches

def weld_guarded(path, min_gap=MIN_GAP, r=WELD_R, max_iter=6):
    """Post-cut welding: like weld(), but a patch is kept only if it does not change the number of
    material regions (it must never re-close a bridge). Returns (path, n_welds)."""
    cur = path; n = 0
    before = _holes(cur)
    for _ in range(max_iter):
        pts = problems(cur, min_gap)
        if not pts:
            break
        ink = _ink(cur)
        applied = 0
        for patch in _patches_for(ink, pts, r):
            cand = pathops.op(cur, _poly_to_path(patch), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False)
            if _holes(cand) == before:
                cur = cand; applied += 1
        if not applied:
            break
        cur.simplify(fix_winding=True, keep_starting_points=False)
        n += applied
    return cur, n

def fill_slivers(path, max_area=200.0, max_thick=6.0):
    """Fill enclosed hair-thin material regions (islands too small/thin to bridge or to survive)."""
    from .bridges import material_regions
    ink = _ink(path)
    regions, ext = material_regions(ink)
    cur = path; n = 0
    for rid, reg in regions.items():
        if rid == ext:
            continue
        if reg.area < max_area or 2*reg.area/max(reg.length, 1e-6) < max_thick:
            cur = pathops.op(cur, _poly_to_path(reg.buffer(0.6, 1)), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False); n += 1
    if n:
        cur.simplify(fix_winding=True, keep_starting_points=False)
    return cur, n

def trim_leaves(path, rects, r=3.0, max_area=600.0, reach=3.0):
    """Post-cut cleanup: a bridge that crosses a tapering stroke tip at an angle can leave a small
    leaf of ink beside the cut, attached to the body only through a neck thinner than 2*r (seen in
    Bold 喝: the hook's tip). The leaf cannot be made as a stencil and its neck trips SolidWorks'
    contour check, so leaf and neck are removed. Only small pieces (<= max_area) that hang off a
    much larger ink component and touch a bridge rectangle are considered. Returns (path, n)."""
    if not rects:
        return path, 0
    ink = _ink(path)
    opened = ink.buffer(-r).buffer(r)
    comps = _pieces(opened)
    if len(comps) < 2:
        return path, 0
    resid = _pieces(ink.difference(opened))
    bodies = _pieces(ink)
    cur = path; n = 0
    for comp in comps:
        if comp.area > max_area:
            continue
        body = next((b for b in bodies if b.intersects(comp)), None)
        if body is None or body.area < 4.0 * max_area:
            continue   # a small stroke of its own, not a leaf hanging off a body
        if not any(comp.distance(rc) < reach for rc in rects):
            continue
        region = comp.buffer(r + 1.0, 2)
        for g in resid:
            if g.intersects(region):
                region = region.union(g.buffer(0.6, 1))
        piece = ink.intersection(region)
        if piece.is_empty:
            continue
        cur = pathops.op(cur, _poly_to_path(piece.buffer(0.4, 1)), pathops.PathOp.DIFFERENCE, fix_winding=True, keep_starting_points=False); n += 1
    if n:
        cur.simplify(fix_winding=True, keep_starting_points=False)
    return cur, n

def weld(path, min_gap=MIN_GAP, r=WELD_R, max_iter=12):
    """Return (path, n_welds). Welds are applied as boolean unions of small polygons on the original
    curves (the untouched outline geometry is preserved everywhere else)."""
    n = 0
    cur = path
    for _ in range(max_iter):
        pts = problems(cur, min_gap)
        if not pts:
            break
        ink = _ink(cur)
        patches = []
        for (x, y) in pts:
            disk = Point(x, y).buffer(r, 6)
            piece = ink.intersection(disk)
            if piece.is_empty:
                continue
            hull = piece.convex_hull
            if hull.geom_type != 'Polygon' or hull.area < 1.0:
                continue
            # expand the hull by a hair so that it overlaps the ink it touches (no tangent edges),
            # using a square-ish buffer (few extra vertices)
            hull = hull.buffer(1.5, 1)
            patches.append(hull)
        if not patches:
            break
        patch = unary_union(patches)
        cur = pathops.op(cur, _poly_to_path(patch), pathops.PathOp.UNION, fix_winding=True, keep_starting_points=False)
        cur.simplify(fix_winding=True, keep_starting_points=False)
        n += len(patches)
    if list(cur.contours):
        cur, ns = fill_slivers(cur)
        n += ns
    return cur, n
