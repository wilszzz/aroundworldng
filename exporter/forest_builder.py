"""
Forest and Vegetation Generator for BeamNG.drive.
Populates real 3D trees and bushes based on OSM forest/wood/park polygons and street verges.
Generates <level_name>.forest.json and art/forest/managedItemData.json.
"""

import json
import math
import pathlib
import random
from typing import Any, Dict, List, Tuple
import uuid
from shapely.geometry import Point, Polygon

from core.projection import lat_lon_to_meters
from fetchers.osm import OSMData, RoadSegment
from processing.exclusion import SpatialExclusionEngine
from processing.heightmap import HeightmapProcessor

# Built-in BeamNG tree models available in core assets
DEFAULT_TREE_MODELS = {
    "tree_oak_large": {
        "shapeFile": "/assets/meshes/foliage/trees_library/oak/tree_oak_large_a.dae",
        "radius": 1.5,
        "annotation": "TREE",
    },
    "tree_oak_small": {
        "shapeFile": "/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae",
        "radius": 1.0,
        "annotation": "TREE",
    },
    "tree_aspen_large": {
        "shapeFile": "/assets/meshes/foliage/trees_library/birch/tree_aspen_large_a.dae",
        "radius": 1.2,
        "annotation": "TREE",
    },
    "tree_beech_large": {
        "shapeFile": "/assets/meshes/foliage/trees_library/beech/tree_beech_large_b.dae",
        "radius": 1.4,
        "annotation": "TREE",
    },
    "bush_large": {
        "shapeFile": "/assets/meshes/foliage/trees_library/oak/tree_oak_bush_a.dae",
        "radius": 0.8,
        "annotation": "BUSH",
    },
}


class ForestBuilder:
    """Generates procedural 3D forest instances and managed item definitions."""

    def __init__(
        self,
        level_name: str,
        origin_lat: float,
        origin_lon: float,
        heightmap: HeightmapProcessor,
        exclusion: SpatialExclusionEngine,
        size_meters: float,
    ):
        self.level_name = level_name
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.heightmap = heightmap
        self.exclusion = exclusion
        self.size = size_meters

    def generate_forest(
        self,
        osm_data: OSMData,
        level_dir: pathlib.Path,
        density_sqm_per_tree: float = 65.0,
    ) -> Dict[str, Any]:
        """
        Populates 3D trees and bushes from OSM forest areas and along street corridors.
        Writes art/forest/managedItemData.json and <level_name>.forest.json.
        Returns the Forest SimObject item for items.level.json.
        """
        instances: Dict[str, List[List[float]]] = {k: [] for k in DEFAULT_TREE_MODELS}

        # 1. Spawn trees within OSM Forest / Wood / Park polygons
        for f_poly_nodes in osm_data.forests:
            if len(f_poly_nodes) < 3:
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
                if area < 50.0:
                    continue

                minx, miny, maxx, maxy = poly.bounds
                num_trees = max(int(area / density_sqm_per_tree), 2)

                for _ in range(num_trees):
                    rx = random.uniform(minx, maxx)
                    ry = random.uniform(miny, maxy)
                    pt = Point(rx, ry)

                    if poly.contains(pt) and self.exclusion.is_point_clear(rx, ry):
                        rz = self.heightmap.get_elevation_at_meters(rx, ry)
                        inst = self._create_tree_instance(rx, ry, rz)
                        tree_type = random.choice(["tree_oak_large", "tree_aspen_large", "tree_beech_large", "tree_oak_small"])
                        instances[tree_type].append(inst)

                        # 40% chance to spawn an accompanying bush
                        if random.random() < 0.4:
                            bx = rx + random.uniform(-2.5, 2.5)
                            by = ry + random.uniform(-2.5, 2.5)
                            if self.exclusion.is_point_clear(bx, by):
                                bz = self.heightmap.get_elevation_at_meters(bx, by)
                                instances["bush_large"].append(self._create_tree_instance(bx, by, bz, scale_range=(0.7, 1.1)))
            except Exception:
                continue

        # 2. Spawn Street Trees along Urban & Secondary Roads
        for road in osm_data.roads:
            if road.is_bridge or road.is_tunnel:
                continue
            if road.highway_type in {"motorway", "trunk"}:
                continue  # High-speed freeways don't have street trees right on the curb
            if len(road.nodes) < 2:
                continue

            pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in road.nodes
            ]

            half_w = (road.width / 2.0) + 2.5  # 2.5 meters from road edge onto the sidewalk/verge
            step = 30.0  # Tree every 30 meters

            for i in range(len(pts) - 1):
                p1, p2 = pts[i], pts[i + 1]
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 10.0:
                    continue

                ux, uy = dx / seg_len, dy / seg_len
                # Perpendicular unit vectors
                nx, ny = -uy, ux

                num_street_trees = max(int(seg_len / step), 1)
                for t_idx in range(1, num_street_trees + 1):
                    dist = (t_idx / (num_street_trees + 1)) * seg_len
                    bx = p1[0] + ux * dist
                    by = p1[1] + uy * dist

                    # Spawn on both sides of the street
                    for side in [-1, 1]:
                        tx = bx + nx * half_w * side
                        ty = by + ny * half_w * side

                        # Ensure point is in map bounds and clear of building footprints
                        if abs(tx) < self.size / 2.0 and abs(ty) < self.size / 2.0:
                            tz = self.heightmap.get_elevation_at_meters(tx, ty)
                            inst = self._create_tree_instance(tx, ty, tz, scale_range=(0.85, 1.15))
                            instances["tree_aspen_large"].append(inst)

        total_instances = sum(len(v) for v in instances.values())
        print(f"[ForestBuilder] Populated {total_instances} 3D trees and foliage instances.")

        # 3. Write art/forest/managedItemData.json
        art_forest_dir = level_dir / "art" / "forest"
        art_forest_dir.mkdir(parents=True, exist_ok=True)
        managed_items: Dict[str, Any] = {}

        for k, v in DEFAULT_TREE_MODELS.items():
            managed_items[k] = {
                "name": k,
                "internalName": k,
                "class": "TSForestItemData",
                "persistentId": str(uuid.uuid4()),
                "annotation": v["annotation"],
                "radius": v["radius"],
                "shapeFile": v["shapeFile"],
                "collidable": True,
            }

        with open(art_forest_dir / "managedItemData.json", "w", encoding="utf-8") as f:
            json.dump(managed_items, f, indent=2)

        # 4. Write <level_name>.forest.json
        forest_file = level_dir / f"{self.level_name}.forest.json"
        forest_data = {
            "header": {
                "format": "JSON Forest Data v2",
                "format description": "posX, posY, posZ, rotX, rotY, rotZ, rotW, scale",
                "version": 2,
            },
            "instances": instances,
        }

        with open(forest_file, "w", encoding="utf-8") as f:
            json.dump(forest_data, f, indent=2)

        # 5. Return Forest SimObject item
        forest_obj = {
            "name": "theForest",
            "class": "Forest",
            "persistentId": str(uuid.uuid4()),
            "__parent": "MissionGroup",
            "dataFile": f"levels/{self.level_name}/{self.level_name}.forest.json",
        }
        return forest_obj

    def _create_tree_instance(
        self, x: float, y: float, z: float, scale_range: Tuple[float, float] = (0.8, 1.3)
    ) -> List[float]:
        """Creates a single [x, y, z, rotX, rotY, rotZ, rotW, scale] array entry."""
        yaw = random.uniform(0, 2 * math.pi)
        rot_z = math.sin(yaw / 2.0)
        rot_w = math.cos(yaw / 2.0)
        scale = round(random.uniform(*scale_range), 3)

        return [
            round(x, 2),
            round(y, 2),
            round(z, 2),
            0.0,
            0.0,
            round(rot_z, 4),
            round(rot_w, 4),
            scale,
        ]
