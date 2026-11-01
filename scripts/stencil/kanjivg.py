"""KanjiVG stroke-order data: parse SVG stroke paths and align them to a glyph's ink bounds."""
import os, re, math

KVG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'kanjivg_dl', 'x', 'kanji')
_NUM = r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?'
_TOK = re.compile(r'[MmLlHhVvCcSsQqTtZzAa]|' + _NUM)

def _cubic(p0, p1, p2, p3, n=12):
    out = []
    for i in range(1, n + 1):
        t = i / n; mt = 1 - t
        a, b, c, d = mt**3, 3*mt*mt*t, 3*mt*t*t, t**3
        out.append((a*p0[0]+b*p1[0]+c*p2[0]+d*p3[0], a*p0[1]+b*p1[1]+c*p2[1]+d*p3[1]))
    return out

def _quad(p0, p1, p2, n=10):
    out = []
    for i in range(1, n + 1):
        t = i / n; mt = 1 - t
        out.append((mt*mt*p0[0]+2*mt*t*p1[0]+t*t*p2[0], mt*mt*p0[1]+2*mt*t*p1[1]+t*t*p2[1]))
    return out

def parse_path(d):
    """Flatten an SVG path 'd' into a list of polylines (one per subpath)."""
    toks = _TOK.findall(d)
    i = 0; cmd = None; cur = (0.0, 0.0); start = (0.0, 0.0); prev_c = None
    polys = []; pts = []
    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if re.match(r'[A-Za-z]', toks[i]):
            cmd = toks[i]; i += 1
            if cmd in 'Zz':
                if pts: polys.append(pts); pts = []
                cur = start; continue
        rel = cmd.islower(); c = cmd.upper()
        if c == 'M':
            x, y = num(), num()
            if rel: x += cur[0]; y += cur[1]
            if pts: polys.append(pts)
            pts = [(x, y)]; cur = (x, y); start = cur; cmd = 'l' if rel else 'L'; prev_c = None
        elif c == 'L':
            x, y = num(), num()
            if rel: x += cur[0]; y += cur[1]
            cur = (x, y); pts.append(cur); prev_c = None
        elif c == 'H':
            x = num(); x = x + cur[0] if rel else x
            cur = (x, cur[1]); pts.append(cur); prev_c = None
        elif c == 'V':
            y = num(); y = y + cur[1] if rel else y
            cur = (cur[0], y); pts.append(cur); prev_c = None
        elif c == 'C':
            x1, y1, x2, y2, x, y = (num() for _ in range(6))
            if rel: x1 += cur[0]; y1 += cur[1]; x2 += cur[0]; y2 += cur[1]; x += cur[0]; y += cur[1]
            pts.extend(_cubic(cur, (x1, y1), (x2, y2), (x, y))); prev_c = (x2, y2); cur = (x, y)
        elif c == 'S':
            x2, y2, x, y = (num() for _ in range(4))
            if rel: x2 += cur[0]; y2 += cur[1]; x += cur[0]; y += cur[1]
            x1, y1 = (2*cur[0]-prev_c[0], 2*cur[1]-prev_c[1]) if prev_c else cur
            pts.extend(_cubic(cur, (x1, y1), (x2, y2), (x, y))); prev_c = (x2, y2); cur = (x, y)
        elif c == 'Q':
            x1, y1, x, y = (num() for _ in range(4))
            if rel: x1 += cur[0]; y1 += cur[1]; x += cur[0]; y += cur[1]
            pts.extend(_quad(cur, (x1, y1), (x, y))); prev_c = (x1, y1); cur = (x, y)
        elif c == 'T':
            x, y = num(), num()
            if rel: x += cur[0]; y += cur[1]
            x1, y1 = (2*cur[0]-prev_c[0], 2*cur[1]-prev_c[1]) if prev_c else cur
            pts.extend(_quad(cur, (x1, y1), (x, y))); prev_c = (x1, y1); cur = (x, y)
        elif c == 'A':
            # rare in KanjiVG; approximate by line to end point
            for _ in range(5): num()
            x, y = num(), num()
            if rel: x += cur[0]; y += cur[1]
            cur = (x, y); pts.append(cur); prev_c = None
    if pts: polys.append(pts)
    return polys

_PATH_RE = re.compile(r'<path\s+id="kvg:([0-9a-f]+)-s(\d+)"(?:\s+kvg:type="([^"]*)")?\s+d="([^"]*)"')

def load(codepoint):
    """Return list of strokes [{'n': int, 'type': str, 'pts': [(x,y)...]}] in KanjiVG coords (109 box, y down), or None."""
    fn = os.path.join(KVG_DIR, '%05x.svg' % codepoint)
    if not os.path.exists(fn):
        return None
    txt = open(fn, encoding='utf-8').read()
    strokes = []
    for m in _PATH_RE.finditer(txt):
        n = int(m.group(2)); typ = m.group(3) or ''
        polys = parse_path(m.group(4))
        pts = [p for poly in polys for p in poly]
        if len(pts) >= 2:
            strokes.append({'n': n, 'type': typ, 'pts': pts})
    strokes.sort(key=lambda s: s['n'])
    return strokes or None

NOMINAL = 1000.0 / 109.0

def align(strokes, ink_bounds, stroke_w):
    """Map KanjiVG strokes into glyph units so the stroke centrelines fit the glyph's ink bbox
    (shrunk by half a stroke width). Returns new list of strokes with 'pts' in glyph coords."""
    xs = [p[0] for s in strokes for p in s['pts']]; ys = [p[1] for s in strokes for p in s['pts']]
    kx0, kx1, ky0, ky1 = min(xs), max(xs), min(ys), max(ys)
    gx0, gy0, gx1, gy1 = ink_bounds
    half = stroke_w / 2.0
    # x axis
    ext = kx1 - kx0
    if ext > 12:
        sx = (gx1 - gx0 - 2*half) / ext
        sx = min(max(sx, NOMINAL*0.7), NOMINAL*1.4)
    else:
        sx = NOMINAL
    cx_k = (kx0 + kx1) / 2; cx_g = (gx0 + gx1) / 2
    # y axis (flip)
    ext = ky1 - ky0
    if ext > 12:
        sy = (gy1 - gy0 - 2*half) / ext
        sy = min(max(sy, NOMINAL*0.7), NOMINAL*1.4)
    else:
        sy = NOMINAL
    cy_k = (ky0 + ky1) / 2; cy_g = (gy0 + gy1) / 2
    out = []
    for s in strokes:
        pts = [(cx_g + (p[0]-cx_k)*sx, cy_g - (p[1]-cy_k)*sy) for p in s['pts']]
        out.append({'n': s['n'], 'type': s['type'], 'pts': pts})
    return out

def snap(strokes, ink, stroke_w, radius=None, passes=2):
    """Pull each stroke polyline onto the centreline of the glyph ink: every vertex is moved to the
    middle of the ink cross-section found along the local normal (within `radius`). Vertices whose
    cross-section is too long (junctions) or missing (overshoot past a stroke end) keep their position.
    A global per-axis scale/offset refit is done between passes."""
    from shapely.geometry import LineString, Point
    radius = radius or 1.6 * stroke_w
    cur = [dict(s) for s in strokes]
    for _ in range(passes):
        moved_src, moved_dst = [], []
        for s in cur:
            pts = s['pts']; new = []
            for i, p in enumerate(pts):
                q0 = pts[max(i-1, 0)]; q1 = pts[min(i+1, len(pts)-1)]
                tx, ty = q1[0]-q0[0], q1[1]-q0[1]; L = math.hypot(tx, ty)
                if L < 1e-6:
                    new.append(p); continue
                n = (-ty/L, tx/L)
                line = LineString([(p[0]-n[0]*radius, p[1]-n[1]*radius), (p[0]+n[0]*radius, p[1]+n[1]*radius)])
                inter = line.intersection(ink)
                pieces = [g for g in (inter.geoms if hasattr(inter, 'geoms') else [inter]) if not g.is_empty and g.geom_type == 'LineString']
                best = None
                P = Point(p)
                # the cross-section the vertex itself sits in: if that one is a junction blob (too long)
                # or a stub, keep the vertex rather than jumping to a neighbouring stroke's section
                own = min(pieces, key=lambda g: g.distance(P)) if pieces else None
                if own is not None and own.distance(P) <= 0.5 * stroke_w and not (0.3 * stroke_w <= own.length <= 1.9 * stroke_w):
                    new.append(p); continue
                for g in pieces:
                    if g.length > 1.9 * stroke_w or g.length < 0.3 * stroke_w:
                        continue
                    d = g.distance(P)
                    if best is None or d < best[0]:
                        best = (d, g)
                if best is None:
                    new.append(p); continue
                g = best[1]
                c = g.interpolate(0.5, normalized=True)
                new.append((c.x, c.y)); moved_src.append(p); moved_dst.append((c.x, c.y))
            s['pts'] = new
        # global refit (per-axis linear) to propagate the systematic offset to unmoved points
        if len(moved_src) >= 4:
            def fit(idx):
                xs = [p[idx] for p in moved_src]; ys = [p[idx] for p in moved_dst]
                mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
                vx = sum((x-mx)**2 for x in xs)
                a = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / vx if vx > 1e-6 else 1.0
                a = min(max(a, 0.85), 1.15)
                return a, my - a*mx
            ax, bx = fit(0); ay, by = fit(1)
            for s in cur:
                s['pts'] = [(ax*p[0]+bx, ay*p[1]+by) for p in s['pts']]
    return cur
