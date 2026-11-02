"""
BeamNG Forest Generator (forest/managedData.json).
Populates realistic trees and vegetation within forest polygons,
strictly avoiding road exclusion zones.
"""

import json
import math
import pathlib
import random
from typing import Any, Dict, List, Tuple
from shapely.geometry import Point, Polygon

from core.projection import lat_lon_to_meters
from processing.exclusion import SpatialExclusionEngine
from processing.heightmap import HeightmapProcessor

TREE_TYPES = [
    "birch_tree_large",
    "birch_tree_medium",
    "pine_tree_large",
    "pine_tree_medium",
    "beech_tree_large",
    "bush_green",
]


class ForestExporter:
    """Scatters trees within forest zones and exports managedData.json."""

    def __init__(
        self,
        heightmap: HeightmapProcessor,
        exclusion: SpatialExclusionEngine,
        origin_lat: float,
        origin_lon: float,
        tree_density: float = 0.008,  # Trees per square meter in forest zones
    ):
        self.heightmap = heightmap
        self.exclusion = exclusion
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.density = tree_density

    def generate_forest_items(
        self,
        forest_polygons: List[List[Tuple[float, float]]],
        max_trees: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Scatters valid tree items across all forest polygons."""
        items: List[Dict[str, Any]] = []

        for f_poly_nodes in forest_polygons:
            if len(f_poly_nodes) < 3 or len(items) >= max_trees:
                continue

            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in f_poly_nodes
            ]

            try:
                poly = Polygon(metric_pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)

                area = poly.area
                num_trees = int(area * self.density)
                num_trees = min(num_trees, 300)

                minx, miny, maxx, maxy = poly.bounds

                for _ in range(num_trees * 2):  # Try with some oversampling for rejected points
                    rx = random.uniform(minx, maxx)
                    ry = random.uniform(miny, maxy)

                    if not poly.contains(Point(rx, ry)):
                        continue

                    # STRICT exclusion check: Must not touch any road
                    if not self.exclusion.is_point_clear(rx, ry):
                        continue

                    z = self.heightmap.get_elevation_at_meters(rx, ry)
                    scale = round(random.uniform(0.8, 1.25), 2)
                    tree_type = random.choice(TREE_TYPES)

                    # Random yaw rotation around Z axis
                    yaw = random.uniform(0, 2 * math.pi)
                    qz = math.sin(yaw / 2.0)
                    qw = math.cos(yaw / 2.0)

                    items.append({
                        "pos": [round(rx, 2), round(ry, 2), round(z, 2)],
                        "rotation": [0.0, 0.0, round(qz, 4), round(qw, 4)],
                        "scale": scale,
                        "type": tree_type,
                    })

                    if len(items) >= max_trees:
                        break
            except Exception:
                continue

        print(f"[ForestExporter] Placed {len(items)} trees safely outside road zones.")
        return items

    def export_managed_data(
        self,
        output_file: pathlib.Path,
        forest_polygons: List[List[Tuple[float, float]]],
    ):
        """Writes forest/managedData.json."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        items = self.generate_forest_items(forest_polygons)

        forest_json = [
            {
                "type": "ForestItemData",
                "internalName": "forestItemData_0",
            },
            {
                "type": "Forest",
                "name": "theForest",
                "items": items,
            },
        ]

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(forest_json, f, indent=2)
        print(f"[ForestExporter] Saved forest data to {output_file}")
