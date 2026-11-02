"""
Spatial Exclusion and Road Buffering.
Guarantees that NO buildings, trees, or props can spawn on or directly adjacent to roads,
and filters out artifacts such as vehicles on satellite images mistakenly identified as structures.
"""

from typing import List, Tuple
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment


class SpatialExclusionEngine:
    """Manages exclusion zones around roads and validates spatial objects."""

    def __init__(
        self,
        roads: List[RoadSegment],
        origin_lat: float,
        origin_lon: float,
        clearance_meters: float = 3.5,
        min_building_area_sqm: float = 35.0,
    ):
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.clearance = clearance_meters
        self.min_building_area = min_building_area_sqm

        # Build unified road corridor polygon
        road_polys = []
        for r in roads:
            if len(r.nodes) < 2:
                continue
            metric_pts = [
                lat_lon_to_meters(lat, lon, origin_lat, origin_lon)
                for lat, lon in r.nodes
            ]
            line = LineString(metric_pts)
            half_width = (r.width / 2.0) + self.clearance
            road_polys.append(line.buffer(half_width, cap_style="round", join_style="round"))

        if road_polys:
            self.road_corridor = unary_union(road_polys)
        else:
            self.road_corridor = Polygon()

    def is_point_clear(self, x_meters: float, y_meters: float) -> bool:
        """Returns True if the point is safely outside the road corridor."""
        pt = Point(x_meters, y_meters)
        return not self.road_corridor.contains(pt)

    def filter_buildings(
        self, raw_buildings: List[List[Tuple[float, float]]]
    ) -> List[List[Tuple[float, float]]]:
        """
        Validates buildings against road corridors and size thresholds:
        1. Filters out objects < min_building_area (eliminating cars/trucks detected as buildings)
        2. Filters out any building that intersects or overlaps with the road corridor
        """
        clean_buildings: List[List[Tuple[float, float]]] = []
        rejected_on_road = 0
        rejected_too_small = 0

        for b_nodes in raw_buildings:
            if len(b_nodes) < 3:
                continue

            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in b_nodes
            ]

            try:
                poly = Polygon(metric_pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)

                # Filter 1: Area threshold (eliminates cars, vans, artifacts)
                if poly.area < self.min_building_area:
                    rejected_too_small += 1
                    continue

                # Filter 2: Road corridor collision
                if self.road_corridor.intersects(poly):
                    rejected_on_road += 1
                    continue

                clean_buildings.append(b_nodes)
            except Exception:
                continue

        print(
            f"[Exclusion] Validated buildings: {len(clean_buildings)} kept | "
            f"Filtered: {rejected_on_road} on road corridor, {rejected_too_small} too small (<{self.min_building_area} sqm)."
        )
        return clean_buildings

    def filter_tree_positions(
        self, candidate_positions: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """Filters a list of (x, y) tree coordinates to ensure none stand on roads."""
        return [
            (x, y)
            for x, y in candidate_positions
            if not self.road_corridor.contains(Point(x, y))
        ]
