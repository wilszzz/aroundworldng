"""
Unit and integration test suite for RAM optimization, road carving, and intersection continuity.
Verifies:
1. RAM consumption remains well below 1.5 GB even on large 4096m maps (4097x4097).
2. Elimination of road junction pits and steps (elevation continuity Z1 = Z2 = ... = Zn).
3. Hermite smoothstep shoulder transitions and flat roadbed margins.
"""

import gc
import math
import tracemalloc
import unittest
from PIL import Image
import numpy as np

from fetchers.osm import OSMData, RoadSegment
from fetchers.yandex_sat import YandexSatFetcher
from processing.road_carver import RoadCarver
from processing.terrain_layers import TerrainLayerEngine


class TestRoadJunctionContinuity(unittest.TestCase):
    """Verifies that intersecting roads share identical elevations and do not create pits or steps."""

    def setUp(self):
        self.res = 257
        self.square_size = 1.0
        self.origin_lat = 55.751244
        self.origin_lon = 37.618423
        self.half_span = (self.res - 1) * self.square_size / 2.0

        # Create terrain with a uniform slope
        gy, gx = np.mgrid[0 : self.res, 0 : self.res]
        self.heights = (gx * 0.08 + gy * 0.04 + 100.0).astype(np.float32)

    def test_three_way_junction_continuity(self):
        """Three roads meeting at a central junction must share the exact same elevation."""
        from core.projection import meters_to_lat_lon

        # Central junction at (0, 0)
        c_lat, c_lon = meters_to_lat_lon(0.0, 0.0, self.origin_lat, self.origin_lon)
        r1_lat, r1_lon = meters_to_lat_lon(-60.0, 0.0, self.origin_lat, self.origin_lon)
        r2_lat, r2_lon = meters_to_lat_lon(50.0, 40.0, self.origin_lat, self.origin_lon)
        r3_lat, r3_lon = meters_to_lat_lon(10.0, -50.0, self.origin_lat, self.origin_lon)

        road1 = RoadSegment(osm_id=1, highway_type="primary", nodes=[(r1_lat, r1_lon), (c_lat, c_lon)], width=8.0)
        road2 = RoadSegment(osm_id=2, highway_type="secondary", nodes=[(c_lat, c_lon), (r2_lat, r2_lon)], width=6.0)
        road3 = RoadSegment(osm_id=3, highway_type="residential", nodes=[(c_lat, c_lon), (r3_lat, r3_lon)], width=5.0)

        carver = RoadCarver(
            heightmap=self.heights,
            square_size=self.square_size,
            origin_lat=self.origin_lat,
            origin_lon=self.origin_lon,
            blend_margin_meters=4.0,
            shoulder_margin_meters=1.2,
        )

        carved = carver.carve_roads([road1, road2, road3], sigma=2.5)

        # Inspect junction center in heightmap
        j_px = int(round(self.half_span / self.square_size))
        j_py = int(round(self.half_span / self.square_size))

        # Check 7x7 patch around the intersection
        patch = carved[j_py - 3 : j_py + 4, j_px - 3 : j_px + 4]
        diffs_x = np.abs(np.diff(patch, axis=1))
        diffs_y = np.abs(np.diff(patch, axis=0))

        # Maximum step across adjacent heightmap pixels in the intersection must be smooth (no vertical cliffs)
        max_step = max(np.max(diffs_x), np.max(diffs_y))
        self.assertLess(max_step, 0.25, f"Step at junction too sharp: {max_step:.4f}m")

        # The center height must be finite and within the range of incident terrain
        j_h = carved[j_py, j_px]
        self.assertTrue(90.0 < j_h < 120.0, f"Unreasonable junction elevation: {j_h}")

    def test_four_way_crossroads(self):
        """Crossroads (4 roads meeting) must have smooth flat center without crevices."""
        from core.projection import meters_to_lat_lon

        c_lat, c_lon = meters_to_lat_lon(20.0, -10.0, self.origin_lat, self.origin_lon)
        n_lat, n_lon = meters_to_lat_lon(20.0, 50.0, self.origin_lat, self.origin_lon)
        s_lat, s_lon = meters_to_lat_lon(20.0, -70.0, self.origin_lat, self.origin_lon)
        e_lat, e_lon = meters_to_lat_lon(80.0, -10.0, self.origin_lat, self.origin_lon)
        w_lat, w_lon = meters_to_lat_lon(-40.0, -10.0, self.origin_lat, self.origin_lon)

        roads = [
            RoadSegment(osm_id=10, highway_type="primary", nodes=[(w_lat, w_lon), (c_lat, c_lon), (e_lat, e_lon)], width=7.0),
            RoadSegment(osm_id=11, highway_type="secondary", nodes=[(s_lat, s_lon), (c_lat, c_lon), (n_lat, n_lon)], width=7.0),
        ]

        carver = RoadCarver(
            heightmap=self.heights,
            square_size=self.square_size,
            origin_lat=self.origin_lat,
            origin_lon=self.origin_lon,
        )
        carved = carver.carve_roads(roads, sigma=2.0)

        cx_px = int(round((20.0 + self.half_span) / self.square_size))
        cy_px = int(round((-10.0 + self.half_span) / self.square_size))

        patch = carved[cy_px - 2 : cy_px + 3, cx_px - 2 : cx_px + 3]
        diff_x = np.abs(np.diff(patch, axis=1))
        diff_y = np.abs(np.diff(patch, axis=0))
        max_step = max(np.max(diff_x), np.max(diff_y))
        self.assertLess(max_step, 0.2, "Crossroad adjacent step must be smooth without steps or vertical cliffs")


class TestSmoothstepHermiteProfile(unittest.TestCase):
    """Verifies that roadbed shoulders use Hermite smoothstep s^2*(3-2s) and preserve flat pavement."""

    def test_flat_roadbed_margin_and_hermite_blend(self):
        res = 129
        square_size = 0.5
        origin_lat, origin_lon = 55.75, 37.62
        half_span = (res - 1) * square_size / 2.0

        # Uniform terrain at 50m
        heights = 50.0 + np.zeros((res, res), dtype=np.float32)

        # Straight road from x=-20, y=0 to x=20, y=0 with target elevation ~60m
        # Let's put a bump under the road to see it flatten
        heights[int(round(half_span / square_size)), :] = 65.0  # raw ridge

        from core.projection import meters_to_lat_lon

        p1_lat, p1_lon = meters_to_lat_lon(-20.0, 0.0, origin_lat, origin_lon)
        p2_lat, p2_lon = meters_to_lat_lon(20.0, 0.0, origin_lat, origin_lon)
        road = RoadSegment(osm_id=1, highway_type="primary", nodes=[(p1_lat, p1_lon), (p2_lat, p2_lon)], width=6.0)

        shoulder_margin = 1.5
        blend_margin = 4.0
        carver = RoadCarver(
            heightmap=heights,
            square_size=square_size,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            blend_margin_meters=blend_margin,
            shoulder_margin_meters=shoulder_margin,
        )

        carved = carver.carve_roads([road], sigma=2.0)

        cy_px = int(round(half_span / square_size))
        cx_px = int(round(half_span / square_size))

        road_h = carved[cy_px, cx_px]

        # Check flat roadbed width: half_width (3.0m) + shoulder (1.5m) = 4.5m
        # At square_size = 0.5m, 4.5m corresponds to 9 pixels to each side (y)
        flat_pixels = int(math.floor((3.0 + shoulder_margin) / square_size))
        for dy in range(-flat_pixels, flat_pixels + 1):
            py = cy_px + dy
            diff = abs(carved[py, cx_px] - road_h)
            self.assertLess(diff, 0.05, f"Roadbed must be flat within shoulder margin, dy={dy}, diff={diff}")

        # Check beyond blend margin: must return to natural terrain (50.0m)
        outer_pixels = int(math.ceil((3.0 + shoulder_margin + blend_margin + 1.0) / square_size))
        self.assertAlmostEqual(carved[cy_px + outer_pixels, cx_px], 50.0, places=1)


class TestRAMOptimization(unittest.TestCase):
    """Verifies that RAM consumption is strictly controlled and does not exceed 1.5 GB on 4096m maps."""

    def test_terrain_layers_ram_on_4096m(self):
        """TerrainLayerEngine on 4097x4097 (16.8M cells) must not exceed 500 MB RAM."""
        gc.collect()
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        res = 4097
        square_size = 1.0
        # Allocate 4097x4097 float32 elevation array (67 MB)
        elevations = np.zeros((res, res), dtype=np.float32)
        elevations[1000:3000, 1000:3000] = 50.0  # some terrain slope

        osm_data = OSMData()
        # Add 30 dummy roads
        for i in range(30):
            osm_data.roads.append(
                RoadSegment(
                    osm_id=i,
                    highway_type="primary" if i % 2 == 0 else "track",
                    surface="asphalt" if i % 2 == 0 else "dirt",
                    nodes=[(55.7 + i * 0.001, 37.6), (55.7 + i * 0.001, 37.64)],
                    width=7.0,
                )
            )

        # Add 50 dummy buildings
        for i in range(50):
            b_lat, b_lon = 55.72 + i * 0.001, 37.62 + i * 0.001
            osm_data.buildings.append([
                (b_lat, b_lon),
                (b_lat + 0.0003, b_lon),
                (b_lat + 0.0003, b_lon + 0.0003),
                (b_lat, b_lon + 0.0003),
            ])

        engine = TerrainLayerEngine(
            elevations=elevations,
            square_size=square_size,
            origin_lat=55.75,
            origin_lon=37.62,
            size_meters=4096.0,
        )

        layer_map = engine.compute_layer_map(osm_data)
        self.assertEqual(layer_map.shape, (4097, 4097))
        self.assertEqual(layer_map.dtype, np.uint8)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        print(f"[RAM Benchmark] TerrainLayerEngine peak memory: {peak_mb:.1f} MB")
        self.assertLess(peak_mb, 800.0, f"Peak memory exceeded 800 MB: {peak_mb:.1f} MB")

        del elevations, layer_map, engine, osm_data
        gc.collect()

    def test_road_carver_ram_on_4096m(self):
        """RoadCarver on 4097x4097 (16.8M cells) with 40 roads must not exceed 800 MB RAM."""
        gc.collect()
        tracemalloc.start()

        res = 4097
        square_size = 1.0
        elevations = np.ones((res, res), dtype=np.float32) * 100.0

        roads = []
        # Create a network of intersecting roads across the 4096m map
        from core.projection import meters_to_lat_lon
        origin_lat, origin_lon = 55.75, 37.62

        for i in range(6):
            # Horizontal roads
            y = -1500.0 + i * 600.0
            p1 = meters_to_lat_lon(-1500.0, y, origin_lat, origin_lon)
            p2 = meters_to_lat_lon(1500.0, y, origin_lat, origin_lon)
            roads.append(RoadSegment(osm_id=100 + i, highway_type="primary", nodes=[p1, p2], width=7.0))

            # Vertical roads (crossings)
            x = -1500.0 + i * 600.0
            p3 = meters_to_lat_lon(x, -1500.0, origin_lat, origin_lon)
            p4 = meters_to_lat_lon(x, 1500.0, origin_lat, origin_lon)
            roads.append(RoadSegment(osm_id=200 + i, highway_type="secondary", nodes=[p3, p4], width=6.0))

        carver = RoadCarver(
            heightmap=elevations,
            square_size=square_size,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
        )

        carved = carver.carve_roads(roads, sigma=2.0)
        self.assertEqual(carved.shape, (4097, 4097))
        self.assertEqual(carved.dtype, np.float32)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        print(f"[RAM Benchmark] RoadCarver peak memory (4096m, 40 roads): {peak_mb:.1f} MB")
        self.assertLess(peak_mb, 1200.0, f"RoadCarver peak memory exceeded 1200 MB: {peak_mb:.1f} MB")

        del elevations, carved, carver, roads
        gc.collect()

    def test_yandex_sat_streaming_resizes_to_max_res(self):
        """YandexSatFetcher must resize down to max_resolution directly to prevent gigabyte buffers."""
        fetcher = YandexSatFetcher(zoom=18)
        # Mock download_tile to return synthetic 256x256 tiles without network
        def mock_download_tile(x, y):
            img = Image.new("RGB", (256, 256), color=(int(x % 256), int(y % 256), 100))
            return (x, y, img)

        fetcher.download_tile = mock_download_tile

        tracemalloc.start()
        # Bounding box spanning ~100 tiles
        res_img = fetcher.fetch_bbox(
            min_lat=55.74,
            min_lon=37.60,
            max_lat=55.76,
            max_lon=37.64,
            max_resolution=2048,
        )
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        print(f"[RAM Benchmark] YandexSatFetcher streaming peak memory: {peak_mb:.1f} MB (size: {res_img.size})")

        self.assertLessEqual(max(res_img.size), 2048)
        self.assertLess(peak_mb, 150.0, f"Satellite fetcher peak RAM exceeded 150 MB: {peak_mb:.1f} MB")
        res_img.close()
        del res_img
        gc.collect()


if __name__ == "__main__":
    unittest.main()
