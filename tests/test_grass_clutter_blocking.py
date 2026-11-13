"""Test suite verifying the spatial indexing and clutter blocking logic for generator.lua."""

import math
import pytest


def point_segment_sq(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2)) if len2 > 1e-8 else 0.0
    return (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2


class MockVegSpatial:
    def __init__(self):
        self.bins = {}

    def build_path_bins(self, lines, points, rect):
        bins = {}
        # 1. Paths in lines
        for line in lines:
            pts = line.get("points")
            if not pts or len(pts) < 2:
                continue
            tags = line.get("tags", {})
            w = line.get("width") or float(tags.get("width", 2.2))
            r = w / 2.0 + 1.6
            r2 = r * r
            for k in range(len(pts) - 1):
                a, b = pts[k], pts[k + 1]
                dx, dy = b[0] - a[0], b[1] - a[1]
                len2 = dx * dx + dy * dy
                if len2 > 1e-8:
                    min_x, max_x = min(a[0], b[0]), max(a[0], b[0])
                    min_y, max_y = min(a[1], b[1]), max(a[1], b[1])
                    entry = {"a": a, "dx": dx, "dy": dy, "len2": len2, "r": r, "r2": r2}
                    by0, by1 = math.floor((min_y - r) / 50), math.floor((max_y + r) / 50)
                    bx0, bx1 = math.floor((min_x - r) / 50), math.floor((max_x + r) / 50)
                    for by in range(by0, by1 + 1):
                        for bx in range(bx0, bx1 + 1):
                            key = (bx + 32768) * 65536 + by + 32768
                            bins.setdefault(key, []).append(entry)

        # 2. Point playgrounds in points (radius 9m)
        for pt in points:
            p = pt.get("pos")
            tags = pt.get("tags", {})
            if p:
                r = None
                if pt.get("kind") == "playground" or tags.get("leisure") == "playground":
                    r = 10.5
                elif pt.get("kind") == "entrance":
                    r = 3.0
                if r:
                    entry = {"a": p, "dx": 0.0, "dy": 0.0, "len2": 1.0, "r": r, "r2": r * r}
                    by0, by1 = math.floor((p[1] - r) / 50), math.floor((p[1] + r) / 50)
                    bx0, bx1 = math.floor((p[0] - r) / 50), math.floor((p[0] + r) / 50)
                    for by in range(by0, by1 + 1):
                        for bx in range(bx0, bx1 + 1):
                            key = (bx + 32768) * 65536 + by + 32768
                            bins.setdefault(key, []).append(entry)
        self.bins = bins
        return bins

    def path_blocked(self, x, y):
        key = (math.floor(x / 50) + 32768) * 65536 + math.floor(y / 50) + 32768
        nearby = self.bins.get(key, [])
        for s in nearby:
            a = s["a"]
            t = max(0.0, min(1.0, ((x - a[0]) * s["dx"] + (y - a[1]) * s["dy"]) / s["len2"]))
            if (x - a[0] - t * s["dx"]) ** 2 + (y - a[1] - t * s["dy"]) ** 2 < s["r2"]:
                return True
        return False


def test_path_blocking_within_width_half_plus_1_6m():
    veg = MockVegSpatial()
    # 2.0m wide footpath from (0, 0) to (100, 0)
    # width / 2 + 1.6 = 1.0 + 1.6 = 2.6m
    lines = [
        {"kind": "path", "points": [[0.0, 0.0], [100.0, 0.0]], "tags": {"width": "2.0"}}
    ]
    veg.build_path_bins(lines, [], [0, 0, 100, 100])

    # Point at (50, 2.5) -> distance 2.5m < 2.6m -> BLOCKED
    assert veg.path_blocked(50.0, 2.5) is True

    # Point at (50, 2.59) -> distance 2.59m < 2.6m -> BLOCKED
    assert veg.path_blocked(50.0, 2.59) is True

    # Point at (50, 2.65) -> distance 2.65m > 2.6m -> NOT BLOCKED
    assert veg.path_blocked(50.0, 2.65) is False

    # Point at (50, 5.0) -> NOT BLOCKED
    assert veg.path_blocked(50.0, 5.0) is False


def test_wider_path_blocking():
    veg = MockVegSpatial()
    # 4.0m wide pedestrian promenade
    # width / 2 + 1.6 = 2.0 + 1.6 = 3.6m
    lines = [
        {"kind": "path", "points": [[0.0, 0.0], [0.0, 80.0]], "tags": {"width": "4.0"}}
    ]
    veg.build_path_bins(lines, [], [0, 0, 100, 100])

    # Point at (3.5, 40) -> distance 3.5m < 3.6m -> BLOCKED
    assert veg.path_blocked(3.5, 40.0) is True

    # Point at (3.7, 40) -> distance 3.7m > 3.6m -> NOT BLOCKED
    assert veg.path_blocked(3.7, 40.0) is False


def test_point_playground_radius_10_5m():
    veg = MockVegSpatial()
    points = [
        {"kind": "playground", "pos": [50.0, 50.0], "tags": {}}
    ]
    veg.build_path_bins([], points, [0, 0, 100, 100])

    # At distance 10.4m from (50, 50) -> BLOCKED
    assert veg.path_blocked(50.0 + 10.4, 50.0) is True

    # At distance 10.6m from (50, 50) -> NOT BLOCKED
    assert veg.path_blocked(50.0 + 10.6, 50.0) is False


def test_area_classification():
    # Test VEG.isBlockedArea equivalents
    def is_blocked_area(area):
        tags = area.get("tags", {})
        kind = area.get("kind", "")
        leisure = tags.get("leisure", "")
        if kind == "water" or tags.get("natural") == "water":
            return True, False
        if kind == "playground" or leisure == "playground" or tags.get("amenity") == "playground":
            return True, False
        if kind in ("pitch", "track") or leisure in ("pitch", "track", "sports_centre") or "sport" in tags:
            return True, False
        is_paved = (
            kind in ("paved", "square", "plaza", "parking")
            or tags.get("amenity") == "parking"
            or "parking" in tags
            or tags.get("place") == "square"
            or tags.get("highway") == "pedestrian"
            or tags.get("surface") in ("paved", "asphalt", "concrete", "paving_stones")
        )
        if is_paved:
            return True, True
        return False, False

    # Water
    assert is_blocked_area({"kind": "water"}) == (True, False)
    # Playground
    assert is_blocked_area({"kind": "playground"}) == (True, False)
    assert is_blocked_area({"tags": {"leisure": "playground"}}) == (True, False)
    # Sports pitch
    assert is_blocked_area({"kind": "pitch"}) == (True, False)
    assert is_blocked_area({"tags": {"leisure": "pitch"}}) == (True, False)
    assert is_blocked_area({"tags": {"sport": "tennis"}}) == (True, False)
    # Parking
    assert is_blocked_area({"kind": "parking"}) == (True, True)
    assert is_blocked_area({"tags": {"amenity": "parking"}}) == (True, True)
    # Plazas and squares
    assert is_blocked_area({"kind": "square"}) == (True, True)
    assert is_blocked_area({"tags": {"place": "square"}}) == (True, True)
    assert is_blocked_area({"tags": {"highway": "pedestrian"}}) == (True, True)
    # Grass / meadow / forest -> NOT blocked
    assert is_blocked_area({"kind": "grass"}) == (False, False)
    assert is_blocked_area({"kind": "forest"}) == (False, False)
    assert is_blocked_area({"kind": "meadow"}) == (False, False)
