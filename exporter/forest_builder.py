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
        "shapeFile": "assets/meshes/foliage/trees_library/oak/tree_oak_large_a.dae",
        "radius": 1.5,
        "annotation": "TREE",
    },
    "tree_oak_small": {
        "shapeFile": "assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae",
        "radius": 1.0,
        "annotation": "TREE",
    },
    "tree_beech_large_b": {
        "shapeFile": "assets/meshes/foliage/trees_library/beech/tree_beech_large_b.dae",
        "radius": 1.4,
        "annotation": "TREE",
    },
    "tree_beech_large_c": {
        "shapeFile": "assets/meshes/foliage/trees_library/beech/tree_beech_large_c.dae",
        "radius": 1.4,
        "annotation": "TREE",
    },
    "tree_aspen_large_a": {
        "shapeFile": "assets/meshes/foliage/trees_library/birch/tree_aspen_large_a.dae",
        "radius": 1.2,
        "annotation": "TREE",
    },
    "tree_aspen_large": {
        "shapeFile": "assets/meshes/foliage/trees_library/birch/tree_aspen_large_a.dae",
        "radius": 1.2,
        "annotation": "TREE",
    },
    "cork_oak_bush_large": {
        "shapeFile": "assets/meshes/foliage/trees_library/cork_oak/cork_oak_bush_large.dae",
        "radius": 1.1,
        "annotation": "BUSH",
    },
    "bush_large": {
        "shapeFile": "assets/meshes/foliage/trees_library/oak/tree_oak_bush_a.dae",
        "radius": 0.8,
        "annotation": "BUSH",
    },
}

# Natural green summer tree pool for streets and procedural greenery
GREEN_STREET_TREES = [
    "tree_oak_large",
    "tree_oak_small",
    "tree_beech_large_b",
    "tree_beech_large_c",
]

# Highway classification filters for street trees
EXCLUDED_STREET_HIGHWAY_TYPES = {
    "motorway",
    "trunk",
    "raceway",
    "track",
    "primary_link",
    "motorway_link",
    "trunk_link",
}

ALLOWED_STREET_HIGHWAY_TYPES = {
    "residential",
    "secondary",
    "tertiary",
    "living_street",
    "unclassified",
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
                        tree_type = random.choice(
                            [
                                "tree_oak_large",
                                "tree_oak_small",
                                "tree_beech_large_b",
                                "tree_beech_large_c",
                                "tree_aspen_large_a",
                            ]
                        )
                        instances[tree_type].append(inst)

                        # 40% chance to spawn an accompanying bush
                        if random.random() < 0.4:
                            bx = rx + random.uniform(-2.5, 2.5)
                            by = ry + random.uniform(-2.5, 2.5)
                            if self.exclusion.is_point_clear(bx, by):
                                bz = self.heightmap.get_elevation_at_meters(bx, by)
                                bush_type = random.choice(["bush_large", "cork_oak_bush_large"])
                                instances[bush_type].append(self._create_tree_instance(bx, by, bz, scale_range=(0.7, 1.1)))
            except Exception:
                continue

        # 2. Spawn Street Trees along Urban & Secondary Roads
        for road in osm_data.roads:
            if road.is_bridge or road.is_tunnel:
                continue
            if road.highway_type in EXCLUDED_STREET_HIGHWAY_TYPES:
                continue  # Never spawn street trees along freeways, tracks, or links
            if road.highway_type not in ALLOWED_STREET_HIGHWAY_TYPES:
                continue  # Spawn street trees only along designated urban streets
            if len(road.nodes) < 2:
                continue

            pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in road.nodes
            ]

            half_w = (road.width / 2.0) + 2.5  # 2.5 meters from road edge onto the sidewalk/verge
            step = 30.0  # Base spacing: tree every 30 meters

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
                    base_dist = (t_idx / (num_street_trees + 1)) * seg_len

                    # Spawn on both sides of the street with organic jitter
                    for side in [-1, 1]:
                        # Organic jitter: step shift +-5m, perpendicular offset shift +-0.8m
                        step_jitter = random.uniform(-5.0, 5.0)
                        actual_dist = max(2.0, min(seg_len - 2.0, base_dist + step_jitter))

                        bx = p1[0] + ux * actual_dist
                        by = p1[1] + uy * actual_dist

                        perp_jitter = random.uniform(-0.8, 0.8)
                        actual_offset = max(road.width / 2.0 + 1.2, half_w + perp_jitter)

                        tx = bx + nx * actual_offset * side
                        ty = by + ny * actual_offset * side

                        # Ensure point is in map bounds
                        if abs(tx) < self.size / 2.0 and abs(ty) < self.size / 2.0:
                            tz = self.heightmap.get_elevation_at_meters(tx, ty)
                            inst = self._create_tree_instance(tx, ty, tz, scale_range=(0.85, 1.15))
                            tree_type = random.choice(GREEN_STREET_TREES)
                            instances[tree_type].append(inst)

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

        # 4. Write modern BeamNG NDJSON v4 files in forest/<item_type>.forest4.json
        forest_dir = level_dir / "forest"
        forest_dir.mkdir(parents=True, exist_ok=True)
        for item_type, inst_list in instances.items():
            if not inst_list:
                continue
            f4_file = forest_dir / f"{item_type}.forest4.json"
            with open(f4_file, "w", encoding="utf-8") as f:
                for inst in inst_list:
                    x, y, z = inst[0], inst[1], inst[2]
                    rot_z, rot_w = inst[5], inst[6]
                    scale = inst[7]
                    cos_y = round(rot_w * rot_w - rot_z * rot_z, 4)
                    sin_y = round(2.0 * rot_z * rot_w, 4)
                    rot_matrix = [
                        cos_y, -sin_y, 0.0,
                        sin_y, cos_y, 0.0,
                        0.0, 0.0, 1.0,
                    ]
                    row = {
                        "pos": [round(x, 3), round(y, 3), round(z, 3)],
                        "rotationMatrix": rot_matrix,
                        "scale": round(scale, 3),
                        "ctxid": 0,
                    }
                    f.write(json.dumps(row) + "\n")

        # 5. Write legacy <level_name>.forest.json for backward compatibility
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

        # 6. Return Forest SimObject item
        forest_obj = {
            "name": "theForest",
            "class": "Forest",
            "persistentId": str(uuid.uuid4()),
            "__parent": "MissionGroup",
            "position": [0.0, 0.0, 0.0],
            "rotationMatrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
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
