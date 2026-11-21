"""Micro-edge audit of a whole batch result (out/results*.pkl): every glyph is finalized as build_font.py does
and its outline is compared with the uncut outline.
Per glyph with cuts it reports
  short   NEW segments shorter than 12 units (not both ends nodes of the uncut outline): `step` when the outline
          turns by more than 12 degrees at both ends, otherwise a smooth remainder; `far` when more than 40 units
          from every cut (not made by a cut: rounding or welding)
  acute   vertices with a new neighbour within 6 units of a cut where the outline turns by more than 135 degrees
          (a tip sharper than 45 degrees)
  weld    self-contacts and gaps under 3 units (weld.problems)
  holes   counters left closed; not ok: finalize's own check
usage: python scripts/audit_font.py out/results.pkl [out/audit.pkl] > out/audit.log
"""
import sys, os, math, pickle, multiprocessing as mp
sys.path.insert(0, os.path.dirname(__file__))
import release_config; release_config.apply()
LIM = 12.0


def audit_one(item):
    g, rec = item
    from shapely.geometry import Polygon, Point
    from stencil.outline import segs_to_path, finalize_record, short_edges, _contour_nodes
    from stencil.weld import problems
    out = {'g': g, 'cp': rec.get('cp'), 'engine': rec.get('engine'), 'n_cuts': len(rec.get('chosen') or []), 'items': []}
    try:
        path, rep = finalize_record(rec)
        out['holes'] = rep['holes_after']; out['ok'] = rep['ok']; out['min_line_seg'] = rep['min_line_seg']
        out['weld'] = len(problems(path, 3.0))
        if not rec.get('chosen'):
            return out
        base = segs_to_path(rec['orig_segs'])
        rects = [Polygon(c['rect']) for c in rec['chosen']]
        dist = lambda q: min(r.distance(Point(q)) for r in rects)
        for e in short_edges(path, base, lim=LIM):
            m = ((e['a'][0] + e['b'][0]) / 2, (e['a'][1] + e['b'][1]) / 2)
            out['items'].append(('short', 'step' if e['step'] else 'smooth', round(e['length'], 1), m, dist(m) > 40.0,
                                 tuple(round(t) for t in e['turns']), e['curve']))
        old = [q for c in base.contours for q, _, _ in _contour_nodes(c)]
        is_old = lambda q: any(abs(q[0] - o[0]) <= 1.5 and abs(q[1] - o[1]) <= 1.5 for o in old)
        for contour in path.contours:
            nodes = _contour_nodes(contour); n = len(nodes)
            if n < 3:
                continue
            for k in range(n):
                pa = nodes[k - 1][0]; pb = nodes[k][0]; pc, _v, c2 = nodes[(k + 1) % n]
                if is_old(pa) and is_old(pb) and is_old(pc):
                    continue
                cin = [c for c in nodes[k][2] if c is not None]; cout = [c for c in c2 if c is not None]
                a = cin[-1] if cin else pa; b = cout[0] if cout else pc
                d1 = (pb[0] - a[0], pb[1] - a[1]); d2 = (b[0] - pb[0], b[1] - pb[1])
                l1, l2 = math.hypot(*d1), math.hypot(*d2)
                if l1 < 1e-6 or l2 < 1e-6:
                    continue
                t = math.degrees(math.acos(max(-1.0, min(1.0, (d1[0] * d2[0] + d1[1] * d2[1]) / (l1 * l2)))))
                if t > 135.0 and dist(pb) <= 6.0:
                    out['items'].append(('acute', 'tip', round(180.0 - t), pb, False, (), False))
    except Exception as ex:
        import traceback
        out['error'] = traceback.format_exc()
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    res = pickle.load(open(sys.argv[1], 'rb'))
    keys = ('segs', 'orig_segs', 'engine', 'chosen', 'cp')
    items = [(g, {k: r.get(k) for k in keys}) for g, r in res.items() if 'segs' in r]
    with mp.Pool(int(os.environ.get('STENCIL_PROCS', max(1, (os.cpu_count() or 2) - 1)))) as pool:
        reps = pool.map(audit_one, items, chunksize=16)
    name = lambda r: (chr(r['cp']) if r.get('cp') else r['g'])
    tot = {'glyphs': len(reps), 'with_cuts': 0, 'corners': 0, 'bridges': 0, 'step': 0, 'smooth': 0, 'far': 0, 'acute': 0,
           'weld': 0, 'holes': 0, 'notok': 0, 'error': 0, 'glyphs_short': 0}
    for r in sorted(reps, key=lambda r: (r.get('cp') or 0x10FFFF, r['g'])):
        if 'error' in r:
            tot['error'] += 1; print('%s ERROR %s' % (name(r), r['error'].splitlines()[-1])); continue
        if r['n_cuts']:
            tot['with_cuts'] += 1; tot[r['engine'] or 'bridges'] += 1
        tot['weld'] += r['weld']; tot['holes'] += r['holes']; tot['notok'] += 0 if r['ok'] else 1
        if r['weld'] or r['holes'] or not r['ok']:
            print('%s %s weld %d holes %d ok %s' % (name(r), r['engine'], r['weld'], r['holes'], r['ok']))
        any_short = False
        for kind, sub, val, q, far, turns, curve in r['items']:
            if kind == 'short':
                if far:
                    tot['far'] += 1
                else:
                    tot[sub] += 1; any_short = True
                print('%s %s short %s %.1f turns %s%s%s at (%.0f, %.0f)' % (name(r), r['engine'], sub, val, '/'.join(str(t) for t in turns),
                                                                       ' curve' if curve else '', ' far' if far else '', q[0], q[1]))
            else:
                tot['acute'] += 1
                print('%s %s acute tip %d deg at (%.0f, %.0f)' % (name(r), r['engine'], val, q[0], q[1]))
        tot['glyphs_short'] += 1 if any_short else 0
    print('# glyphs %(glyphs)d, with cuts %(with_cuts)d (revised %(corners)d, first release %(bridges)d); new short edges under 12 near cuts: '
          'steps %(step)d, smooth %(smooth)d in %(glyphs_short)d glyphs; away from cuts %(far)d; tips under 45 deg %(acute)d; '
          'weld problems %(weld)d; holes %(holes)d; not ok %(notok)d; errors %(error)d' % tot)
    if len(sys.argv) > 2:
        pickle.dump(reps, open(sys.argv[2], 'wb'))
