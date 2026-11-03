"""
Main Generator Orchestrator.
Coordinates data fetching, geospatial processing, road carving, and level packaging.
"""

import gc
import math
import pathlib
from typing import Optional
import numpy as np
from PIL import Image

from core.config import MapConfig
from core.projection import meters_to_lat_lon
from exporter.level_builder import LevelBuilder
from fetchers.elevation import ElevationFetcher
from fetchers.osm import OSMFetcher
from fetchers.yandex_sat import YandexSatFetcher
from processing.exclusion import SpatialExclusionEngine
from processing.heightmap import HeightmapProcessor
from processing.road_carver import RoadCarver


class AroundWorldGenerator:
    """Master pipeline for generating BeamNG levels from real-world map data."""

    def __init__(self, config: MapConfig):
        self.cfg = config
        self.yandex_fetcher = YandexSatFetcher(zoom=self.cfg.sat_zoom)
        self.elevation_fetcher = ElevationFetcher()
        self.osm_fetcher = OSMFetcher()

    def generate(self) -> pathlib.Path:
        print("=" * 65)
        print(f" AroundWorldNG — Generating Level: {self.cfg.title}")
        print(f" Center: ({self.cfg.center_lat:.6f}, {self.cfg.center_lon:.6f})")
        print(f" Size: {self.cfg.size_meters:.0f}m x {self.cfg.size_meters:.0f}m | Res: {self.cfg.heightmap_res}x{self.cfg.heightmap_res}")
        print("=" * 65)

        # 1. Compute geographic bounding box
        half_size = self.cfg.size_meters / 2.0
        min_lat, min_lon = meters_to_lat_lon(-half_size, -half_size, self.cfg.center_lat, self.cfg.center_lon)
        max_lat, max_lon = meters_to_lat_lon(half_size, half_size, self.cfg.center_lat, self.cfg.center_lon)

        # 2. Fetch Yandex Satellite Imagery
        sat_image: Optional[Image.Image] = None
        if self.cfg.save_orthophoto:
            try:
                sat_image = self.yandex_fetcher.fetch_bbox(
                    min_lat, min_lon, max_lat, max_lon, max_resolution=self.cfg.sat_max_res
                )
            except Exception as e:
                print(f"[Generator] Warning: Could not download satellite tiles: {e}")
        gc.collect()

        # 3. Fetch Elevation Grid (DEM)
        try:
            raw_elevations = self.elevation_fetcher.fetch_elevation_grid(
                min_lat, min_lon, max_lat, max_lon, target_res=self.cfg.heightmap_res
            )
        except Exception as e:
            print(f"[Generator] Error fetching DEM ({e}), using default terrain plane.")
            raw_elevations = 50.0 + np.zeros((self.cfg.heightmap_res, self.cfg.heightmap_res), dtype=np.float32)
        gc.collect()

        # 4. Fetch OpenStreetMap Vectors
        osm_data = self.osm_fetcher.fetch_bbox_data(min_lat, min_lon, max_lat, max_lon)

        # 5. Spatial Exclusion Engine (Car-as-building prevention & road clearing)
        exclusion = SpatialExclusionEngine(
            roads=osm_data.roads,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
            clearance_meters=self.cfg.road_exclusion_buffer,
            min_building_area_sqm=12.0,
        )

        # Clean OSM buildings (filters out small noise and anything on roads)
        osm_data.buildings = exclusion.filter_buildings(osm_data.buildings)

        # 6. Road Carving & Longitudinal Smoothing
        if self.cfg.generate_roads and osm_data.roads:
            carver = RoadCarver(
                heightmap=raw_elevations,
                square_size=self.cfg.square_size,
                origin_lat=self.cfg.center_lat,
                origin_lon=self.cfg.center_lon,
            )
            processed_elevations = carver.carve_roads(
                osm_data.roads, sigma=self.cfg.road_carve_smoothing
            )
        else:
            processed_elevations = raw_elevations

        # 7. Heightmap Processing
        height_proc = HeightmapProcessor(
            elevations=processed_elevations,
            square_size=self.cfg.square_size,
        )
        terrain_specs = height_proc.compute_specs()

        # 8. Level Building & Packaging
        builder = LevelBuilder(self.cfg)
        output_pkg = builder.build_level(
            heightmap_proc=height_proc,
            terrain_specs=terrain_specs,
            osm_data=osm_data,
            exclusion=exclusion,
            sat_image=sat_image,
        )

        print("\n" + "=" * 65)
        print(f" [OK] Map successfully generated!")
        print(f" Output mod: {output_pkg}")
        print("=" * 65 + "\n")
        return output_pkg
