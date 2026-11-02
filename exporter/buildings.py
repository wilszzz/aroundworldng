"""
3D Building Exporter for BeamNG.drive.
Generates TSStatic building instances matching OpenStreetMap building footprints.
"""

import random
from typing import Any, Dict, List, Tuple
import uuid
from shapely.geometry import Polygon

from core.projection import lat_lon_to_meters
from processing.heightmap import HeightmapProcessor


class BuildingExporter:
    """Translates OSM building polygons into BeamNG TSStatic objects."""

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
        """Converts building footprint polygons to 3D TSStatic scene objects."""
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

                minx, miny, maxx, maxy = poly.bounds
                w = max(maxx - minx, 5.0)
                d = max(maxy - miny, 5.0)
                cx = (minx + maxx) / 2.0
                cy = (miny + maxy) / 2.0

                z = self.heightmap.get_elevation_at_meters(cx, cy)
                
                # Height estimation: area-based or realistic variation
                if poly.area > 500:
                    h = random.uniform(14.0, 28.0)  # Large apartment / commercial building
                else:
                    h = random.uniform(6.0, 12.0)   # 2-3 story house

                # Scale of our 10x10x10 cube
                sx = w / 10.0
                sy = d / 10.0
                sz = h / 10.0

                bld_obj = {
                    "name": f"building_{idx}",
                    "class": "TSStatic",
                    "persistentId": str(uuid.uuid4()),
                    "__parent": "MissionGroup",
                    "position": [round(cx, 2), round(cy, 2), round(z, 2)],
                    "scale": [round(sx, 3), round(sy, 3), round(sz, 3)],
                    "shapeName": f"/levels/{self.level_name}/art/shapes/buildings/building_box.dae",
                    "collisionType": "Visible Mesh Final",
                }
                items.append(bld_obj)
            except Exception:
                continue

        print(f"[BuildingExporter] Generated {len(items)} 3D solid buildings.")
        return items
