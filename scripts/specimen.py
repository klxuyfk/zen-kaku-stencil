"""Specimen image of the built font (out/specimen.png): a few lines of text set with PIL.
usage: python scripts/specimen.py [font.ttf] [out.png]"""
import sys
from PIL import Image, ImageDraw, ImageFont

FONT = sys.argv[1] if len(sys.argv) > 1 else 'out/ZenKakuStencil-Regular.ttf'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'out/specimen.png'
LINES = [('東京都港区 日本語ステンシル', 96), ('Zen Kaku Stencil ABCDEFG abcdefg 0123456789', 60),
         ('あいうえお かきくけこ アイウエオ カキクケコ', 66), ('鬱陶 曲用品門 膣 兩劇赭 ぱ', 84), ('注意 危険 立入禁止 非常口 消火器', 84)]
W, PAD, GAP = 1800, 44, 26
h = PAD * 2 + sum(int(s * 1.18) for _, s in LINES) + GAP * (len(LINES) - 1)
img = Image.new('RGB', (W, h), (255, 255, 255)); d = ImageDraw.Draw(img)
y = PAD
for text, size in LINES:
    d.text((PAD, y), text, fill=(20, 20, 20), font=ImageFont.truetype(FONT, size))
    y += int(size * 1.18) + GAP
img.save(OUT); print('wrote', OUT, img.size)
