"""Export the generated TrueType fonts to UFO sources (sources/*.ufo) for the Google Fonts tool chain.

    python scripts/export_ufo.py

The UFOs are a faithful conversion of fonts/ttf/*.ttf (quadratic outlines, metrics, kerning and
features extracted with `extractor`). They are build inputs for `gftools builder`, not design
sources: to change the fonts, edit the pipeline in scripts/ and regenerate.
"""
import os, sys, glob, shutil
import extractor, ufoLib2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    for ttf in sorted(glob.glob(os.path.join(ROOT, 'fonts', 'ttf', '*.ttf'))):
        name = os.path.splitext(os.path.basename(ttf))[0]
        dest = os.path.join(ROOT, 'sources', name + '.ufo')
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        ufo = ufoLib2.Font()
        extractor.extractUFO(ttf, ufo, doGlyphs=True, doInfo=True, doKerning=True, doFeatures=True)
        ufo.save(dest, overwrite=True)
        print('wrote', os.path.relpath(dest, ROOT), len(ufo), 'glyphs')

if __name__ == '__main__':
    main()
