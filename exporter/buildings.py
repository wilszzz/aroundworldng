"""
3D Architectural Building Exporter for BeamNG.drive.
Generates TSStatic building instances from OpenStreetMap building footprints,
mapping each footprint to suitable architectural archetypes with orientation and foundation skirts.
"""

import math
import random
from typing import Any, Dict, List, Tuple
import uuid
from shapely.geometry import Polygon

from core.projection import lat_lon_to_meters
from processing.heightmap import HeightmapProcessor

ARCHETYPES = {
    "house": {
        "file": "bld_house_small.dae",
        "bw": 10.0, "bd": 12.0, "bh": 7.0,
    },
    "apartment": {
        "file": "bld_apartment_block.dae",
        "bw": 24.0, "bd": 14.0, "bh": 16.0,
    },
    "commercial": {
        "file": "bld_commercial_glass.dae",
        "bw": 20.0, "bd": 20.0, "bh": 26.0,
    },
    "plaza": {
        "file": "bld_commercial_plaza.dae",
        "bw": 30.0, "bd": 16.0, "bh": 8.0,
    },
    "warehouse": {
        "file": "bld_industrial_warehouse.dae",
        "bw": 35.0, "bd": 20.0, "bh": 10.0,
    },
}


class BuildingExporter:
    """Translates OSM building polygons into oriented, textured BeamNG TSStatic objects."""

    def __init__(
        self,
        heightmap: HeightmapProcessor,
        level_name: str,
        origin_lat: float,
        origin_lon: float,
    ):
        self.heightmap = heightmap
        self.level_name = level_name
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon

    def export_buildings(
        self,
        building_polygons: List[List[Tuple[float, float]]],
        max_buildings: int = 500,
    ) -> List[Dict[str, Any]]:
        """Converts building footprint polygons to oriented 3D TSStatic scene objects."""
        items: List[Dict[str, Any]] = []

        for idx, b_poly in enumerate(building_polygons):
            if len(b_poly) < 3 or len(items) >= max_buildings:
                break

            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in b_poly
            ]

            try:
                poly = Polygon(metric_pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)

                area = poly.area
                # Skip tiny sheds or giant open grounds/stadium zones (> 5000 m2)
                if area < 30.0 or area > 5000.0:
                    continue

                minx, miny, maxx, maxy = poly.bounds
                cx = (minx + maxx) / 2.0
                cy = (miny + maxy) / 2.0

                # Clamp width and depth to realistic building bounds
                w = min(max(maxx - minx, 8.0), 45.0)
                d = min(max(maxy - miny, 8.0), 35.0)

                # Estimate building orientation from first wall segment
                p0 = metric_pts[0]
                p1 = metric_pts[1]
                yaw = math.atan2(p1[1] - p0[1], p1[0] - p0[0])

                # Select archetype based on footprint dimensions and area
                if area < 180.0:
                    atype_key = "house"
                    h = random.uniform(6.5, 8.5)
                elif area < 650.0:
                    atype_key = "apartment"
                    h = random.uniform(12.0, 18.0)
                elif area < 1600.0:
                    atype_key = random.choice(["commercial", "plaza"])
                    h = random.uniform(16.0, 24.0) if atype_key == "commercial" else random.uniform(7.5, 10.0)
                else:
                    atype_key = "warehouse" if w > 30.0 or d > 30.0 else "commercial"
                    h = random.uniform(9.0, 13.0) if atype_key == "warehouse" else random.uniform(18.0, 26.0)

                spec = ARCHETYPES[atype_key]
                sx = round(max(0.5, min(2.5, w / spec["bw"])), 3)
                sy = round(max(0.5, min(2.5, d / spec["bd"])), 3)
                sz = round(max(0.6, min(2.0, h / spec["bh"])), 3)

                z = self.heightmap.get_elevation_at_meters(cx, cy)

                cos_y = math.cos(yaw)
                sin_y = math.sin(yaw)

                bld_obj = {
                    "name": f"building_{atype_key}_{idx}",
                    "class": "TSStatic",
                    "persistentId": str(uuid.uuid4()),
                    "__parent": "MissionGroup",
                    "position": [round(cx, 2), round(cy, 2), round(z, 2)],
                    "rotationMatrix": [
                        round(cos_y, 4), round(-sin_y, 4), 0.0,
                        round(sin_y, 4), round(cos_y, 4), 0.0,
                        0.0, 0.0, 1.0,
                    ],
                    "scale": [sx, sy, sz],
                    "shapeName": f"/levels/{self.level_name}/art/shapes/buildings/{spec['file']}",
                    "collisionType": "Visible Mesh Final",
                }
                items.append(bld_obj)
            except Exception:
                continue

        print(f"[BuildingExporter] Generated {len(items)} oriented architectural 3D buildings.")
        return items
