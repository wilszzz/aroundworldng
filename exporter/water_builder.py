"""
Water Bodies and Ocean Generator for BeamNG.drive.
Generates physical WaterBlock instances for lakes/ponds and WaterPlane for sea/ocean.
"""

from typing import Any, Dict, List, Tuple
import uuid
from shapely.geometry import Polygon

from core.projection import lat_lon_to_meters
from processing.heightmap import HeightmapProcessor, TerrainSpecs


class WaterBuilder:
    """Creates physical BeamNG water objects (WaterBlock, WaterPlane) with fluid physics."""

    def __init__(
        self,
        heightmap: HeightmapProcessor,
        origin_lat: float,
        origin_lon: float,
        specs: TerrainSpecs,
    ):
        self.heightmap = heightmap
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.specs = specs

    def generate_water_items(
        self, water_polygons: List[List[Tuple[float, float]]]
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

                minx, miny, maxx, maxy = poly.bounds
                w = max(maxx - minx, 10.0)
                d = max(maxy - miny, 10.0)
                cx = (minx + maxx) / 2.0
                cy = (miny + maxy) / 2.0

                # Sample average water elevation
                z = self.heightmap.get_elevation_at_meters(cx, cy)

                items.append({
                    "name": f"water_lake_{idx}",
                    "class": "WaterBlock",
                    "persistentId": str(uuid.uuid4()),
                    "__parent": "MissionGroup",
                    "position": [round(minx, 2), round(miny, 2), round(z + 0.5, 2)],
                    "scale": [round(w, 2), round(d, 2), 15.0],
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

        # 2. Ocean WaterPlane (if map elevation reaches near or below sea level)
        if self.specs.min_elev <= 1.0:
            items.append({
                "name": "Ocean",
                "class": "WaterPlane",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [0.0, 0.0, 0.0],
                "baseColor": [15, 75, 115, 240],
                "clarity": 0.35,
                "viscosity": 0.001,
                "waterFogDensity": 0.7,
                "reflectivity": 0.3,
                "overallWaveMagnitude": 0.25,
                "overallRippleMagnitude": 1.0,
            })
            print("[WaterBuilder] Added global ocean WaterPlane at Z = 0.0m.")

        print(f"[WaterBuilder] Created {len(items)} physical water bodies.")
        return items
