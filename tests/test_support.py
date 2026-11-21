import pytest

from app.modules.review.decisions import conclusion, decisions
from app.modules.seams.support import clearance, convex_hull, local_reach
from conftest import by_key, controls, replace_witness_table

# --- 托底几何 -------------------------------------------------------------

def test_convex_hull_and_clearance_identify_extrapolation():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hull = convex_hull(square + [(5, 5)])
    assert hull == [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert clearance((5, 5), hull) == 0.0
    assert clearance((5, 0), hull) == 0.0
    assert clearance((-4, 5), hull) == pytest.approx(4.0)
    assert clearance((15, 15), hull) == pytest.approx(5 * 2 ** .5)


def test_extrapolation_is_always_strictly_positive_outside_the_envelope():
    # 包络外的点永远不会被误判为内插；判定的正是「有没有被控制点围住」。
    hull = convex_hull([(0, 0), (1200, 0), (1200, 900), (0, 900)])
    assert clearance((600, 1200), hull) == pytest.approx(300.0)
    assert clearance((1201, 450), hull) == pytest.approx(1.0)


def test_local_reach_uses_densest_control_neighborhood_and_is_order_free():
    points = [(0, 0), (100, 0), (200, 0), (600, 0)]
    forward = local_reach(points)
    backward = local_reach(list(reversed(points)))
    assert forward == backward == 100


# --- 接缝验核：托底进入判定 ------------------------------------------------

def test_unbacked_edge_is_blocked_even_when_measured_gap_passes(reference):
    # 删掉 0421 东侧的控制点，只留西侧一条线。HX-QS 仍然可测，但 0421 一侧
    # 覆盖不到东边，验核偏差全靠外推，必须判为无托底而不是通过。
    survey = reference
    pixels = survey.bundle['pixels.csv'].decode('utf-8-sig')
    kept = [line for line in pixels.splitlines(keepends=True)
            if not (line.startswith('0421,') and line.split(',')[2] in {'764', '935', '1040', '1052'})]
    survey.bundle['pixels.csv'] = ''.join(kept).encode()
    edge = by_key(survey.seams['edges'], 'HX-QS')
    assert edge['status'] == 'BLOCKED'
    assert edge['reason'] == 'EDGE_UNBACKED'
    assert edge['backing'] == 'PARTIAL'
    assert edge['support']['a']['state'] == 'EXTRAPOLATED'
    assert edge['support']['b']['state'] == 'BACKED'
    assert edge['max_m'] is not None  # 偏差仍留证，只是不算已核


def test_fully_backed_edge_passes_and_reports_both_sides(reference):
    edge = by_key(reference.seams['edges'], 'HX-QS')
    assert edge['status'] == 'PASS'
    assert edge['backing'] == 'BACKED'
    assert edge['support']['a']['state'] == edge['support']['b']['state'] == 'BACKED'
    assert edge['support']['a']['backed'] >= 3
    assert edge['support']['a']['coverage'] >= .6


def test_missing_model_stays_unverifiable_not_unbacked(field):
    edge = by_key(field.seams['edges'], 'QS-SJ')
    assert (edge['status'], edge['reason'], edge['backing']) == (
        'BLOCKED', 'MODEL_UNAVAILABLE', 'UNVERIFIABLE')
    assert edge['support']['b']['state'] == 'NO_MODEL'
    assert edge['support']['b']['stations'] == 6


# --- 图幅与整册判定 -------------------------------------------------------

def test_partial_sheet_keeps_its_backed_edge_signable(field):
    reviews = {row['code']: row for row in decisions(field.catalog, field.refit, field.seams)}
    # 0421 的 HX-QS 超限（退修），但 HX-LW 有实测且托底，仍有可核图边。
    row = reviews['0421']
    assert (row['status'], row['cleared_edges'], row['failed_edges']) == ('RETURN', ['HX-LW'], ['HX-QS'])
    verdict = conclusion(list(reviews.values()))
    assert verdict['verdict'] == 'PARTIAL'
    assert verdict['signable_sheets'] == ['0431']
    assert verdict['failed_edges'] == ['HX-QS']
    assert verdict['held_edges'] == ['QS-SJ']


def test_one_unbacked_edge_does_not_stop_a_neighbouring_backed_edge(field):
    survey = field
    survey.options = survey.options.model_copy(update={'seam_limit_m': 3})
    reviews = {row['code']: row for row in decisions(survey.catalog, survey.refit, survey.seams)}
    # 放宽上限后 HX-QS 不再超限，但 0421 一侧无托底 -> 0421 部分停签，
    # 仍然保留 HX-LW 的可签资格，而不是整幅卡死。
    assert reviews['0421']['status'] == 'PARTIAL'
    assert reviews['0421']['cleared_edges'] == ['HX-LW']
    assert reviews['0421']['held_edges'] == ['HX-QS']
    assert reviews['0421']['reason'] == 'EDGE_UNBACKED'


def test_all_edges_backed_lets_the_whole_volume_sign(reference):
    reviews = decisions(reference.catalog, reference.refit, reference.seams)
    verdict = conclusion(reviews)
    assert {row['status'] for row in reviews} == {'READY'}
    assert verdict == {'verdict': 'CLEAR', 'label': '能签',
                       'signable_sheets': ['0421', '0422', '0431', '0432'],
                       'held_sheets': [], 'returned_sheets': [],
                       'cleared_edges': ['HX-LW', 'HX-QS', 'QS-SJ'],
                       'held_edges': [], 'failed_edges': []}


def test_no_signable_sheet_stops_the_whole_volume(reference):
    survey = reference
    # 让每幅图都失去模型：清空控制点，四幅都无法拟合。
    header = survey.bundle['pixels.csv'].decode('utf-8-sig').splitlines()[0]
    survey.bundle['pixels.csv'] = (header + '\n').encode()
    survey.bundle['ground.csv'] = survey.bundle['ground.csv'][:0]
    replace_witness_table(survey, '拼缝,证点,甲列,甲行,乙列,乙行,备注\n')
    reviews = decisions(survey.catalog, survey.refit, survey.seams)
    assert conclusion(reviews)['verdict'] == 'STOP'


def test_backing_is_deterministic_across_repeated_evaluation(reference):
    first = decisions(reference.catalog, reference.refit, reference.seams)
    second = decisions(reference.catalog, reference.refit, reference.seams)
    assert first == second
    assert conclusion(first) == conclusion(second)
