"""
Yandex Maps Satellite Imagery Fetcher & Stitcher.
Downloads satellite tiles from Yandex and stitches them into a georeferenced orthophoto image.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import gc
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
        max_resolution: int = 2048,
    ) -> Image.Image:
        """
        Fetches satellite tiles covering the bounding box and stitches directly
        into a target texture canvas (up to max_resolution x max_resolution)
        to prevent excessive memory consumption.
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

        full_w = max(1, px_right - px_left)
        full_h = max(1, px_bottom - px_top)

        # Target dimensions (capped at max_resolution, default 2048, up to 4096)
        max_res = min(max(256, max_resolution), 4096)
        scale = min(1.0, float(max_res) / float(max(full_w, full_h)))
        target_w = max(1, int(round(full_w * scale)))
        target_h = max(1, int(round(full_h * scale)))

        canvas = Image.new("RGB", (target_w, target_h), color=(30, 30, 30))

        # Download tiles concurrently and stream-paste directly into target canvas
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_coord = {
                executor.submit(self.download_tile, tx, ty): (tx, ty)
                for tx, ty in tile_coords
            }
            for future in tqdm(as_completed(future_to_coord), total=total_tiles, desc="Tiles"):
                res = future.result()
                if not res:
                    continue
                tx, ty, img = res
                try:
                    t_x0 = tx * 256
                    t_y0 = ty * 256
                    t_x1 = (tx + 1) * 256
                    t_y1 = (ty + 1) * 256

                    ix0 = max(t_x0, px_left)
                    iy0 = max(t_y0, px_top)
                    ix1 = min(t_x1, px_right)
                    iy1 = min(t_y1, px_bottom)

                    if ix1 <= ix0 or iy1 <= iy0:
                        continue

                    crop_x0 = int(round(ix0 - t_x0))
                    crop_y0 = int(round(iy0 - t_y0))
                    crop_x1 = int(round(ix1 - t_x0))
                    crop_y1 = int(round(iy1 - t_y0))

                    tile_patch = img.crop((crop_x0, crop_y0, crop_x1, crop_y1))

                    dest_x0 = int(round((ix0 - px_left) * scale))
                    dest_y0 = int(round((iy0 - px_top) * scale))
                    dest_x1 = int(round((ix1 - px_left) * scale))
                    dest_y1 = int(round((iy1 - px_top) * scale))

                    dw = max(1, dest_x1 - dest_x0)
                    dh = max(1, dest_y1 - dest_y0)

                    if tile_patch.size != (dw, dh):
                        tile_resized = tile_patch.resize((dw, dh), Image.Resampling.BILINEAR)
                        tile_patch.close()
                        canvas.paste(tile_resized, (dest_x0, dest_y0))
                        tile_resized.close()
                        del tile_resized
                    else:
                        canvas.paste(tile_patch, (dest_x0, dest_y0))
                        tile_patch.close()
                        del tile_patch
                finally:
                    img.close()
                    del img

        gc.collect()
        return canvas
