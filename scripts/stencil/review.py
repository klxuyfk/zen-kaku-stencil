"""Review rendering: stencil result with cut rectangles and KanjiVG strokes overlaid."""
from PIL import Image, ImageDraw
from .core import path_polys, signed_area

def render_result(res, size=220, box_=(-60, -200, 1060, 920), show_strokes=True, label=''):
    img = Image.new('RGB', (size, size), (255, 255, 255))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box_
    s = size / max(x1-x0, y1-y0)
    tf = lambda p: ((p[0]-x0)*s, size-(p[1]-y0)*s)
    polys = path_polys(res.path, tol=0.5)
    polys.sort(key=lambda ph: -abs(signed_area(ph[0])))
    for pts, hole in polys:
        d.polygon([tf(p) for p in pts], fill=((255, 255, 255) if hole else (20, 20, 20)))
    for c in res.chosen:
        pts = [tf(p) for p in c.rect.exterior.coords]
        d.line(pts, fill=(230, 40, 40), width=1)
    if show_strokes and res.strokes:
        for st in res.strokes:
            pts = [tf(p) for p in st['pts']]
            d.line(pts, fill=(60, 120, 255), width=1)
            d.ellipse([pts[-1][0]-2, pts[-1][1]-2, pts[-1][0]+2, pts[-1][1]+2], fill=(0, 160, 0))
    if res.unconnected or res.n_holes_after:
        d.rectangle([0, 0, size-1, size-1], outline=(255, 0, 0), width=3)
    if label:
        d.text((3, 2), label, fill=(120, 120, 120))
    return img
