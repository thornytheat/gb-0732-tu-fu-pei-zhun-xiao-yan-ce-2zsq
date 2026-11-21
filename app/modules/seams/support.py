"""托底认定：判断登记图边的实测偏差是否真的由控制点撑住。

拼缝见证点只提供沿边的独立测距；它们落在图框上，却不一定落在控制点覆盖的
范围内。远离控制点包络时，仿射模型只是顺着最后几个控制点外推，这时算出的
偏差不能被当成「已核」。本模块以控制点的局部加密间距为尺度，逐站判断见证
点在包络内插还是在外推，再按与覆盖判定相同的门槛汇总到每侧和每条边。

判定是确定性的：控制点集合、见证站和门槛一旦固定，结果不随遍历次序改变。
认定写入批次快照，重跑同一批次时原样复用，不重新生成或追加。
"""

import math
from statistics import median

from app.modules.seams.geometry import MIN_COVERAGE, MIN_STATIONS

BACKING_EPSILON_PX = 1e-9
# 与见证覆盖同样的门槛：托底站点至少三站，且在内插范围内跨过六成边长。
MIN_BACKING_STATIONS = MIN_STATIONS
MIN_BACKING_COVERAGE = MIN_COVERAGE
MIN_BASIS_POINTS = 3


def _cross(origin, first, second):
    return ((first[0] - origin[0]) * (second[1] - origin[1])
            - (first[1] - origin[1]) * (second[0] - origin[0]))


def convex_hull(points):
    """控制点包络；不足三点时退化为线段或点。"""
    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique
    lower = []
    for point in unique:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    if length == 0:
        return math.dist(point, start)
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length
    ratio = max(0.0, min(1.0, ratio))
    return math.dist(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def clearance(point, hull):
    """点到控制点包络的距离；落在包络内为 0，越远表示外推越多。"""
    if len(hull) == 1:
        return math.dist(point, hull[0])
    if len(hull) == 2:
        return _segment_distance(point, *hull)
    if all(_cross(hull[index], hull[(index + 1) % len(hull)], point) >= -BACKING_EPSILON_PX
           for index in range(len(hull))):
        return 0.0
    return min(_segment_distance(point, hull[index], hull[(index + 1) % len(hull)])
               for index in range(len(hull)))


def local_reach(pixels):
    """接边处控制点的加密间距尺度：最近邻距离的中位数。

    接边加密时，这个间距就是模型仍可视为内插的最大外推距离；控制点越密，
    允许的包络外余量越小，外推越容易被识别。
    """
    if len(pixels) < 2:
        return None
    nearest = [min(math.dist(point, other) for index, other in enumerate(pixels) if index != station)
               for station, point in enumerate(pixels)]
    return median(nearest)


def sheet_basis(pixels):
    """一幅图可用于托底判定的控制点依据；不足三点时 incapable。"""
    if len(set(pixels)) < MIN_BASIS_POINTS:
        return None
    return {'hull': convex_hull(pixels), 'reach_px': local_reach(pixels), 'points': len(pixels)}


def side_support(stations, pixel_key, along_key, basis, model_available):
    """一条边单侧的托底状态。

    站点到控制点包络的距离不超过本幅控制点的局部加密间距，才算这一侧由实测
    控制点托住；汇总时沿用见证覆盖的「至少三站、跨六成」门槛。
    """
    if not model_available:
        state = 'NO_MODEL'
    elif basis is None:
        state = 'NO_BASIS'
    else:
        state = None
    if state is not None:
        return {'state': state, 'reach_px': basis['reach_px'] if basis else None,
                'stations': len(stations), 'backed': 0, 'coverage': 0.0,
                'max_clearance_px': None, 'clearances': []}
    clearances = []
    for station in stations:
        distance = clearance(station[pixel_key], basis['hull'])
        clearances.append({'name': station['name'], 'along': station[along_key],
                           'clearance_px': distance, 'backed': distance <= basis['reach_px'] + BACKING_EPSILON_PX})
    backed = [row for row in clearances if row['backed']]
    span = (max(row['along'] for row in backed) - min(row['along'] for row in backed)) if backed else 0.0
    state = ('BACKED' if len(backed) >= MIN_BACKING_STATIONS and span + 1e-12 >= MIN_BACKING_COVERAGE
             else 'EXTRAPOLATED')
    return {'state': state, 'reach_px': basis['reach_px'], 'stations': len(clearances),
            'backed': len(backed), 'coverage': span,
            'max_clearance_px': max(row['clearance_px'] for row in clearances) if clearances else None,
            'clearances': clearances}


def edge_support(edge, stations, models, bases):
    """合并两侧托底：只有两侧都被控制点托住，实测偏差才算已核。"""
    first = side_support(stations, 'a_pixel', 'at', bases.get(edge['a']),
                         models[edge['a']]['status'] == 'FIT')
    second = side_support(stations, 'b_pixel', 'bt', bases.get(edge['b']),
                          models[edge['b']]['status'] == 'FIT')
    states = (first['state'], second['state'])
    if 'NO_MODEL' in states or 'NO_BASIS' in states:
        backing = 'UNVERIFIABLE'
    elif states == ('BACKED', 'BACKED'):
        backing = 'BACKED'
    elif 'BACKED' in states:
        backing = 'PARTIAL'
    else:
        backing = 'UNBACKED'
    return {'backing': backing,
            'support': {'a': {'sheet': edge['a'], 'side': edge['a_side'], **first},
                        'b': {'sheet': edge['b'], 'side': edge['b_side'], **second}}}
