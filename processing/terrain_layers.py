"""
Multi-Layer Procedural Terrain Biome Engine for BeamNG.drive.
Generates layerMap for theTerrain.ter assigning realistic surface materials
(Grass, Asphalt, Dirt, Rock) based on slopes, road corridors, and building footprints.
"""

import math
from typing import List, Tuple
import numpy as np
from shapely.geometry import LineString, Point, Polygon

from core.projection import lat_lon_to_meters
from fetchers.osm import OSMData, RoadSegment


class TerrainLayerEngine:
    """Generates procedural layerMap indices for BeamNG .ter binary."""

    # Material Indices:
    # 0: Grass (Lush vegetation)
    # 1: Asphalt (Roadbeds, aprons, parking, foundation pads)
    # 2: Dirt (Unpaved paths, trails, shoulders)
    # 3: Rock (Steep cliffs and mountain slopes)
    MATERIAL_NAMES = ["Grass", "Asphalt", "Dirt", "Rock"]

    def __init__(
        self,
        elevations: np.ndarray,
        square_size: float,
        origin_lat: float,
        origin_lon: float,
        size_meters: float,
    ):
        self.elevations = elevations
        self.res = elevations.shape[0]
        self.square_size = square_size
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.size = size_meters
        self.half_span = (self.res - 1) * self.square_size / 2.0

    def compute_layer_map(self, osm_data: OSMData) -> np.ndarray:
        """
        Computes 2D uint8 array (res, res) with material layer indices.
        """
        layer_map = np.zeros((self.res, self.res), dtype=np.uint8)  # Default: Grass (0)

        # 1. Slope Analysis: Slopes > 25 degrees become Rock (3)
        gy, gx = np.gradient(self.elevations, self.square_size)
        slope = np.hypot(gx, gy)
        steep_mask = slope > 0.466  # tan(25 deg) ≈ 0.466
        layer_map[steep_mask] = 3

        # 2. Paint Roads onto LayerMap (Asphalt or Dirt)
        for road in osm_data.roads:
            if road.is_bridge or road.is_tunnel:
                continue
            if len(road.nodes) < 2:
                continue

            pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in road.nodes
            ]

            is_dirt = road.surface in {"dirt", "ground", "earth", "gravel", "unpaved"}
            mat_idx = 2 if is_dirt else 1
            half_w = (road.width / 2.0) + 1.0  # slight apron margin

            # Stamp road segments onto grid
            for i in range(len(pts) - 1):
                p1, p2 = pts[i], pts[i + 1]
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 1.0:
                    continue

                steps = max(int(seg_len / 2.0), 2)
                for s in range(steps + 1):
                    t = s / steps
                    cx = p1[0] + dx * t
                    cy = p1[1] + dy * t

                    px_min = int(max(0, (cx - half_w + self.half_span) / self.square_size))
                    px_max = int(min(self.res - 1, (cx + half_w + self.half_span) / self.square_size))
                    py_min = int(max(0, (cy - half_w + self.half_span) / self.square_size))
                    py_max = int(min(self.res - 1, (cy + half_w + self.half_span) / self.square_size))

                    for py in range(py_min, py_max + 1):
                        for px in range(px_min, px_max + 1):
                            gx_pt = px * self.square_size - self.half_span
                            gy_pt = py * self.square_size - self.half_span
                            if math.hypot(gx_pt - cx, gy_pt - cy) <= half_w:
                                layer_map[py, px] = mat_idx

        # 3. Paint Ground under Buildings as Asphalt/Concrete base pads (1)
        for b_poly in osm_data.buildings:
            if len(b_poly) < 3:
                continue
            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in b_poly
            ]
            xs = [p[0] for p in metric_pts]
            ys = [p[1] for p in metric_pts]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)

            px_min = int(max(0, (minx + self.half_span) / self.square_size))
            px_max = int(min(self.res - 1, (maxx + self.half_span) / self.square_size))
            py_min = int(max(0, (miny + self.half_span) / self.square_size))
            py_max = int(min(self.res - 1, (maxy + self.half_span) / self.square_size))

            poly = Polygon(metric_pts)
            for py in range(py_min, py_max + 1):
                for px in range(px_min, px_max + 1):
                    gx_pt = px * self.square_size - self.half_span
                    gy_pt = py * self.square_size - self.half_span
                    if poly.contains(Point(gx_pt, gy_pt)):
                        layer_map[py, px] = 1

        print(
            f"[TerrainLayers] Multi-layer mapping: Grass={np.sum(layer_map == 0)}, "
            f"Asphalt={np.sum(layer_map == 1)}, Dirt={np.sum(layer_map == 2)}, Rock={np.sum(layer_map == 3)} cells."
        )
        return layer_map
