"""
Spatial Exclusion and Road Buffering.
Guarantees that NO buildings, trees, or props can spawn on or directly adjacent to roads,
and filters out artifacts such as vehicles on satellite images mistakenly identified as structures.
"""

from typing import List, Tuple, Union
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from core.projection import lat_lon_to_meters, meters_to_lat_lon
from fetchers.osm import BuildingPolygon, RoadSegment


class SpatialExclusionEngine:
    """Manages exclusion zones around roads and validates spatial objects."""

    def __init__(
        self,
        roads: List[RoadSegment],
        origin_lat: float,
        origin_lon: float,
        clearance_meters: float = 0.8,
        min_building_area_sqm: float = 12.0,
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
        self, raw_buildings: List[Union[BuildingPolygon, List[Tuple[float, float]]]]
    ) -> List[BuildingPolygon]:
        """
        Validates buildings against road corridors and size thresholds:
        1. Filters out objects < min_building_area (eliminating cars/trucks detected as buildings)
        2. Instead of discarding buildings that touch the road, clips them via poly.difference(self.road_corridor).
           Any remaining part with area >= min_building_area is preserved.
        """
        clean_buildings: List[BuildingPolygon] = []
        rejected_on_road = 0
        rejected_too_small = 0
        clipped_count = 0

        for b_nodes in raw_buildings:
            if len(b_nodes) < 3:
                continue

            tags = getattr(b_nodes, "tags", {})

            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in b_nodes
            ]

            try:
                poly = Polygon(metric_pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)

                # Filter 1: Area threshold (eliminates cars, vans, artifacts)
                if poly.is_empty or poly.area < self.min_building_area:
                    rejected_too_small += 1
                    continue

                # Filter 2: Road corridor collision
                if self.road_corridor.is_empty or not self.road_corridor.intersects(poly):
                    clean_buildings.append(
                        b_nodes if isinstance(b_nodes, BuildingPolygon) else BuildingPolygon(b_nodes, tags=tags)
                    )
                    continue

                # Building intersects road corridor: clip it instead of dropping it entirely
                diff = poly.difference(self.road_corridor)
                if diff.is_empty:
                    rejected_on_road += 1
                    continue

                parts: List[Polygon] = []
                if isinstance(diff, Polygon):
                    parts = [diff]
                elif isinstance(diff, MultiPolygon) or hasattr(diff, "geoms"):
                    parts = [g for g in diff.geoms if isinstance(g, Polygon)]

                saved_any = False
                for part in parts:
                    if part.is_empty or not part.is_valid:
                        part = part.buffer(0)
                    if part.is_empty or part.area < self.min_building_area:
                        rejected_too_small += 1
                        continue

                    coords = list(part.exterior.coords)
                    # Remove closing duplicate vertex if present
                    if len(coords) >= 4 and coords[0] == coords[-1]:
                        coords = coords[:-1]
                    if len(coords) < 3:
                        continue

                    lat_lon_pts = [
                        meters_to_lat_lon(x, y, self.origin_lat, self.origin_lon)
                        for x, y in coords
                    ]
                    clean_buildings.append(BuildingPolygon(lat_lon_pts, tags=tags))
                    clipped_count += 1
                    saved_any = True

                if not saved_any:
                    rejected_on_road += 1

            except Exception:
                continue

        print(
            f"[Exclusion] Validated buildings: {len(clean_buildings)} kept (clipped {clipped_count}) | "
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
