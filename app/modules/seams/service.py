from app.modules.seams.geometry import (DISTANCE_EPSILON_M, MIN_COVERAGE, MIN_STATIONS, coverage,
                                        endpoints, measure_gap)
from app.modules.seams.support import edge_support, sheet_basis
from app.modules.seams.witnesses import TrainingIndex, read_witnesses, split_by_edge


def inspect_edge(edge, rows, quarantined, a, b, models, limit, bases):
    span = coverage(rows)
    result = {**edge, 'count': len(rows), 'coverage': span, 'limit_m': limit, 'stations': rows,
              'a_line': None, 'b_line': None, 'max_m': None, 'median_m': None}
    reasons = []
    if not all(models[code]['status'] == 'FIT' for code in (edge['a'], edge['b'])):
        reasons.append('MODEL_UNAVAILABLE')
    if len(rows) < MIN_STATIONS or min(span) + 1e-12 < MIN_COVERAGE:
        reasons.append('EDGE_COVERAGE')
    direction = -1 if edge['reverse'] else 1
    if any((right['bt'] - left['bt']) * direction <= 0 for left, right in zip(rows, rows[1:])):
        reasons.append('EDGE_ORDER')
    if quarantined:
        reasons.append('EDGE_DIRTY')
    # Twisted correspondence is not a valid physical gap measurement.
    if 'MODEL_UNAVAILABLE' not in reasons and 'EDGE_ORDER' not in reasons:
        left, right = (models[code]['model'] for code in (edge['a'], edge['b']))
        result.update(measure_gap(rows, left, right, endpoints(a, edge['a_side']), endpoints(b, edge['b_side'])))
    support = edge_support(edge, rows, models, bases)
    result.update(support)
    # 托底只影响「实测偏差能否算已核」，不改变偏差本身。缺模型或次序不合时
    # 托底本就无法成立，状态以 BLOCKED 为准，不另立名目。
    if result['max_m'] is not None and result['max_m'] > limit + DISTANCE_EPSILON_M:
        result.update(status='FAIL', reason='GAP_OVER_LIMIT', reasons=['GAP_OVER_LIMIT', *reasons])
    elif reasons:
        result.update(status='BLOCKED', reason=reasons[0], reasons=reasons)
    elif support['backing'] != 'BACKED':
        result.update(status='BLOCKED', reason='EDGE_UNBACKED', reasons=['EDGE_UNBACKED'])
    else:
        result.update(status='PASS', reason=None, reasons=[])
    return result


def check_seams(intake, converted, pairing, refit, seam_limit_m):
    catalog, table = intake['catalog'], intake['tables']['witness.csv']
    sheets = {sheet['code']: sheet for sheet in catalog['sheets']}
    by_edge, issues = split_by_edge(table, catalog)
    training = TrainingIndex(converted['pixels'], pairing['aliases'])
    controls = {code: [] for code in sheets}
    for point in refit['accepted']:
        controls[point['sheet']].append(point['pixel'])
    bases = {code: sheet_basis(pixels) for code, pixels in controls.items()}
    results = []
    for edge in catalog['edges']:
        code, a, b = edge['code'], sheets[edge['a']], sheets[edge['b']]
        rows, rejected = read_witnesses(by_edge[code], edge, a, b, training)
        issues[code].extend(rejected)
        results.append(inspect_edge(edge, rows, issues[code], a, b, refit['sheets'], seam_limit_m, bases))
    quarantine = sorted((row for group in issues.values() for row in group), key=lambda row: row['source']['line'])
    return {'edges': results, 'quarantine': quarantine, 'input_count': table['records']}
