"""
Yandex Maps Satellite Imagery Fetcher & Stitcher.
Downloads satellite tiles from Yandex and stitches them into a georeferenced orthophoto image.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import math
from typing import Dict, List, Optional, Tuple
from PIL import Image
import requests
from tqdm import tqdm

from core.projection import (
    lat_lon_to_yandex_pixel,
    lat_lon_to_yandex_tile,
    yandex_pixel_to_lat_lon,
)

YANDEX_SAT_URL = "https://core-sat.maps.yandex.net/tiles?l=sat&x={x}&y={y}&z={z}&scale=1&lang=ru_RU"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://yandex.ru/maps/",
}


class YandexSatFetcher:
    """Handles fetching and mosaic stitching of Yandex satellite tiles."""

    def __init__(self, zoom: int = 18, max_workers: int = 8):
        self.zoom = zoom
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def download_tile(self, x: int, y: int) -> Optional[Tuple[int, int, Image.Image]]:
        url = YANDEX_SAT_URL.format(x=x, y=y, z=self.zoom)
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                    return (x, y, img)
                elif resp.status_code == 404:
                    # Tile not found / empty area - return blank black tile
                    return (x, y, Image.new("RGB", (256, 256), color=(20, 20, 20)))
            except Exception:
                pass
        return None

    def fetch_bbox(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
    ) -> Image.Image:
        """
        Fetches all satellite tiles covering the bounding box and crops
        to the exact bounding box in Yandex projection space.
        """
        # Get pixel bounds at target zoom
        # Note: In Yandex projection, max_lat has smaller pixel Y than min_lat
        px_min_x, px_max_y = lat_lon_to_yandex_pixel(min_lat, min_lon, self.zoom)
        px_max_x, px_min_y = lat_lon_to_yandex_pixel(max_lat, max_lon, self.zoom)

        # Ensure correct ordering
        px_left = min(px_min_x, px_max_x)
        px_right = max(px_min_x, px_max_x)
        px_top = min(px_min_y, px_max_y)
        px_bottom = max(px_min_y, px_max_y)

        # Tile coordinate ranges
        tile_x_min = int(math.floor(px_left / 256.0))
        tile_x_max = int(math.floor(px_right / 256.0))
        tile_y_min = int(math.floor(px_top / 256.0))
        tile_y_max = int(math.floor(px_bottom / 256.0))

        tile_coords = [
            (tx, ty)
            for tx in range(tile_x_min, tile_x_max + 1)
            for ty in range(tile_y_min, tile_y_max + 1)
        ]

        total_tiles = len(tile_coords)
        print(f"[YandexSat] Fetching {total_tiles} tiles (Zoom {self.zoom})...")

        # Download tiles concurrently
        tiles: Dict[Tuple[int, int], Image.Image] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_coord = {
                executor.submit(self.download_tile, tx, ty): (tx, ty)
                for tx, ty in tile_coords
            }
            for future in tqdm(as_completed(future_to_coord), total=total_tiles, desc="Tiles"):
                res = future.result()
                if res:
                    tx, ty, img = res
                    tiles[(tx, ty)] = img

        # Stitch full canvas
        canvas_width = (tile_x_max - tile_x_min + 1) * 256
        canvas_height = (tile_y_max - tile_y_min + 1) * 256
        canvas = Image.new("RGB", (canvas_width, canvas_height), color=(30, 30, 30))

        for (tx, ty), img in tiles.items():
            offset_x = (tx - tile_x_min) * 256
            offset_y = (ty - tile_y_min) * 256
            canvas.paste(img, (offset_x, offset_y))

        # Crop to exact pixel bounding box
        crop_left = int(px_left - tile_x_min * 256)
        crop_top = int(px_top - tile_y_min * 256)
        crop_right = int(px_right - tile_x_min * 256)
        crop_bottom = int(px_bottom - tile_y_min * 256)

        cropped = canvas.crop((crop_left, crop_top, crop_right, crop_bottom))
        return cropped
