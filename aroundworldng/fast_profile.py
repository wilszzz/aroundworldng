"""Road heights for the whole graph at once (fast generator, index time).

Per-segment profiles from a 24 m DEM gave 112 % ramps and 3.5 m pits on short pieces
(docs/PERFORMANCE.md). Here every road is sampled into stations (shared at graph
nodes) and the heights minimise

    sum w*m*(h - target)^2 + ALPHA * sum (dh)^2/l + BETA * sum (d2h)^2/l^3

(data, grade, change of grade), solved by Jacobi-preconditioned conjugate gradients. A node
has one height for every road that meets there, so tiles and junction mouths agree by
construction. Bridges pull up and real tunnels pull down only softly; their approaches become
ramps. A bridge spans the height of its abutments: it does not follow the river bed under
the span. Where it crosses a road in plan, the deck and the road under it share the
CLEARANCE: the deck rises and the lower road dips into a cutting. A 24 m DEM has no cuttings,
and the soft pull alone left Juri's overpasses 1.3 m over the ring road. Letting only the deck
rise made an 11 m hill of every short overpass, and a dual carriageway's two bridges (their
ribbons overlap, their roads are joined) lifted each other 800 m on the Tallinna ringtee.
tunnel=building_passage is an arch through a house, at ground level.
"""
import math

import numpy as np

STEP = 20.0            # station spacing, m
ALPHA = 40.0 ** 2      # grade smoothing length 40 m
BETA = 50.0 ** 4       # grade-change smoothing length 50 m
BRIDGE_CLEAR, TUNNEL_DEPTH, SOFT = 6.5, 7.0, 0.5
# Grade weight on the first station gap out of a junction (3+ roads): roads leave it level, so
# roads that overlap near it in plan are at one height. With free grades a link and the main
# road diverged by 0.78 m over the main road's sidewalk, and junction polygons tilted 24 %.
JUNCTION_FLAT = 10.0
# Ground roads whose surfaces touch in plan (two carriageways of a divided road, a lane beside
# a street) are tied to one height: on Khreshchatyk the carriageways overlapped by 1 m with
# profiles up to 1.02 m apart.
COUPLE = 1000.0
# Parallel carriageways of dual carriageways, avenues, and divided boulevards are locked
# with high rigidity to eliminate ski-jump ramps and asymmetric terrain cliffs:
COUPLE_DUAL = 3000.0
# Intra-quarter courtyard roads and driveways regularized to the local courtyard plane:
COUPLE_COURTYARD = 800.0
# A deck over a road: 4.5 m headroom + the deepest girder (ROADS.deckDepth of a
# main road, 1.5 m), per layer. A street slab is 1 m and keeps a little more air.
CLEARANCE, CLEAR_WEIGHT, CLEAR_PASSES = 6.0, 1e4, 12
# Reserve the possible sidewalks of the rendered deck; clearance is measured at its
# soffit over the whole lower carriageway, including skew crossings. Numerical slack
# stays above the 4.5 m headroom rather than silently accepting a shortfall from it.
DECK_OVERHANG, CLEAR_SLACK, CLEAR_TOL = 2., .1, .05
CLEAR_EXTRA = 6.
# Steepest grade the solve may make by class (Level 1 skeleton max 4-5%, Level 2 courtyards max 4-5%):
GRADE_MAX = {'motorway': .04, 'trunk': .04, 'primary': .05, 'secondary': .05, 'tertiary': .055,
             'motorway_link': .05, 'trunk_link': .05, 'primary_link': .06, 'secondary_link': .06,
             'residential': .05, 'living_street': .04, 'service': .05,
             'pedestrian': .04, 'footway': .05, 'cycleway': .05, 'path': .07, 'unclassified': .06}
GRADE_DEFAULT, GRADE_PASSES, STIFF_MAX = .07, 4, 30.


def crossings(pos, seg_of, same, upper, lower, widths, levels):
    """Vertices of the overlap between upper deck and lower road station ribbons.

    Heights vary affinely along each straight station edge, so their least separation
    over the common polygon occurs at a vertex. Centre-line intersections alone missed
    a wide road's edges and bridges that overlap a road without their axes crossing.
    Returns edge starts (a, b) and longitudinal parameters (u, t) at each vertex.
    """
    e0 = np.flatnonzero(same)
    top, bottom = e0[upper[e0]], e0[lower[e0]]
    if not len(top) or not len(bottom):
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0), np.zeros(0)
    cell = 32.0
    mid = (pos[bottom] + pos[bottom + 1]) / 2
    key = np.floor(mid / cell).astype(np.int64)
    bins = {}
    for k, (x, y) in enumerate(key.tolist()):
        bins.setdefault((x, y), []).append(k)
    # A midpoint hash keeps country-sized indexes compact. Every lower edge is at
    # most STEP long; expand a deck's query by the largest lower half width and length.
    reach = float(np.max(widths[bottom])) / 2 + STEP / 2

    def ribbon(p, r, half):
        normal = np.array([-r[1], r[0]]) * (half / max(float(np.linalg.norm(r)), 1e-9))
        return [p - normal, p + r - normal, p + r + normal, p + normal]

    def clip(poly, q, d, half):
        length = float(np.linalg.norm(d))
        if length < 1e-9:
            return []
        axis = d / length
        normal = np.array([-axis[1], axis[0]])
        # dot(p-q, n) >= bound: longitudinal ends and both lateral edges.
        for n, bound in ((axis, 0.), (-axis, -length), (normal, -half), (-normal, -half)):
            if not poly:
                break
            result = []
            a = poly[-1]; da = float((a - q) @ n) - bound
            for b in poly:
                db = float((b - q) @ n) - bound
                if (da >= 0) != (db >= 0):
                    result.append(a + (b - a) * (da / (da - db)))
                if db >= 0:
                    result.append(b)
                a, da = b, db
            poly = result
        return poly

    out = ([], [], [], [])
    for a in top.tolist():
        p, r = pos[a], pos[a + 1] - pos[a]
        poly = ribbon(p, r, widths[a] / 2 + DECK_OVERHANG)
        low = np.min(poly, axis=0); high = np.max(poly, axis=0)
        lo = np.floor((low - reach) / cell).astype(int)
        hi = np.floor((high + reach) / cell).astype(int)
        near = [k for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1)
                for k in bins.get((x, y), ())]
        if not near:
            continue
        b = bottom[near]
        b = b[(seg_of[a] != seg_of[b]) & (levels[a] > levels[b])]
        q, d = pos[b], pos[b + 1] - pos[b]
        half = widths[b] / 2
        hit = np.all(np.maximum(q, q + d) + half[:, None] >= low, axis=1)
        hit &= np.all(np.minimum(q, q + d) - half[:, None] <= high, axis=1)
        for k in np.flatnonzero(hit).tolist():
            overlap = clip(poly, q[k], d[k], half[k])
            for point in overlap:
                u = np.clip(float((point - p) @ r) / max(float(r @ r), 1e-9), 0, 1)
                t = np.clip(float((point - q[k]) @ d[k]) / max(float(d[k] @ d[k]), 1e-9), 0, 1)
                out[0].append(a); out[1].append(int(b[k])); out[2].append(u); out[3].append(t)
    return (np.array(out[0], int), np.array(out[1], int), np.array(out[2]), np.array(out[3]))


def close_pairs(pos, seg_of, width, ground_or_levels, same, is_urban=None,
                is_major=None, is_oneway=None, names=None):
    """Station -> nearby edge of another ground segment whose strip touches it: lateral
    distance to the edge < half widths + 0.5 m (weight COUPLE).
    Also finds:
    1. Dual Carriageway pairs (parallel ways within 32m): locked with high rigidity COUPLE_DUAL.
    2. Intra-quarter courtyard pairs (residential/service roads within 35m): regularized with COUPLE_COURTYARD."""
    cell = 32.0
    e0 = np.flatnonzero(same)                     # edge e0 -> e0+1, both of one segment
    if not len(e0):
        if is_urban is not None or is_major is not None:
            return (np.zeros(0, int), np.zeros(0, int), np.zeros(0)), (np.zeros(0, int), np.zeros(0, int), np.zeros(0), np.zeros(0))
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0)

    mid = (pos[e0] + pos[e0 + 1]) / 2
    M = 1 << 21
    def keys(xy, dx=0, dy=0):
        return (np.floor(xy[:, 0] / cell).astype(np.int64) + dx + M) * (2 * M) + np.floor(xy[:, 1] / cell).astype(np.int64) + dy + M
    ekey = keys(mid); order = np.argsort(ekey, kind='stable'); skey = ekey[order]

    # Precalculate unit direction vectors of edges
    dxy_e = pos[e0 + 1] - pos[e0]
    len_e = np.maximum(np.hypot(dxy_e[:, 0], dxy_e[:, 1]), 1e-9)
    dir_e = dxy_e / len_e[:, None]

    # Precalculate unit direction vectors of stations
    dir_st = np.zeros_like(pos)
    dir_st[e0] = dir_e
    end_st = np.setdiff1d(np.arange(len(pos)), e0)
    valid_prev = end_st[end_st > 0]
    prev_in_e0 = same[valid_prev - 1]
    valid_prev = valid_prev[prev_in_e0]
    if len(valid_prev):
        dir_st[valid_prev] = dir_st[valid_prev - 1]

    # Handle float levels vs boolean ground
    is_bool_ground = np.asarray(ground_or_levels).dtype == bool
    if is_bool_ground:
        ground_arr = ground_or_levels
        level_arr = None
    else:
        ground_arr = None
        level_arr = np.asarray(ground_or_levels, dtype=float)

    out = ([], [], [])
    extra_out = ([], [], [], [])
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nk = keys(pos, dx, dy)
            lo = np.searchsorted(skey, nk, 'left'); hi = np.searchsorted(skey, nk, 'right')
            cnt = hi - lo
            if not cnt.sum():
                continue
            ia = np.repeat(np.arange(len(pos)), cnt)
            ie_idx = order[lo[ia] + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))]
            ie = e0[ie_idx]

            keep = (seg_of[ia] != seg_of[ie])
            if level_arr is not None:
                # Same vertical level (allows parallel carriageway bridges to couple with each other!)
                keep &= (np.abs(level_arr[seg_of[ia]] - level_arr[seg_of[ie]]) < 0.5)
            elif ground_arr is not None:
                keep &= (ground_arr[ia] & ground_arr[ie])

            if not keep.any():
                continue
            ia, ie, ie_idx = ia[keep], ie[keep], ie_idx[keep]
            a, b = pos[ie], pos[ie + 1]
            ab = b - a; L2 = np.maximum((ab ** 2).sum(1), 1e-9)
            t = np.clip(((pos[ia] - a) * ab).sum(1) / L2, 0, 1)
            proj = a + ab * t[:, None]
            d = np.linalg.norm(pos[ia] - proj, axis=1)

            # 1. Direct touch coupling
            touch_limit = (width[ia] + width[ie]) / 2 + 0.5
            touch = d < touch_limit
            out[0].append(ia[touch]); out[1].append(ie[touch]); out[2].append(t[touch])

            # 2. Non-touching candidates within reach (up to 35m)
            non_touch = (~touch) & (d < 35.0)
            if not non_touch.any():
                continue

            nia, nie, nit, nid, nie_sub = ia[non_touch], ie[non_touch], t[non_touch], d[non_touch], ie_idx[non_touch]
            sa, sb = seg_of[nia], seg_of[nie]

            # Parallelism / collinearity between station heading and edge heading
            dot = (dir_st[nia] * dir_e[nie_sub]).sum(axis=1)
            is_parallel = np.abs(dot) >= 0.65

            # Dual Carriageway Vertical Locking
            is_dual = is_parallel & (nid < 32.0)
            has_major = is_major is not None
            has_oneway = is_oneway is not None
            has_names = names is not None

            if has_major or has_oneway or has_names:
                dual_cond = np.zeros(len(nia), bool)
                if has_major:
                    dual_cond |= (is_major[sa] & is_major[sb])
                if has_oneway:
                    dual_cond |= (is_oneway[sa] | is_oneway[sb])
                if has_names:
                    name_match = (names[sa] != '') & (names[sa] == names[sb])
                    dual_cond |= name_match
                is_dual &= dual_cond
            else:
                is_dual &= (nid < 25.0)

            w_dual = COUPLE_DUAL * (1.0 - (nid / 32.0) ** 2)

            # Courtyard Intra-Quarter Regularization
            is_court = np.zeros(len(nia), bool)
            if is_urban is not None:
                is_court = (~is_dual) & (nid < 35.0) & (is_urban[sa] & is_urban[sb])
                w_court = COUPLE_COURTYARD * (1.0 - nid / 35.0)
            else:
                w_court = np.zeros(len(nia))

            couple_mask = is_dual | is_court
            if couple_mask.any():
                cia = nia[couple_mask]
                cie = nie[couple_mask]
                cit = nit[couple_mask]
                cw = np.where(is_dual[couple_mask], w_dual[couple_mask], w_court[couple_mask])
                extra_out[0].append(cia); extra_out[1].append(cie); extra_out[2].append(cit); extra_out[3].append(cw)

    touch_res = tuple(np.concatenate(v) if v else np.zeros(0, int if i < 2 else float) for i, v in enumerate(out))
    if is_urban is not None or is_major is not None:
        extra_res = tuple(np.concatenate(v) if v else np.zeros(0, int if i < 3 else float) for i, v in enumerate(extra_out))
        return touch_res, extra_res
    return touch_res


def layer(tags):
    try:
        value = abs(float(str(tags.get('layer', 1)).split(';')[0]))
        return value if math.isfinite(value) else 1.
    except (TypeError, ValueError):
        return 1.


def kind(tags):
    if tags.get('bridge') not in (None, 'no'):
        return 'bridge'
    if tags.get('tunnel') not in (None, 'no', 'building_passage'):
        return 'tunnel'
    return 'road'


def stations(segments, node_index):
    """All segments' stations at once (162k segments: a Python loop cost 12 s).

    Returns per-station arc length s, variable id, position, owning segment and the start of
    each segment's run; ends map to their graph node, interior stations get fresh ids."""
    n_seg = len(segments)
    lens = np.array([len(seg['xy']) for seg in segments])
    xy = np.concatenate([np.asarray(seg['xy'], dtype=float) for seg in segments])
    first = np.r_[0, np.cumsum(lens)[:-1]]
    step = np.r_[0., np.linalg.norm(np.diff(xy, axis=0), axis=1)]
    step[first] = 1.                       # a 1 m gap keeps the global arc length increasing
    cum = np.cumsum(step)
    base = cum[first]                      # each segment's start on the global arc length
    length = cum[first + lens - 1] - base
    n = np.maximum(1, np.ceil(length / STEP)).astype(np.int64)
    count = n + 1
    run = np.r_[0, np.cumsum(count)[:-1]]
    seg_of = np.repeat(np.arange(n_seg), count)
    k = np.arange(count.sum()) - run[seg_of]
    s = length[seg_of] * k / n[seg_of]
    g = base[seg_of] + s
    pos = np.column_stack([np.interp(g, cum, xy[:, 0]), np.interp(g, cum, xy[:, 1])])
    a = np.array([node_index[seg['nodes'][0]] for seg in segments])
    b = np.array([node_index[seg['nodes'][1]] for seg in segments])
    inner_run = len(node_index) + np.r_[0, np.cumsum(n - 1)[:-1]]
    ids = inner_run[seg_of] + k - 1
    ids[k == 0] = a[seg_of[k == 0]]
    ends = k == n[seg_of]
    ids[ends] = b[seg_of[ends]]
    nvar = len(node_index) + int((n - 1).sum())
    return s, ids, pos, seg_of, run, nvar


def csr(rows, cols, vals, n):
    """COO -> CSR with duplicates summed (no SciPy here)."""
    key = rows * n + cols
    order = np.argsort(key, kind='stable')
    key, vals = key[order], vals[order]
    uniq, start = np.unique(key, return_index=True)
    data = np.add.reduceat(vals, start)
    r, c = uniq // n, uniq % n
    ptr = np.r_[0, np.cumsum(np.bincount(r, minlength=n))]
    return ptr, c, data


def spans(segments, node_index, kinds, dem):
    """{node variable: height} of the nodes inside a bridge mapped in pieces.

    Only an end on the ground is an abutment: a node where nothing but bridges meet is a split
    of the way, and the DEM under it is the water (the Golden Gate's deck, split at its north
    tower, dived to the sea). Between the abutments the heights run linearly along the deck."""
    ends = [(k, node_index[seg['nodes'][0]], node_index[seg['nodes'][1]]) for k, seg in enumerate(segments)]
    ground = {n for k, a, b in ends if kinds[k] <= 0 for n in (a, b)}
    links = {}
    for k, a, b in ends:
        if kinds[k] > 0 and a != b:
            xy = np.asarray(segments[k]['xy'], dtype=float)
            weight = 1. / max(float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum()), .5)
            links.setdefault(a, []).append((b, weight))
            links.setdefault(b, []).append((a, weight))
    inside = {n for n, near in links.items() if n not in ground and len(near) >= 2}
    heights, seen = {}, set()
    for start in inside:
        if start in seen:
            continue
        part, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            part.append(n)
            for m, _ in links[n]:
                if m in inside and m not in seen:
                    seen.add(m)
                    stack.append(m)
        where = {n: i for i, n in enumerate(part)}
        system, values, anchored = np.zeros((len(part), len(part))), np.zeros(len(part)), False
        for n, i in where.items():
            for m, weight in links[n]:
                system[i, i] += weight
                if m in where:
                    system[i, where[m]] -= weight
                else:
                    values[i] += weight * dem[m]
                    anchored = True
        if anchored:                       # a ring of bridges with no way down keeps its DEM
            heights.update(zip(part, np.linalg.solve(system, values).tolist()))
    return heights


def solve(segments, sample, iterations=400, tol=1e-3, emit=None):
    """Heights for every segment's stations. sample(xy) -> DEM height (vectorised, NaN outside).

    Returns a list of (s, h) per segment and {node id: h}."""
    nodes = sorted({n for seg in segments for n in seg['nodes']})
    node_index = {n: k for k, n in enumerate(nodes)}
    s, ids, pos_st, seg_of, run, nvar = stations(segments, node_index)
    pos = np.zeros((nvar, 2)); pos[ids] = pos_st
    same = seg_of[1:] == seg_of[:-1]                       # consecutive stations of one segment
    ds = np.diff(s)
    ea, eb, el = ids[:-1][same], ids[1:][same], np.maximum(ds[same], .5)
    mass = np.bincount(ea, el / 2, nvar) + np.bincount(eb, el / 2, nvar)
    tri = same[:-1] & same[1:]
    ta, tb, tc = ids[:-2][tri], ids[1:-1][tri], ids[2:][tri]
    tl = np.maximum((ds[:-1][tri] + ds[1:][tri]) / 2, .5)
    dem = sample(pos)
    # whole OSM ways reach past the downloaded DEM (their tiles fail no_dem anyway): there the
    # height only follows the neighbours
    known = np.isfinite(dem)
    dem[~known] = np.median(dem[known]) if known.any() else 0.
    target = dem.copy()
    urban_types = {'residential', 'living_street', 'service', 'pedestrian', 'footway', 'cycleway', 'path', 'unclassified'}
    major_types = {'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link',
                   'secondary', 'secondary_link', 'tertiary', 'tertiary_link'}
    is_urban_seg = np.array([seg['tags'].get('highway') in urban_types for seg in segments], bool)
    is_major_seg = np.array([seg['tags'].get('highway') in major_types for seg in segments], bool)
    is_oneway_seg = np.array([
        str(seg['tags'].get('oneway', '')).lower() in ('yes', '1', 'true', '-1') or
        seg['tags'].get('highway') == 'motorway'
        for seg in segments
    ], bool)
    seg_names = np.array([str(seg['tags'].get('name') or seg['tags'].get('ref') or '') for seg in segments])

    kinds = np.array([{'road': 0, 'bridge': 1, 'tunnel': -1}[kind(seg['tags'])] for seg in segments])
    layers = np.array([max(1., layer(seg['tags'])) for seg in segments])
    levels = kinds * layers
    k_st = kinds[seg_of]
    bounds = np.r_[run, len(s)]

    # Level 1 (Major Roads): smooth DEM along highway stations to remove high-frequency terrain noise
    for k in np.flatnonzero(is_major_seg):
        sl = slice(int(bounds[k]), int(bounds[k + 1]))
        sid = ids[sl]
        if len(sid) >= 3:
            dem_vals = target[sid]
            sm = np.empty_like(dem_vals)
            sm[0] = 0.7 * dem_vals[0] + 0.3 * dem_vals[1]
            sm[-1] = 0.7 * dem_vals[-1] + 0.3 * dem_vals[-2]
            sm[1:-1] = 0.25 * dem_vals[:-2] + 0.50 * dem_vals[1:-1] + 0.25 * dem_vals[2:]
            target[sid] = sm

    # Level 2 (Courtyard Roads): soften DEM noise spikes relative to segment median
    for k in np.flatnonzero(is_urban_seg):
        sl = slice(int(bounds[k]), int(bounds[k + 1]))
        sid = ids[sl]
        if len(sid) >= 3:
            dem_vals = target[sid]
            med = np.median(dem_vals)
            clipped = np.clip(dem_vals, med - 2.0, med + 2.0)
            target[sid] = 0.4 * dem_vals + 0.6 * clipped

    is_urban_var = np.zeros(nvar, bool)
    is_urban_var[ids] = is_urban_seg[seg_of]
    weight = np.where(known, np.where(is_urban_var, 0.35, 1.0), 1e-3)
    inner = (k_st < 0) & (ids >= len(node_index))
    target[ids[inner]] = dem[ids[inner]] - TUNNEL_DEPTH * layers[seg_of[inner]]
    weight[ids[inner]] = np.where(known[ids[inner]], SOFT, 1e-3)
    # A bridge deck follows the chord between its abutments across ravines/water.
    # It does not artificially rise +6.5m above flat ground. Crossing over lower roads
    # is solved dynamically by the active clearance springs.
    deck = spans(segments, node_index, kinds, dem) if (kinds > 0).any() else {}
    for k in np.flatnonzero(kinds > 0):
        sl = slice(int(bounds[k]), int(bounds[k + 1]))
        sid = ids[sl]
        for n in (int(sid[0]), int(sid[-1])):
            if n in deck:
                target[n] = deck[n]
                weight[n] = SOFT if known[n] else 1e-3
        interior = sid >= len(node_index)
        if not interior.any():
            continue
        ss = s[sl]
        span = float(ss[-1] - ss[0])
        t = (ss - ss[0]) / span if span > 1e-6 else np.zeros(len(ss))
        chord = deck.get(int(sid[0]), dem[sid[0]]) * (1 - t) + deck.get(int(sid[-1]), dem[sid[-1]]) * t
        target[sid[interior]] = chord[interior]
        weight[sid[interior]] = np.where(known[sid[interior]], SOFT, 1e-3)
    mw = weight * np.maximum(mass, .5)
    degree = np.bincount(np.array([node_index[n] for seg in segments for n in seg['nodes']]), minlength=nvar)
    flat = np.where((degree[ea] >= 3) | (degree[eb] >= 3), JUNCTION_FLAT, 1.)
    hw_types = [segments[k]['tags'].get('highway', '') for k in seg_of[:-1][same]]
    is_urban_edge = np.array([h in urban_types for h in hw_types])
    is_major_edge = np.array([h in major_types for h in hw_types])
    edge_stiff = np.where(is_major_edge, 3.0, np.where(is_urban_edge, 2.5, 1.0))
    ce = ALPHA * flat * edge_stiff / el

    hw_types_tri = [segments[k]['tags'].get('highway', '') for k in seg_of[:-2][tri]]
    is_major_tri = np.array([h in major_types for h in hw_types_tri])
    ct = BETA * np.where(is_major_tri, 4.0, 1.5) / tl ** 3

    edge_max = np.array([GRADE_MAX.get(h, GRADE_DEFAULT) for h in hw_types])
    dem_grade = np.abs(dem[eb] - dem[ea]) / el + .01
    dem_grade_allowed = np.where(is_major_edge, np.minimum(dem_grade, 0.05),
                        np.where(is_urban_edge, np.minimum(dem_grade, 0.07), dem_grade))
    edge_max = np.maximum(edge_max, dem_grade_allowed)
    stiff = np.ones(len(ea))
    widths = np.clip(np.array([seg.get('width', 4.) for seg in segments]), .5, 80.)
    (pa, pe, pt), (upa, upe, upt, upw) = close_pairs(
        pos_st, seg_of, widths[seg_of], levels[seg_of], same,
        is_urban=is_urban_seg, is_major=is_major_seg, is_oneway=is_oneway_seg, names=seg_names
    )
    va, vb1, vb2 = ids[pa], ids[pe], ids[pe + 1]
    keep = (va != vb1) & (va != vb2)
    va, vb1, vb2, pt = va[keep], vb1[keep], vb2[keep], pt[keep]
    if len(upa):
        uva, uvb1, uvb2 = ids[upa], ids[upe], ids[upe + 1]
        ukeep = (uva != uvb1) & (uva != uvb2)
        uva, uvb1, uvb2, upt, upw = uva[ukeep], uvb1[ukeep], uvb2[ukeep], upt[ukeep], upw[ukeep]
    else:
        uva, uvb1, uvb2, upt, upw = np.zeros(0, int), np.zeros(0, int), np.zeros(0, int), np.zeros(0), np.zeros(0)
    # a bridge over a road: the deck (not the road under it) reaches clear above that road.
    # A lower road may itself be a bridge (stacked motorway interchanges).
    # Compare vertical levels, not just bridge versus non-bridge: short spans
    # have no interior station and their soft DEM offset alone can be zero.
    levels = kinds * layers
    xa, xb, xu, xt = crossings(pos_st, seg_of, same, k_st > 0, np.ones(len(k_st), bool),
                               widths[seg_of], levels[seg_of])
    xv = (ids[xa], ids[xa + 1], ids[xb], ids[xb + 1])
    apart = levels[seg_of[xa]] > levels[seg_of[xb]]
    for i in range(2):
        for j in range(2, 4):
            apart &= xv[i] != xv[j]                # not a ramp leaving the bridge's own node
    xa, xb, xu, xt = xa[apart], xb[apart], xu[apart], xt[apart]
    # A dual carriageway's two bridges run side by side: each one's deck ribbon overlaps the other
    # direction's approach, whose road is joined to the first by the carriageway's own nodes. Lifting
    # that road to clear the deck lifts the deck again (a feedback of 800 m on the Tallinna ringtee).
    # Only a pair whose centre lines really cross in plan is an overpass.
    if len(xa):
        def centre_lines_cross(u, w):
            a, b = np.asarray(segments[u]['xy'], float), np.asarray(segments[w]['xy'], float)
            p, r = a[:-1, None, :], (a[1:] - a[:-1])[:, None, :]
            q, t = b[None, :-1, :], (b[1:] - b[:-1])[None, :, :]
            cross = r[..., 0] * t[..., 1] - r[..., 1] * t[..., 0]
            d = q - p
            with np.errstate(divide='ignore', invalid='ignore'):
                su = (d[..., 0] * t[..., 1] - d[..., 1] * t[..., 0]) / cross
                sv = (d[..., 0] * r[..., 1] - d[..., 1] * r[..., 0]) / cross
            return bool(np.any((np.abs(cross) > 1e-9) & (su >= 0) & (su <= 1) & (sv >= 0) & (sv <= 1)))
        verdict = {}
        for u, w in set(zip(seg_of[xa].tolist(), seg_of[xb].tolist())):
            verdict[u, w] = centre_lines_cross(u, w)
        genuine = np.array([verdict[u, w] for u, w in zip(seg_of[xa].tolist(), seg_of[xb].tolist())], bool)
        xa, xb, xu, xt = xa[genuine], xb[genuine], xu[genuine], xt[genuine]
    # The deck and the road under it share the clearance, each taking its part: a deck alone
    # lifted the full 6 m over a 24 m DEM that has no cutting (an 11 m hill at every short
    # overpass of the Tartu mnt), and a lower road tied to its own deck then raised it again.
    xv = (ids[xa], ids[xa + 1], ids[xb], ids[xb + 1])
    xc = (1 - xu, xu, -(1 - xt), -xt)
    separation = CLEARANCE * (levels[seg_of[xa]] - levels[seg_of[xb]]) + CLEAR_SLACK
    def clearance(h):
        return separation + 0 * h[ids[xb]]
    clear = clearance(target)
    # the road under a bridge passes close to the bridge's approaches in plan: they are not
    # one surface, so no coupling ties them (it dragged the trunk down to the underpass)
    if len(xa):
        touching = {}
        for k, seg in enumerate(segments):
            for n in seg['nodes']:
                touching.setdefault(n, set()).add(k)
        def approach(u, hops=2):
            near = {u}
            for _ in range(hops):
                near |= {m for k in near for n in segments[k]['nodes'] for m in touching[n]}
            return near
        apart_of = {}
        for u, w in set(zip(seg_of[xa].tolist(), seg_of[xb].tolist())):
            over, below = approach(u), approach(w) - {u}
            for k in over - below:
                apart_of.setdefault(k, set()).update(below - over)
            for k in below - over:
                apart_of.setdefault(k, set()).update(over - below)
        sa, sb = seg_of[pa[keep]], seg_of[pe[keep]]
        free = np.array([b not in apart_of.get(a, ()) for a, b in zip(sa.tolist(), sb.tolist())], bool)
        va, vb1, vb2, pt = va[free], vb1[free], vb2[free], pt[free]
        if len(uva):
            usa, usb = seg_of[upa[ukeep]], seg_of[upe[ukeep]]
            ufree = np.array([b not in apart_of.get(a, ()) for a, b in zip(usa.tolist(), usb.tolist())], bool)
            uva, uvb1, uvb2, upt, upw = uva[ufree], uvb1[ufree], uvb2[ufree], upt[ufree], upw[ufree]
    # residual h_a - (1-t) h_b1 - t h_b2, weight COUPLE
    cv, cw = (va, vb1, vb2), (np.ones(len(va)), -(1 - pt), -pt)
    ucv, ucw = (uva, uvb1, uvb2), (np.ones(len(uva)), -(1 - upt), -upt)
    trip, coef = (ta, tb, tc), (1., -2., 1.)

    def assemble():
        g = ce * stiff
        rows = [np.arange(nvar), ea, eb, ea, eb]
        cols = [np.arange(nvar), ea, eb, eb, ea]
        vals = [mw, g, g, -g, -g]
        for i in range(3):
            for j in range(3):
                rows.append(cv[i]); cols.append(cv[j]); vals.append(COUPLE * cw[i] * cw[j])
        if len(uva):
            for i in range(3):
                for j in range(3):
                    rows.append(ucv[i]); cols.append(ucv[j]); vals.append(upw * ucw[i] * ucw[j])
        for i in range(3):
            for j in range(3):
                rows.append(trip[i]); cols.append(trip[j]); vals.append(ct * coef[i] * coef[j])
        ptr, col, data = csr(np.concatenate(rows), np.concatenate(cols), np.concatenate(vals), nvar)
        diag0 = np.bincount(np.repeat(np.arange(nvar), np.diff(ptr)), np.where(
            col == np.repeat(np.arange(nvar), np.diff(ptr)), data, 0.), nvar)
        return ptr, col, data, diag0
    ptr, col, data, diag0 = assemble()

    # the clearance springs act only where a deck would be too low (a lower bound): on a
    # crossing in an active set, outside the CSR matrix
    active = np.zeros(len(xa))

    def gap(h):
        return sum(c * h[v] for c, v in zip(xc, xv))

    def matvec(h, springs=True):
        out = np.add.reduceat(data * h[col], ptr[:-1])
        if springs and active.any():
            g = CLEAR_WEIGHT * active * gap(h)
            for c, v in zip(xc, xv):
                out += np.bincount(v, g * c, nvar)
        return out

    def cg(b):
        diag = diag0 + sum(np.bincount(v, CLEAR_WEIGHT * active * c * c, nvar) for c, v in zip(xc, xv))
        x = np.zeros(nvar); r = b.copy(); z = r / diag; p = z.copy(); rz = r @ z
        norm0 = math.sqrt(b @ b) or 1.
        it = 0
        for it in range(iterations):
            if math.sqrt(r @ r) < tol * norm0 or rz <= 0:
                break                              # e.g. a flat DEM is already the answer
            ap = matvec(p)
            alpha = rz / (p @ ap)
            x += alpha * p; r -= alpha * ap
            if math.sqrt(r @ r) < tol * norm0:
                break
            z = r / diag; rz2 = r @ z
            p = z + (rz2 / rz) * p; rz = rz2
        return x, it + 1, math.sqrt(r @ r) / norm0

    # solve for the offset from the DEM: the start residual is small and well scaled. A spring
    # gives part of the clearance only: its target is raised by the shortfall and solved again.
    base = mw * target
    aim = clear.copy()
    ceiling = aim + CLEAR_EXTRA
    steep = 0
    for grade_pass in range(GRADE_PASSES + 1):
        for _ in range(CLEAR_PASSES + 1):
            b = base - matvec(dem)
            for c, v in zip(xc, xv):
                b += np.bincount(v, CLEAR_WEIGHT * active * aim * c, nvar)
            x, its, residual = cg(b)
            # A lower bridge can itself have risen in this solve. Its DEM target is
            # no longer the road below us: measure the solved surfaces every pass.
            clear = clearance(dem + x)
            short = clear - gap(dem + x)
            if not len(xa) or short.max() < CLEAR_TOL:
                break
            # a low crossing joins the set; an active one aims higher by what it still lacks
            # The aim stops CLEAR_EXTRA m over the first one: a crossing whose lower road is tied to
            # the deck (an interchange's ramps) would otherwise chase it up a hill.
            aim = np.minimum(np.where(active > 0, aim + np.maximum(short, 0), clear), ceiling)
            active = np.where(short > CLEAR_TOL, 1., active)
        h = dem + x
        grade = np.abs(h[eb] - h[ea]) / el
        over = grade > edge_max + .002
        steep = int(over.sum())
        if not steep or grade_pass == GRADE_PASSES:
            break
        # the grade weight goes with the square of the excess; neighbours take the rest next pass
        # capped, so the clearance springs (CLEAR_WEIGHT) still win where both cannot hold
        stiff[over] = np.minimum(stiff[over] * np.clip(3 * (grade[over] / edge_max[over]) ** 2, 2, 30), STIFF_MAX)
        ptr, col, data, diag0 = assemble()
    if emit:
        low = int((short > .5).sum()) if len(xa) else 0
        worst = f', worst {short.max():.2f} m' if low else ''
        emit(f'profile: {nvar} stations, {len(va)} close station-edge pairs, {len(xa)} bridge crossings '
             f'({low} short of clearance{worst}), {steep} edges over their grade after {grade_pass} grade passes, '
             f'{its} CG iterations, residual {residual:.1e}')
    h = dem + x
    hs = h[ids]
    bounds = np.r_[run, len(s)]
    profiles = [(s[bounds[k]:bounds[k + 1]], hs[bounds[k]:bounds[k + 1]]) for k in range(len(segments))]
    return profiles, {n: float(h[k]) for n, k in node_index.items()}


class Mosaic:
    """Terrain.sample for millions of points: the PNG tiles round them stitched, BLOCK x BLOCK
    tiles at a time. One grid over all the points' bounding box was 4.7 GiB for Estonia at z13
    (the sea and the empty bogs included), and the solve samples the DEM once."""
    BLOCK = 8

    def __init__(self, terrain, xy=None):
        self.zoom = getattr(terrain, 'zoom', 12)
        self.terrain = terrain

    def _grid(self, tx0, ty0, tx1, ty1, needed):
        """The pixels of tiles tx0..tx1, ty0..ty1, of those in `needed` only (NaN where a tile is
        missing or not asked for). The edge tiles of a downloaded DEM may be missing on disk, and
        z13 upsamples from z12 neighbours: reading just what the points reach keeps to the tiles
        a grid over them read."""
        # a z13 grid has four times the pixels: single precision (millimetres at 1000 m)
        grid = np.full(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), np.nan,
                       dtype=np.float32 if self.zoom > 12 else float)
        for a, b in sorted(needed):
            if tx0 <= a <= tx1 and ty0 <= b <= ty1:
                if self.terrain.has(a, b):
                    ix = np.arange(a * 256, a * 256 + 256); iy = np.arange(b * 256, b * 256 + 256)
                    gx, gy = np.meshgrid(ix, iy)
                    grid[(b - ty0) * 256:(b - ty0 + 1) * 256,
                         (a - tx0) * 256:(a - tx0 + 1) * 256] = self.terrain.pixels(gx.ravel(), gy.ravel()).reshape(256, 256)
        valid = np.isfinite(grid)
        if valid.any():
            try:
                from scipy.ndimage import median_filter
                fill_val = float(np.nanmedian(grid[valid]))
                filled = np.where(valid, grid, fill_val)
                med = median_filter(filled, size=5)
                despiked = np.where(np.abs(filled - med) > 4.0, med, filled)
                grid = np.where(valid, despiked, np.nan)
            except Exception:
                pass
        return grid

    @staticmethod
    def _px(lon, lat, zoom=12):
        scale = 256 * 2 ** zoom
        return (np.asarray(lon) + 180) / 360 * scale, (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * scale

    def sample(self, xy, smooth=True, missing=False):
        """Same filter and result as Terrain.sample (smooth 5-tap bilinear)."""
        from fast_sources import LIFT
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        lon, lat = self.terrain.frame.geographic(xy[:, 0], xy[:, 1])
        x, y = self._px(lon, lat, self.zoom)
        ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
        u, v = x - ix, y - iy
        offsets = [(0, 0, 1.)] if not smooth else [(0, 0, .5), (-1, 0, .125), (1, 0, .125), (0, -1, .125), (0, 1, .125)]
        z = np.zeros(len(x))
        # the points of one block of tiles at a time, in the order of their block key
        bx, by = ix // 256 // self.BLOCK, iy // 256 // self.BLOCK
        key = bx * 65536 + by
        order = np.argsort(key, kind='stable')
        starts = np.flatnonzero(np.r_[True, key[order][1:] != key[order][:-1]])
        for first, last in zip(starts, np.r_[starts[1:], len(order)]):
            at = order[first:last]
            # a tile of margin each side: the 5-tap filter and the bilinear corner reach one pixel out
            x0, y0 = int(bx[at[0]]) * self.BLOCK - 1, int(by[at[0]]) * self.BLOCK - 1
            # the pixels the filter reads: from one before (ix, iy) to two after, in 256 px tiles
            reach = np.unique(np.concatenate([((ix[at] + dx) // 256) * 65536 + (iy[at] + dy) // 256
                                              for dx in (-1, 2) for dy in (-1, 2)]))
            g = self._grid(x0, y0, x0 + self.BLOCK + 1, y0 + self.BLOCK + 1,
                           [divmod(int(k), 65536) for k in reach])
            gx, gy = ix[at] - x0 * 256, iy[at] - y0 * 256
            for dx, dy, w in offsets:
                a, b = gx + dx, gy + dy
                z[at] += w * ((g[b, a] * (1 - u[at]) + g[b, a + 1] * u[at]) * (1 - v[at])
                              + (g[b + 1, a] * (1 - u[at]) + g[b + 1, a + 1] * u[at]) * v[at])
        if not missing and not np.isfinite(z).all():
            raise FileNotFoundError('no_dem: profile stations outside the downloaded DEM')
        return z + LIFT
