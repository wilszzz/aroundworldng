"""
Multi-Layer Procedural Terrain Biome Engine for BeamNG.drive.
Generates layerMap for theTerrain.ter assigning realistic surface materials
(Grass, Asphalt, Dirt, Rock) based on slopes, road corridors, and building footprints.
Optimized for low RAM consumption with float32 arrays and fast C-accelerated rasterization.
"""

import gc
import math
from typing import List, Tuple
import numpy as np
from PIL import Image, ImageDraw

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
        self.elevations = np.asarray(elevations, dtype=np.float32)
        self.res = self.elevations.shape[0]
        self.square_size = float(square_size)
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.size = size_meters
        self.half_span = (self.res - 1) * self.square_size / 2.0

    def compute_layer_map(self, osm_data: OSMData) -> np.ndarray:
        """
        Computes 2D uint8 array (res, res) with material layer indices.
        Uses float32 slopes and fast PIL rasterization for zero-overhead stamping.
        """
        layer_map = np.zeros((self.res, self.res), dtype=np.uint8)  # Default: Grass (0)

        # 1. Slope Analysis in float32: Slopes > 25 degrees become Rock (3)
        gy, gx = np.gradient(self.elevations, np.float32(self.square_size))
        slope = np.hypot(gx, gy)
        steep_mask = slope > 0.466  # tan(25 deg) ≈ 0.466
        layer_map[steep_mask] = 3
        del gy, gx, slope, steep_mask
        gc.collect()

        # 2. Fast C-accelerated stamping of roads and buildings using PIL
        img = Image.fromarray(layer_map, mode="L")
        draw = ImageDraw.Draw(img)

        # 2a. Paint Roads onto LayerMap (Asphalt=1 or Dirt=2)
        for road in osm_data.roads:
            if road.is_bridge or road.is_tunnel:
                continue
            if len(road.nodes) < 2:
                continue

            is_dirt = road.surface in {"dirt", "ground", "earth", "gravel", "unpaved"}
            mat_idx = 2 if is_dirt else 1
            width_px = max(1, int(round((road.width + 2.0) / self.square_size)))

            pts_px = []
            for lat, lon in road.nodes:
                x, y = lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                px = (x + self.half_span) / self.square_size
                py = (y + self.half_span) / self.square_size
                pts_px.append((px, py))

            if len(pts_px) >= 2:
                draw.line(pts_px, fill=mat_idx, width=width_px, joint="curve")

        # 2b. Paint Ground under Buildings as Asphalt/Concrete base pads (1)
        for b_poly in osm_data.buildings:
            if len(b_poly) < 3:
                continue
            b_pts_px = []
            for lat, lon in b_poly:
                x, y = lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                px = (x + self.half_span) / self.square_size
                py = (y + self.half_span) / self.square_size
                b_pts_px.append((px, py))

            if len(b_pts_px) >= 3:
                draw.polygon(b_pts_px, fill=1)

        layer_map = np.asarray(img, dtype=np.uint8).copy()
        img.close()
        del img, draw
        gc.collect()

        print(
            f"[TerrainLayers] Multi-layer mapping: Grass={np.sum(layer_map == 0)}, "
            f"Asphalt={np.sum(layer_map == 1)}, Dirt={np.sum(layer_map == 2)}, Rock={np.sum(layer_map == 3)} cells."
        )
        return layer_map
