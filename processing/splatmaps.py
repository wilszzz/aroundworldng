"""
Splatmap / Weightmap Generator for BeamNG Terrain Materials.
Computes surface slope, aspect, and blends forest, rock, and grass material layers.
"""

from typing import Dict, List, Tuple
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from core.projection import lat_lon_to_meters


class SplatmapGenerator:
    """Generates material weightmaps (opacity masks) for BeamNG terrain."""

    def __init__(
        self,
        heightmap: np.ndarray,
        square_size: float,
        origin_lat: float,
        origin_lon: float,
    ):
        self.heights = heightmap
        self.res = heightmap.shape[0]
        self.square_size = square_size
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon

    def compute_slope_degrees(self) -> np.ndarray:
        """Calculates gradient/slope in degrees for each terrain cell."""
        dy, dx = np.gradient(self.heights, self.square_size)
        slope_rad = np.arctan(np.sqrt(dx * dx + dy * dy))
        return np.degrees(slope_rad)

    def generate_material_layers(
        self,
        forest_polygons: List[List[Tuple[float, float]]],
        water_polygons: List[List[Tuple[float, float]]],
    ) -> Dict[str, Image.Image]:
        """
        Generates 8-bit opacity maps (0..255) for:
        - rock: steep cliffs and slopes > 32 degrees
        - forest: forest ground under canopy
        - grass: gentle open plains
        """
        slope = self.compute_slope_degrees()

        # Rock layer: ramps from 0 at 28 deg to 255 at 45 deg
        rock_weight = np.clip((slope - 28.0) / (45.0 - 28.0), 0.0, 1.0) * 255.0
        rock_img = Image.fromarray(rock_weight.astype(np.uint8), mode="L")

        # Forest layer: rasterize forest polygons onto canvas
        forest_img = Image.new("L", (self.res, self.res), color=0)
        draw = ImageDraw.Draw(forest_img)

        for f_poly in forest_polygons:
            if len(f_poly) < 3:
                continue
            pixel_pts = []
            for lat, lon in f_poly:
                x_m, y_m = lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                px = x_m / self.square_size
                py = y_m / self.square_size
                pixel_pts.append((px, py))
            draw.polygon(pixel_pts, fill=220)

        # Grass layer: base layer filling areas not dominated by rock
        grass_weight = np.clip(255.0 - rock_weight, 0.0, 255.0)
        grass_img = Image.fromarray(grass_weight.astype(np.uint8), mode="L")

        return {
            "rock": rock_img,
            "forest": forest_img,
            "grass": grass_img,
        }
