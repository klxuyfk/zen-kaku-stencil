"""Release naming, applied in place to fonts/ttf/*.ttf (or to the files given): the Google Fonts style name
table (copyright, version, manufacturer, designer, description, URLs), the vendor ID and head.fontRevision.
build_font.py leaves the parent font's records and a development version string; run this before gf_fixes.py.

    python scripts/set_names.py [--version 1.100] [font.ttf ...]
"""
import os, sys, glob, argparse
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = 'KLXU'
URL = 'https://github.com/klxuyfk/zen-kaku-stencil'
COPYRIGHT = ('Copyright 2026 Kagami Aso (%s), Copyright 2022 The Zen Project Authors '
             '(https://github.com/googlefonts/zen-kakugothic)' % URL)
DESCRIPTION = ('Zen Kaku Stencil is a stencil derivative of Zen Kaku Gothic New: every counter is bridged following '
               'Japanese stroke order, and every glyph is verified to dissolve into valid closed profiles in CAD.')
LICENSE = ('This Font Software is licensed under the SIL Open Font License, Version 1.1. This license is available '
           'with a FAQ at: https://scripts.sil.org/OFL')


def set_names(path, version):
    font = TTFont(path)
    name = font['name']
    family = name.getDebugName(16) or name.getDebugName(1)
    style = name.getDebugName(17) or name.getDebugName(2)
    ps = (family + '-' + style).replace(' ', '')
    records = {0: COPYRIGHT, 1: family, 2: style, 3: '%s;%s;%s' % (version, VENDOR, ps), 4: '%s %s' % (family, style),
               5: 'Version %s; stencil derivative of Zen Kaku Gothic New' % version, 6: ps, 8: 'Kagami Aso',
               9: 'Yoshimichi Ohira (Zen Kaku Gothic New); Kagami Aso (stencil derivative)', 10: DESCRIPTION,
               11: URL, 12: URL, 13: LICENSE, 14: 'https://scripts.sil.org/OFL'}
    name.names = []
    for nid, text in sorted(records.items()):
        name.setName(text, nid, 3, 1, 0x409)
    font['OS/2'].achVendID = VENDOR
    font['head'].fontRevision = float(version)
    font.save(path)
    print(os.path.basename(path), '->', records[5])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', default='1.100'); ap.add_argument('fonts', nargs='*')
    a = ap.parse_args()
    for p in a.fonts or sorted(glob.glob(os.path.join(ROOT, 'fonts', 'ttf', '*.ttf'))):
        set_names(p, a.version)
