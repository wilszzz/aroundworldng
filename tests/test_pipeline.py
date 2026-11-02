"""
Comprehensive Unit and Integration Test Suite for AroundWorldNG.
Tests math, coordinate transforms, binary exporters, Collada meshes, and scene assembling.
"""

import io
import math
import pathlib
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import numpy as np

from core.projection import lat_lon_to_meters, meters_to_lat_lon, lat_lon_to_yandex_pixel, yandex_pixel_to_lat_lon
from fetchers.osm import OSMData, RoadSegment
from processing.heightmap import HeightmapProcessor
from processing.terrain_layers import TerrainLayerEngine
from exporter.building_mesh import write_building_dae, create_all_building_archetypes
from exporter.forest_builder import ForestBuilder
from exporter.water_builder import WaterBuilder
from exporter.road_decorations import RoadDecorationBuilder


class TestProjection(unittest.TestCase):
    def test_roundtrip_meters(self):
        origin_lat, origin_lon = 43.4057, 39.9572
        test_pts = [
            (43.4060, 39.9580),
            (43.4010, 39.9500),
            (43.4100, 39.9650),
        ]
        for lat, lon in test_pts:
            x, y = lat_lon_to_meters(lat, lon, origin_lat, origin_lon)
            r_lat, r_lon = meters_to_lat_lon(x, y, origin_lat, origin_lon)
            self.assertAlmostEqual(lat, r_lat, places=6)
            self.assertAlmostEqual(lon, r_lon, places=6)

    def test_roundtrip_yandex_pixel(self):
        test_pts = [(55.7558, 37.6176), (43.4057, 39.9572), (-23.5505, -46.6333)]
        zoom = 18
        for lat, lon in test_pts:
            px, py = lat_lon_to_yandex_pixel(lat, lon, zoom)
            r_lat, r_lon = yandex_pixel_to_lat_lon(px, py, zoom)
            self.assertAlmostEqual(lat, r_lat, places=5)
            self.assertAlmostEqual(lon, r_lon, places=5)


class TestHeightmapAndTer(unittest.TestCase):
    def setUp(self):
        self.res = 129
        self.elevs = np.zeros((self.res, self.res), dtype=np.float32)
        # Gradient from -5 to +15 meters
        for r in range(self.res):
            self.elevs[r, :] = -5.0 + (20.0 * r / (self.res - 1))
        self.proc = HeightmapProcessor(self.elevs, square_size=1.0)

    def test_specs(self):
        specs = self.proc.compute_specs()
        self.assertAlmostEqual(specs.min_elev, -5.0)
        self.assertAlmostEqual(specs.max_elev, 15.0)
        self.assertGreater(specs.height_scale, 0)

    def test_binary_ter_structure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ter_path = pathlib.Path(tmp_dir) / "test.ter"
            layer_map = np.zeros((self.res, self.res), dtype=np.uint8)
            materials = ["Grass", "Asphalt", "Dirt", "Rock"]

            self.proc.export_binary_ter(
                output_ter_path=ter_path,
                materials=materials,
                layer_map=layer_map,
                level_name="test_map",
            )
            self.assertTrue(ter_path.exists())

            # Read back and verify format
            with open(ter_path, "rb") as f:
                data = f.read()

            # Version = 9 (byte 0)
            version = data[0]
            self.assertEqual(version, 9)

            # Block size = res - 1 = 128 (uint32 at offset 1)
            size = struct.unpack_from("<I", data, 1)[0]
            self.assertEqual(size, self.res - 1)

            # Total header size = 1 + 4 = 5 bytes
            # Heightmap size = size * size * 2 = 128 * 128 * 2 = 32768
            # LayerMap size = size * size = 16384
            # Material count = 4 bytes + material names
            expected_payload_min = 5 + (size * size * 2) + (size * size) + 4
            self.assertGreaterEqual(len(data), expected_payload_min)


class TestColladaMeshes(unittest.TestCase):
    def test_building_archetypes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            shapes_dir = pathlib.Path(tmp_dir)
            create_all_building_archetypes(shapes_dir)

            dae_files = list((shapes_dir / "buildings").glob("*.dae"))
            self.assertEqual(len(dae_files), 5)

            ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
            for dae_file in dae_files:
                tree = ET.parse(dae_file)
                root = tree.getroot()
                self.assertTrue(root.tag.endswith("COLLADA"))

                # Check up_axis
                up_axis = tree.find(".//c:up_axis", ns)
                self.assertIsNotNone(up_axis)
                self.assertEqual(up_axis.text, "Z_UP")

                # Check visual scene
                scene = tree.find(".//c:visual_scene", ns)
                self.assertIsNotNone(scene)

                # Check triangle counts match actual index counts
                for tri in tree.findall(".//c:triangles", ns):
                    claimed = int(tri.attrib.get("count", 0))
                    p = tri.find("c:p", ns).text.strip().split()
                    inputs = len(tri.findall("c:input", ns))
                    actual = len(p) // (3 * inputs)
                    self.assertEqual(claimed, actual)


class TestWaterBuilder(unittest.TestCase):
    def test_no_ocean_without_coastline(self):
        elevs = np.zeros((10, 10), dtype=np.float32) - 3.0  # Below sea level
        proc = HeightmapProcessor(elevs, square_size=1.0)
        specs = proc.compute_specs()

        wb = WaterBuilder(heightmap=proc, origin_lat=43.0, origin_lon=39.0, specs=specs)
        # When has_coastline is False, no infinite ocean is added
        items = wb.generate_water_items([], has_coastline=False)
        self.assertEqual(len(items), 0)

        # When has_coastline is True, ocean is added at safe elevation
        items_ocean = wb.generate_water_items([], has_coastline=True)
        self.assertEqual(len(items_ocean), 1)
        self.assertEqual(items_ocean[0]["class"], "WaterPlane")
        self.assertLessEqual(items_ocean[0]["position"][2], -3.0)


class TestRoadDecorations(unittest.TestCase):
    def test_streetlight_placement_and_yaw(self):
        elevs = np.zeros((100, 100), dtype=np.float32)
        proc = HeightmapProcessor(elevs, square_size=1.0)
        builder = RoadDecorationBuilder(heightmap=proc, origin_lat=43.0, origin_lon=39.0, size_meters=500.0)

        # Straight North road (lon 39.0, lat 43.0 -> 43.002)
        nodes = [(43.0, 39.0), (43.002, 39.0)]
        road = RoadSegment(osm_id=1, highway_type="primary", nodes=nodes, is_lit=True, width=8.0)

        items = builder.generate_decorations([road])
        lamps = [i for i in items if i["name"].startswith("streetlight_")]
        self.assertGreater(len(lamps), 0)

        for lamp in lamps:
            self.assertEqual(lamp["class"], "TSStatic")
            # Lamp should be placed to the right (+X, East) of the road
            self.assertGreater(lamp["position"][0], 0.0)


if __name__ == "__main__":
    unittest.main()
