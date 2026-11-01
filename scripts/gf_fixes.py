"""Post-build fixes for the Google Fonts profile of fontbakery, applied in place to fonts/ttf/*.ttf.

    python scripts/gf_fixes.py

1. `.notdef` gets a visible outline (a hollow rectangle) instead of the blank glyph inherited from
   the parent font (fontbakery: mandatory_glyphs).
2. A `prep` table with the smart-dropout-control program expected for unhinted TrueType fonts
   (fontbakery: smart_dropout).
3. The legacy spacing accents (grave, acute, circumflex, tilde, dieresis, ring, cedilla) are set to
   GDEF class 1 (base) instead of class 3 (mark), as they are spacing characters in their own right
   (fontbakery: legacy_accents).
The remaining Google Fonts failure, Latin Extended coverage (Ā ă Ą Ć Ċ ... ), is a glyph-set
limitation of the parent font and is not fixed here.
"""
import os, glob
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import ttProgram
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_ACCENTS = ['grave', 'acute', 'circumflex', 'tilde', 'dieresis', 'ring', 'cedilla', 'macron', 'breve',
                  'dotaccent', 'ogonek', 'caron', 'hungarumlaut']

def fix_notdef(font, width=600, stroke=50):
    glyf = font['glyf']; hmtx = font['hmtx']
    g = glyf['.notdef']
    if g.numberOfContours > 0:
        return False
    pen = TTGlyphPen(None)
    x0, y0, x1, y1 = 50, -120, width - 50, 880
    pen.moveTo((x0, y0)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y0)); pen.closePath()
    pen.moveTo((x0 + stroke, y0 + stroke)); pen.lineTo((x1 - stroke, y0 + stroke)); pen.lineTo((x1 - stroke, y1 - stroke)); pen.lineTo((x0 + stroke, y1 - stroke)); pen.closePath()
    glyf['.notdef'] = pen.glyph()
    hmtx['.notdef'] = (width, x0)
    return True

def fix_prep(font):
    program = ttProgram.Program()
    program.fromBytecode(b'\xb8\x01\xff\x85\xb0\x04\x8d')
    if 'prep' in font and font['prep'].program.getBytecode() == program.getBytecode():
        return False
    prep = newTable('prep'); prep.program = program; font['prep'] = prep
    return True

def fix_legacy_accents(font):
    if 'GDEF' not in font or not font['GDEF'].table.GlyphClassDef:
        return 0
    classes = font['GDEF'].table.GlyphClassDef.classDefs
    n = 0
    for name in LEGACY_ACCENTS:
        if classes.get(name) == 3:
            classes[name] = 1; n += 1
    return n

def main():
    for path in sorted(glob.glob(os.path.join(ROOT, 'fonts', 'ttf', '*.ttf'))):
        font = TTFont(path)
        a = fix_notdef(font); b = fix_prep(font); c = fix_legacy_accents(font)
        font.save(path)
        print(os.path.basename(path), 'notdef drawn' if a else 'notdef kept', '| prep added' if b else '| prep kept', '| accents reclassified:', c)

if __name__ == '__main__':
    main()
