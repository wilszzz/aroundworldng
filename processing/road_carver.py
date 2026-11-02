"""
Road Carving and Terrain Conformance Engine.
Smooths terrain along road spline trajectories to eliminate unnatural bumps,
steps, and jagged vertical slopes, creating realistic roadbeds with embankments.
"""

from typing import List, Tuple
import numpy as np
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import LineString

from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment


class RoadCarver:
    """Modifies heightmap elevations to create smooth road foundations."""

    def __init__(
        self,
        heightmap: np.ndarray,
        square_size: float,
        origin_lat: float,
        origin_lon: float,
        blend_margin_meters: float = 4.0,
    ):
        """
        heightmap: 2D float32 numpy array (res, res)
        square_size: meters per pixel
        blend_margin_meters: width of lateral transition from roadbed to natural terrain
        """
        self.heights = heightmap
        self.res = heightmap.shape[0]
        self.square_size = square_size
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.margin = blend_margin_meters

    def sample_height(self, x_meters: float, y_meters: float) -> float:
        px = np.clip(x_meters / self.square_size, 0, self.res - 1)
        py = np.clip(y_meters / self.square_size, 0, self.res - 1)
        ix, iy = int(px), int(py)
        return float(self.heights[iy, ix])

    def carve_roads(self, roads: List[RoadSegment], sigma: float = 3.0) -> np.ndarray:
        """
        Applies road carving and terracing to the heightmap.
        Returns the modified heightmap array.
        """
        carved = self.heights.copy()
        print(f"[RoadCarver] Smoothing terrain for {len(roads)} roads (sigma={sigma})...")

        for road in roads:
            # Skip bridges and tunnels - they shouldn't deform ground terrain!
            if road.is_bridge or road.is_tunnel:
                continue

            if len(road.nodes) < 2:
                continue

            # Convert to local metric points
            pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in road.nodes
            ]

            line = LineString(pts)
            total_len = line.length
            if total_len < 5.0:
                continue

            # Sample points along the road spline every 2 meters
            step = 2.0
            num_samples = max(int(total_len / step), 3)
            sample_distances = np.linspace(0, total_len, num_samples)

            sampled_coords = [line.interpolate(d) for d in sample_distances]
            raw_elevs = np.array([self.sample_height(pt.x, pt.y) for pt in sampled_coords], dtype=np.float32)

            # Smooth longitudinal profile along the road
            smooth_elevs = gaussian_filter1d(raw_elevs, sigma=sigma, mode="nearest")

            half_width = road.width / 2.0
            influence_radius = half_width + self.margin

            # Carve each sample into heightmap grid
            for idx, pt in enumerate(sampled_coords):
                target_h = smooth_elevs[idx]

                # Bounding box in pixels for this sample point
                px_min = int(max(0, (pt.x - influence_radius) / self.square_size))
                px_max = int(min(self.res - 1, (pt.x + influence_radius) / self.square_size))
                py_min = int(max(0, (pt.y - influence_radius) / self.square_size))
                py_max = int(min(self.res - 1, (pt.y + influence_radius) / self.square_size))

                for py in range(py_min, py_max + 1):
                    for px in range(px_min, px_max + 1):
                        gx = px * self.square_size
                        gy = py * self.square_size
                        dist = np.hypot(gx - pt.x, gy - pt.y)

                        if dist <= half_width:
                            # Full flat roadbed
                            carved[py, px] = target_h
                        elif dist <= influence_radius:
                            # Smooth cosine transition to natural terrain
                            t = (dist - half_width) / self.margin
                            blend = 0.5 * (1.0 + np.cos(t * np.pi))  # 1 at road edge, 0 at margin edge
                            carved[py, px] = blend * target_h + (1.0 - blend) * carved[py, px]

        return carved
