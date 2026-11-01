"""Core geometry for the stencil pipeline: glyph loading, overlap removal, hole detection, rendering."""
import math
from fontTools.ttLib import TTFont
import pathops
from PIL import Image, ImageDraw

# ---------- loading ----------
class Font:
    def __init__(self, path):
        self.tt = TTFont(path)
        self.cmap = self.tt.getBestCmap()
        self.gs = self.tt.getGlyphSet()
        self.upem = self.tt['head'].unitsPerEm

    def glyph_name(self, ch):
        return self.cmap.get(ord(ch))

    def raw_path(self, gname):
        p = pathops.Path()
        self.gs[gname].draw(p.getPen(glyphSet=self.gs))
        return p

    def clean_path(self, gname):
        """Union of all contours (overlaps removed), consistent winding."""
        p = self.raw_path(gname)
        p.simplify(fix_winding=True, keep_starting_points=False)
        return p

    def advance(self, gname):
        return self.tt['hmtx'][gname][0]

# ---------- flattening ----------
def _quad_pts(p0, p1, p2, n):
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b = (1 - t) ** 2, 2 * (1 - t) * t
        c = t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return out

def _cubic_pts(p0, p1, p2, p3, n):
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, d = mt ** 3, 3 * mt * mt * t, 3 * mt * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out

def contour_points(contour, tol=1.0):
    """Flatten a pathops contour to a polyline (list of points, closed implicitly)."""
    pts = []
    cur = None
    for verb, args in contour.segments:
        if verb == 'moveTo':
            cur = args[0]; pts.append(cur)
        elif verb == 'lineTo':
            cur = args[0]; pts.append(cur)
        elif verb == 'qCurveTo':
            # pathops yields one off-curve + one on-curve per qCurveTo after simplify
            ctrls = list(args)
            if ctrls[-1] is None:
                # closed all-off-curve contour: the on-curve point is implied midway between
                # the last and first off-curve points (contour has no moveTo)
                implied = ((ctrls[-2][0] + ctrls[0][0]) / 2, (ctrls[-2][1] + ctrls[0][1]) / 2)
                ctrls[-1] = implied
                if cur is None:
                    cur = implied; pts.append(cur)
            # decompose multiple off-curves (implied on-curves)
            offs, end = ctrls[:-1], ctrls[-1]
            for i, off in enumerate(offs):
                nxt = end if i == len(offs) - 1 else ((off[0] + offs[i + 1][0]) / 2, (off[1] + offs[i + 1][1]) / 2)
                d = math.dist(cur, off) + math.dist(off, nxt)
                n = max(2, int(math.ceil(math.sqrt(d / tol * 0.5))))
                pts.extend(_quad_pts(cur, off, nxt, n)); cur = nxt
        elif verb == 'curveTo':
            c1, c2, end = args
            d = math.dist(cur, c1) + math.dist(c1, c2) + math.dist(c2, end)
            n = max(2, int(math.ceil(math.sqrt(d / tol * 0.5))))
            pts.extend(_cubic_pts(cur, c1, c2, end, n)); cur = end
        elif verb in ('closePath', 'endPath'):
            pass
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts

def signed_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return a / 2

def path_polys(path, tol=1.0):
    """Return list of (points, is_hole) for a cleaned path. Holes are determined by orientation
    relative to the majority of enclosing structure: after fix_winding outer contours are CCW(+)."""
    out = []
    for ct in path.contours:
        pts = contour_points(ct, tol)
        if len(pts) < 3:
            continue
        out.append((pts, signed_area(pts) < 0))
    return out

# ---------- shapely helpers ----------
def to_shapely(path, tol=1.0):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = path_polys(path, tol)
    outers = [Polygon(p) for p, h in polys if not h]
    holes = [Polygon(p) for p, h in polys if h]
    geom = unary_union(outers)
    if holes:
        geom = geom.difference(unary_union(holes))
    return geom

# ---------- rendering ----------
def render_paths(paths, size=256, scale_box=None, colors=None, bg=(255, 255, 255)):
    """Render one or more pathops paths (already cleaned) into a PIL image.
    paths: list of pathops.Path; colors: list of RGB fill colours (later paths drawn over earlier).
    scale_box: (xmin, ymin, xmax, ymax) font-unit box mapped to the image."""
    img = Image.new('RGB', (size, size), bg)
    d = ImageDraw.Draw(img)
    if scale_box is None:
        scale_box = (-100, -300, 1100, 900)
    x0, y0, x1, y1 = scale_box
    s = size / max(x1 - x0, y1 - y0)
    def tf(p):
        return (p[0] - x0) * s, size - (p[1] - y0) * s
    for i, path in enumerate(paths):
        col = (colors[i] if colors else (0, 0, 0))
        polys = path_polys(path, tol=0.5)
        polys.sort(key=lambda ph: -abs(signed_area(ph[0])))
        for pts, hole in polys:
            d.polygon([tf(p) for p in pts], fill=(bg if hole else col))
    return img

def contact_sheet(images, cols=8, pad=4, bg=(220, 220, 220)):
    if not images:
        return Image.new('RGB', (10, 10), bg)
    w, h = images[0].size
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (w + pad) + pad, rows * (h + pad) + pad), bg)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        sheet.paste(im, (pad + c * (w + pad), pad + r * (h + pad)))
    return sheet
