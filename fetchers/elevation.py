"""
Global Elevation (DEM) Data Fetcher.
Uses AWS Terrarium DEM tiles (Copernicus DEM & SRTM) to extract high-accuracy elevation grids.
Terrarium encoding:
    elevation_meters = (R * 256 + G + B / 256) - 32768
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import math
from typing import Dict, Optional, Tuple
import numpy as np
from PIL import Image
import requests
from scipy.interpolate import RegularGridInterpolator
from tqdm import tqdm

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lat_lon_to_web_mercator_tile(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Converts WGS84 (lat, lon) to continuous Web Mercator (EPSG:3857) tile coordinates."""
    lat_rad = math.radians(max(min(lat, 85.0511), -85.0511))
    n = 1 << zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


class ElevationFetcher:
    """Fetches DEM tiles and builds an elevation grid."""

    def __init__(self, zoom: int = 13, max_workers: int = 6):
        self.zoom = zoom
        self.max_workers = max_workers
        self.session = requests.Session()

    def download_tile(self, x: int, y: int) -> Optional[Tuple[int, int, np.ndarray]]:
        url = TERRARIUM_URL.format(z=self.zoom, x=x, y=y)
        for _ in range(3):
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                    rgb = np.array(img, dtype=np.float32)
                    # Decode Terrarium height formula
                    elev = (rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0) - 32768.0
                    return (x, y, elev)
            except Exception:
                pass
        return None

    def fetch_elevation_grid(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        target_res: int = 1025,
    ) -> np.ndarray:
        """
        Fetches DEM tiles covering the bbox and resamples onto a target_res x target_res float32 grid.
        Returns array of shape (target_res, target_res) where [0, 0] is South-West (min_x, min_y).
        """
        # Get tile coordinate range in Web Mercator
        tile_min_x_f, tile_max_y_f = lat_lon_to_web_mercator_tile(min_lat, min_lon, self.zoom)
        tile_max_x_f, tile_min_y_f = lat_lon_to_web_mercator_tile(max_lat, max_lon, self.zoom)

        tile_x_min = int(math.floor(min(tile_min_x_f, tile_max_x_f)))
        tile_x_max = int(math.floor(max(tile_min_x_f, tile_max_x_f)))
        tile_y_min = int(math.floor(min(tile_min_y_f, tile_max_y_f)))
        tile_y_max = int(math.floor(max(tile_min_y_f, tile_max_y_f)))

        tile_coords = [
            (tx, ty)
            for tx in range(tile_x_min, tile_x_max + 1)
            for ty in range(tile_y_min, tile_y_max + 1)
        ]

        print(f"[Elevation] Fetching {len(tile_coords)} DEM tiles (Zoom {self.zoom})...")

        tiles: Dict[Tuple[int, int], np.ndarray] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_coord = {
                executor.submit(self.download_tile, tx, ty): (tx, ty)
                for tx, ty in tile_coords
            }
            for future in tqdm(as_completed(future_to_coord), total=len(tile_coords), desc="DEM"):
                res = future.result()
                if res:
                    tx, ty, elev = res
                    tiles[(tx, ty)] = elev

        # Build composite array
        cols = tile_x_max - tile_x_min + 1
        rows = tile_y_max - tile_y_min + 1
        composite = np.zeros((rows * 256, cols * 256), dtype=np.float32)

        for (tx, ty), tile_elev in tiles.items():
            r = (ty - tile_y_min) * 256
            c = (tx - tile_x_min) * 256
            composite[r : r + 256, c : c + 256] = tile_elev

        # Generate sample points for target grid
        # In Web Mercator tile space:
        xs = np.linspace(min(tile_min_x_f, tile_max_x_f), max(tile_min_x_f, tile_max_x_f), target_res)
        # Note: Tile Y increases downwards (South), so North (max_lat) has smaller tile Y
        ys = np.linspace(tile_min_y_f, tile_max_y_f, target_res)

        # Convert to pixel coordinates inside composite
        comp_x = (xs - tile_x_min) * 256.0
        comp_y = (ys - tile_y_min) * 256.0

        comp_x = np.clip(comp_x, 0, composite.shape[1] - 1)
        comp_y = np.clip(comp_y, 0, composite.shape[0] - 1)

        # Interpolate
        grid_y = np.arange(composite.shape[0])
        grid_x = np.arange(composite.shape[1])
        interpolator = RegularGridInterpolator((grid_y, grid_x), composite, method="linear")

        mesh_y, mesh_x = np.meshgrid(comp_y, comp_x, indexing="ij")
        points = np.stack([mesh_y.ravel(), mesh_x.ravel()], axis=-1)
        resampled = interpolator(points).reshape(target_res, target_res)

        # Flip so row 0 is South (increasing Y = North for BeamNG terrain)
        resampled_flipped = np.flipud(resampled)
        return resampled_flipped.astype(np.float32)
