"""图幅与整册判定。

判定只读取接缝验核的同一份结论：一条图边只有在偏差实测且两侧都被控制点
托住（`verified`）时才算已核。因此「接缝复核」和「图幅签审」不会各说各话。

每幅图按关联图边分成三类：
- cleared：实测通过且托底成立，可签；
- held：缺模型、覆盖/次序不足或只有模型外推（无托底），停签；
- failed：已知偏差超限，退修。

图幅结论 `READY` 表示全部图边已核，`PARTIAL` 表示只有部分图边已核（其余
停签），`RETURN` 表示有已知超限，`HOLD` 表示没有任何可签图边。整册结论取
`CLEAR` / `PARTIAL` / `STOP` 三种，供册页和签审共用。
"""

from collections import defaultdict

VERDICT_LABELS = {'CLEAR': '能签', 'PARTIAL': '部分停签', 'STOP': '整册须停'}


def _edge_sort(edge):
    return edge['code']


def _held_reason(edges):
    reasons = [edge['reason'] for edge in edges if edge['status'] == 'BLOCKED']
    return next((reason for reason in reasons if reason == 'EDGE_UNBACKED'), reasons[0])


def decisions(catalog, refit, seams):
    incident = defaultdict(list)
    for edge in seams['edges']:
        incident[edge['a']].append(edge)
        incident[edge['b']].append(edge)
    reviews = []
    for sheet in catalog['sheets']:
        code = sheet['code']
        model, edges = refit['sheets'][code], sorted(incident[code], key=_edge_sort)
        cleared = [edge['code'] for edge in edges if edge['status'] == 'PASS' and edge.get('backing') == 'BACKED']
        failed = [edge['code'] for edge in edges if edge['status'] == 'FAIL']
        held = [edge['code'] for edge in edges if edge['status'] == 'BLOCKED']
        if model['status'] != 'FIT':
            status, reason = 'HOLD', model['reason']
        elif failed:
            status, reason = 'RETURN', 'GAP_OVER_LIMIT'
        elif cleared and held:
            status, reason = 'PARTIAL', _held_reason(edges)
        elif cleared:
            status, reason = 'READY', None
        elif held:
            status, reason = 'HOLD', _held_reason(edges)
        else:
            status, reason = 'HOLD', 'NO_EDGE_REGISTERED'
        reviews.append({**sheet, 'status': status, 'reason': reason, 'fit_rms_m': model.get('rms_m'),
                        'edges': [edge['code'] for edge in edges], 'cleared_edges': cleared,
                        'failed_edges': failed, 'held_edges': held,
                        'edge_backing': {edge['code']: edge.get('backing') for edge in edges}})
    return reviews


def conclusion(reviews):
    """整册托底结论：全部图幅可签为能签，无一可签为须停，其余为部分停签。"""
    signable = [row for row in reviews if row['status'] in ('READY', 'PARTIAL') and row['cleared_edges']]
    returned = [row['code'] for row in reviews if row['status'] == 'RETURN']
    if not signable:
        verdict = 'STOP'
    elif len(signable) == len(reviews) and all(row['status'] == 'READY' for row in reviews):
        verdict = 'CLEAR'
    else:
        verdict = 'PARTIAL'
    return {'verdict': verdict, 'label': VERDICT_LABELS[verdict],
            'signable_sheets': [row['code'] for row in signable],
            'held_sheets': [row['code'] for row in reviews if row['status'] in ('HOLD', 'RETURN')],
            'returned_sheets': returned,
            'cleared_edges': sorted({code for row in reviews for code in row['cleared_edges']}),
            'held_edges': sorted({code for row in reviews for code in row['held_edges']}),
            'failed_edges': sorted({code for row in reviews for code in row['failed_edges']})}
