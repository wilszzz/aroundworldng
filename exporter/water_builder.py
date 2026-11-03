"""
Water Bodies and Ocean Generator for BeamNG.drive.
Generates physical WaterBlock instances for lakes/ponds and WaterPlane for sea/ocean.
"""

from typing import Any, Dict, List, Optional, Tuple
import uuid
from shapely.geometry import Polygon, box

from core.projection import lat_lon_to_meters
from processing.heightmap import HeightmapProcessor, TerrainSpecs
from processing.exclusion import SpatialExclusionEngine


class WaterBuilder:
    """Creates physical BeamNG water objects (WaterBlock, WaterPlane) with fluid physics."""

    def __init__(
        self,
        heightmap: HeightmapProcessor,
        origin_lat: float,
        origin_lon: float,
        specs: TerrainSpecs,
        exclusion: Optional[SpatialExclusionEngine] = None,
    ):
        self.heightmap = heightmap
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.specs = specs
        self.exclusion = exclusion

    def generate_water_items(
        self,
        water_polygons: List[List[Tuple[float, float]]],
        has_coastline: bool = False,
    ) -> List[Dict[str, Any]]:
        """Generates list of WaterBlock and WaterPlane SimObjects."""
        items: List[Dict[str, Any]] = []

        # 1. Process OSM Inland Water Bodies (Ponds, Lakes, Reservoirs)
        for idx, w_poly in enumerate(water_polygons):
            if len(w_poly) < 3:
                continue

            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in w_poly
            ]

            try:
                poly = Polygon(metric_pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)

                # Filter out road corridor collisions (e.g. roadside ditches/mapping artifacts on asphalt)
                if self.exclusion and hasattr(self.exclusion, "road_corridor") and not self.exclusion.road_corridor.is_empty:
                    if poly.intersects(self.exclusion.road_corridor):
                        overlap = poly.intersection(self.exclusion.road_corridor)
                        if overlap.area > 0.3 * poly.area:
                            continue

                minx, miny, maxx, maxy = poly.bounds
                w = max(maxx - minx, 1.0)
                d = max(maxy - miny, 1.0)
                cx = (minx + maxx) / 2.0
                cy = (miny + maxy) / 2.0

                # Sample shoreline elevations along actual polygon vertices
                bank_elevs = [
                    self.heightmap.get_elevation_at_meters(x, y)
                    for x, y in metric_pts
                ]
                min_bank_z = min(bank_elevs) if bank_elevs else self.heightmap.get_elevation_at_meters(cx, cy)
                center_z = self.heightmap.get_elevation_at_meters(cx, cy)

                # Water surface MUST be safely below surrounding banks so it never spills onto land
                water_z = min(min_bank_z, center_z) - 0.4

                # Guarantee water surface never clips through any nearby road in the bounding box
                if self.exclusion and hasattr(self.exclusion, "road_corridor") and not self.exclusion.road_corridor.is_empty:
                    box_geom = box(minx, miny, maxx, maxy)
                    if box_geom.intersects(self.exclusion.road_corridor):
                        road_overlap = box_geom.intersection(self.exclusion.road_corridor)
                        if not road_overlap.is_empty:
                            if hasattr(road_overlap, "exterior"):
                                coords = list(road_overlap.exterior.coords)
                            elif hasattr(road_overlap, "geoms"):
                                coords = [pt for g in road_overlap.geoms if hasattr(g, "exterior") for pt in g.exterior.coords]
                            else:
                                coords = []
                            if coords:
                                min_road_z = min(self.heightmap.get_elevation_at_meters(rx, ry) for rx, ry in coords)
                                water_z = min(water_z, min_road_z - 1.0)

                water_depth = 15.0
                items.append({
                    "name": f"water_lake_{idx}",
                    "class": "WaterBlock",
                    "persistentId": str(uuid.uuid4()),
                    "__parent": "MissionGroup",
                    "position": [round(minx, 2), round(miny, 2), round(water_z - water_depth, 2)],
                    "scale": [round(w, 2), round(d, 2), water_depth],
                    "baseColor": [18, 90, 125, 220],
                    "clarity": 0.4,
                    "viscosity": 0.001,
                    "waterFogDensity": 0.6,
                    "wetDarkening": 0.2,
                    "wetDepth": 0.5,
                    "depthGradientMax": 15.0,
                    "reflectivity": 0.25,
                    "overallWaveMagnitude": 0.1,
                    "overallRippleMagnitude": 0.8,
                })
            except Exception:
                continue

        # 2. Ocean WaterPlane ONLY if actual coastline/sea is present in the area
        # and positioned safely at or below min elevation so roads and land are never submerged
        if has_coastline:
            ocean_z = min(self.specs.min_elev - 0.5, -0.5)
            items.append({
                "name": "Ocean",
                "class": "WaterPlane",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [0.0, 0.0, round(ocean_z, 2)],
                "baseColor": [15, 75, 115, 240],
                "clarity": 0.35,
                "viscosity": 0.001,
                "waterFogDensity": 0.7,
                "reflectivity": 0.3,
                "overallWaveMagnitude": 0.25,
                "overallRippleMagnitude": 1.0,
            })
            print(f"[WaterBuilder] Added ocean WaterPlane at Z = {ocean_z:.1f}m for coastline.")

        print(f"[WaterBuilder] Created {len(items)} physical water bodies.")
        return items
