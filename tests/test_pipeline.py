"""
Comprehensive Unit and Integration Test Suite for AroundWorldNG.
Tests math, coordinate transforms, binary exporters, Collada meshes, and scene assembling.
"""

import io
import json
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
from processing.exclusion import SpatialExclusionEngine
from exporter.building_mesh import (
    write_building_dae,
    create_all_building_archetypes,
    clean_ring,
    triangulate,
    is_convex_quad,
    ProceduralBuildingMesh,
    write_sector_dae,
)
from exporter.buildings import BuildingExporter
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

            # Header = 1 + 4 = 5 bytes
            offset = 5

            # Heightmap size = size * size * 2 = 128 * 128 * 2 = 32768
            hm_bytes = size * size * 2
            offset += hm_bytes

            # LayerMap size = size * size = 16384
            lm_bytes = size * size
            offset += lm_bytes

            # LayerTextureMap size = size * size = 16384 (Crucial Torque3D v9 layer texture map)
            ltm_bytes = size * size
            ltm_data = data[offset : offset + ltm_bytes]
            self.assertEqual(len(ltm_data), ltm_bytes)
            self.assertEqual(set(ltm_data), {0}, "LayerTextureMap must be zero-filled")
            offset += ltm_bytes

            # Material count = 4 bytes (uint32)
            mat_count = struct.unpack_from("<I", data, offset)[0]
            self.assertEqual(mat_count, len(materials))
            offset += 4

            # Material names
            parsed_materials = []
            for _ in range(mat_count):
                m_len = data[offset]
                offset += 1
                m_str = data[offset : offset + m_len].decode("ascii")
                offset += m_len
                parsed_materials.append(m_str)

            self.assertEqual(parsed_materials, materials)
            # Exact total file length matching Torque3D v9 specification
            self.assertEqual(len(data), offset)


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

    def test_water_lake_elevation_below_bank(self):
        # Heightmap with bank at 20.0m and center at 15.0m
        elevs = np.full((51, 51), 20.0, dtype=np.float32)
        elevs[24:27, 24:27] = 15.0
        proc = HeightmapProcessor(elevs, square_size=1.0)
        specs = proc.compute_specs()

        origin_lat, origin_lon = 43.0, 39.0
        wb = WaterBuilder(heightmap=proc, origin_lat=origin_lat, origin_lon=origin_lon, specs=specs)
        # Lake centered around (0, 0)
        p0 = meters_to_lat_lon(-5.0, -5.0, origin_lat, origin_lon)
        p1 = meters_to_lat_lon(5.0, -5.0, origin_lat, origin_lon)
        p2 = meters_to_lat_lon(5.0, 5.0, origin_lat, origin_lon)
        p3 = meters_to_lat_lon(-5.0, 5.0, origin_lat, origin_lon)

        items = wb.generate_water_items([[p0, p1, p2, p3]])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["class"], "WaterBlock")
        # Water elevation must be strictly below bank (20.0m) and center (15.0m)
        self.assertLess(items[0]["position"][2], 15.0)

    def test_water_lake_avoids_road_corridor(self):
        elevs = np.full((50, 50), 10.0, dtype=np.float32)
        proc = HeightmapProcessor(elevs, square_size=1.0)
        specs = proc.compute_specs()

        origin_lat, origin_lon = 43.0, 39.0
        r_p0 = (origin_lat, origin_lon)
        r_p1 = meters_to_lat_lon(50.0, 50.0, origin_lat, origin_lon)
        road = RoadSegment(osm_id=1, highway_type="primary", nodes=[r_p0, r_p1], width=10.0)
        exclusion = SpatialExclusionEngine([road], origin_lat, origin_lon)

        wb = WaterBuilder(heightmap=proc, origin_lat=origin_lat, origin_lon=origin_lon, specs=specs, exclusion=exclusion)
        # Lake completely on road corridor
        d_p0 = (origin_lat, origin_lon)
        d_p1 = meters_to_lat_lon(2.0, 0.0, origin_lat, origin_lon)
        d_p2 = meters_to_lat_lon(2.0, 2.0, origin_lat, origin_lon)
        d_p3 = meters_to_lat_lon(0.0, 2.0, origin_lat, origin_lon)

        items = wb.generate_water_items([[d_p0, d_p1, d_p2, d_p3]])
        self.assertEqual(len(items), 0)


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
            self.assertEqual(lamp["collisionType"], "Collision Mesh")
            self.assertEqual(lamp["decalType"], "Collision Mesh")
            # Lamp should be placed to the right (+X, East) of the road
            self.assertGreater(lamp["position"][0], 0.0)


class TestProceduralBuildings(unittest.TestCase):
    def test_clean_ring(self):
        # 1. Nearly collinear vertices on straight edge simplified with 0.08m tol
        ring = [(0, 0), (5, 0.02), (10, 0), (10, 10), (0, 10), (0, 0)]
        cleaned = clean_ring(ring, tol=0.08)
        self.assertIsNotNone(cleaned)
        self.assertEqual(len(cleaned), 4)

        # 2. Clockwise ring should be inverted to CCW
        cw_ring = [(0, 0), (0, 10), (10, 10), (10, 0)]
        ccw_cleaned = clean_ring(cw_ring)
        self.assertIsNotNone(ccw_cleaned)
        # Compute signed area
        n = len(ccw_cleaned)
        area2 = sum(ccw_cleaned[i][0]*ccw_cleaned[(i+1)%n][1] - ccw_cleaned[(i+1)%n][0]*ccw_cleaned[i][1] for i in range(n))
        self.assertGreater(area2, 0)

        # 3. Tiny polygon should be rejected (< 12 m2)
        tiny_ring = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertIsNone(clean_ring(tiny_ring))

        # 4. Real 90-degree corner indent (0.3m setback) must NOT be cut with tol=0.08
        corner_ring = [(0, 0), (5, 0), (5, 0.3), (5.3, 0.3), (5.3, 10), (0, 10)]
        cleaned_corner = clean_ring(corner_ring, tol=0.08)
        self.assertIsNotNone(cleaned_corner)
        self.assertEqual(len(cleaned_corner), 6)

    def test_is_convex_quad(self):
        # 1. Rectangle
        rect = [(0, 0), (10, 0), (10, 8), (0, 8)]
        self.assertTrue(is_convex_quad(rect))

        # 2. Trapezoid
        trap = [(0, 0), (10, 0), (8, 6), (2, 6)]
        self.assertTrue(is_convex_quad(trap))

        # 3. Boomerang / reflex corner (concave 4-gon)
        boomerang = [(0, 0), (10, 0), (4, 4), (0, 10)]
        self.assertFalse(is_convex_quad(boomerang))

        # 4. L-shape (6 vertices)
        l_shape = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
        self.assertFalse(is_convex_quad(l_shape))

        # 5. Triangle (3 vertices)
        tri = [(0, 0), (10, 0), (5, 5)]
        self.assertFalse(is_convex_quad(tri))

    def test_triangulate(self):
        # Convex box
        box = [(0, 0), (10, 0), (10, 10), (0, 10)]
        tris = triangulate(box)
        self.assertEqual(len(tris), 2)

        # L-shape concave
        l_shape = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
        tris_l = triangulate(l_shape)
        self.assertEqual(len(tris_l), 4)

    def test_building_exporter_sector_and_skirt(self):
        res = 65
        elevs = np.zeros((res, res), dtype=np.float32)
        # Slope from 10m to 20m
        for r in range(res):
            elevs[r, :] = 10.0 + (10.0 * r / (res - 1))
        proc = HeightmapProcessor(elevs, square_size=2.0)

        origin_lat, origin_lon = 43.4057, 39.9572
        # Real footprint coords (around origin)
        p0 = (origin_lat, origin_lon)
        p1 = (origin_lat, origin_lon + 0.0002)
        p2 = (origin_lat + 0.00015, origin_lon + 0.0002)
        p3 = (origin_lat + 0.00015, origin_lon)
        poly = [p0, p1, p2, p3]

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = pathlib.Path(tmp_dir) / "art" / "shapes" / "buildings"
            exporter = BuildingExporter(
                heightmap=proc,
                level_name="test_map",
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                output_dir=out_dir,
            )
            items = exporter.export_buildings([poly])
            self.assertEqual(len(items), 1)

            item = items[0]
            self.assertEqual(item["class"], "TSStatic")
            self.assertEqual(item["collisionType"], "Collision Mesh")
            self.assertEqual(item["decalType"], "Collision Mesh")
            self.assertTrue(item["prebuildCollisionData"])
            self.assertIn("bld_sector_", item["shapeName"])

            # Check exported DAE
            dae_files = list(out_dir.glob("bld_sector_*.dae"))
            self.assertEqual(len(dae_files), 1)

            tree = ET.parse(dae_files[0])
            ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}

            # Validate up_axis
            up_axis = tree.find(".//c:up_axis", ns)
            self.assertEqual(up_axis.text, "Z_UP")

            # Validate geometry has both Building-mesh and Colmesh-mesh
            geom_ids = [g.attrib.get("id") for g in tree.findall(".//c:geometry", ns)]
            self.assertIn("Building-mesh", geom_ids)
            self.assertIn("Colmesh-mesh", geom_ids)

            # Validate Torque3D collision node hierarchy: base00 -> start01 -> Colmesh-1
            col_node = tree.find(".//c:node[@id='base00']/c:node[@id='start01']/c:node[@id='Colmesh-1']", ns)
            self.assertIsNotNone(col_node)
            self.assertEqual(col_node.attrib.get("name"), "Colmesh-1")

            visual_node = tree.find(".//c:node[@id='base00']/c:node[@id='start01']/c:node[@id='BuildingNode']", ns)
            self.assertIsNotNone(visual_node)

            # Check materials include facade_plaster and roof_gravel
            mat_ids = [m.attrib.get("id") for m in tree.findall(".//c:material", ns)]
            self.assertIn("facade_plaster-mat", mat_ids)

            # Check that foundation skirt goes down to min_elevation - 0.5m
            pos_node = tree.find(".//c:geometry[@id='Building-mesh']//c:source[@id='Building-pos']//c:float_array", ns)
            pos_floats = [float(x) for x in pos_node.text.strip().split()]
            zs = pos_floats[2::3]
            min_local_z = min(zs)
            global_min_z = min_local_z + item["position"][2]
            # Heightmap around origin has z_min=15.0m, skirt reaches z_min - 0.5m = 14.5m
            self.assertAlmostEqual(global_min_z, 14.5, places=1)

    def test_building_pitched_and_flat_roofs(self):
        from exporter.building_mesh import ProceduralBuildingMesh, write_sector_dae

        # 1. House with pitched/gabled roof (convex 4-gon)
        house_mesh = ProceduralBuildingMesh()
        rect_ring = [(-6.0, -4.0), (6.0, -4.0), (6.0, 4.0), (-6.0, 4.0)]
        house_mesh.extrude_building(
            ring=rect_ring,
            base_z=10.0,
            z_base=9.5,
            z_eave=16.0,
            floors=2,
            floor_h=3.0,
            band_idx=2,
            is_house=True,
        )
        # Should have roof_tiles for pitched roof
        self.assertGreater(len(house_mesh.triangles_by_mat.get("roof_tiles", [])), 0)
        # Ridge must be elevated above z_eave (16.0m)
        max_z = max(v[2] for v in house_mesh.verts)
        self.assertGreater(max_z, 17.5)

        # 2. High-rise / office with flat gravel roof and parapet
        office_mesh = ProceduralBuildingMesh()
        office_mesh.extrude_building(
            ring=rect_ring,
            base_z=10.0,
            z_base=9.5,
            z_eave=28.0,
            floors=6,
            floor_h=3.0,
            band_idx=0,
            is_house=False,
        )
        # Should have roof_gravel
        self.assertGreater(len(office_mesh.triangles_by_mat.get("roof_gravel", [])), 0)
        # Parapet height ~0.35m
        max_office_z = max(v[2] for v in office_mesh.verts)
        self.assertAlmostEqual(max_office_z, 28.35, places=2)

        # 3. L-shaped house (concave, N=6) must strictly use flat roof + parapet (no wigwam/peaks!)
        l_mesh = ProceduralBuildingMesh()
        l_ring = [(-6.0, -4.0), (6.0, -4.0), (6.0, 0.0), (0.0, 0.0), (0.0, 4.0), (-6.0, 4.0)]
        l_mesh.extrude_building(
            ring=l_ring,
            base_z=10.0,
            z_base=9.5,
            z_eave=16.0,
            floors=2,
            floor_h=3.0,
            band_idx=2,
            is_house=True,
        )
        # Should NOT have roof_tiles or sharp ridge peak!
        self.assertEqual(len(l_mesh.triangles_by_mat.get("roof_tiles", [])), 0)
        self.assertGreater(len(l_mesh.triangles_by_mat.get("roof_gravel", [])), 0)
        # Peak must NOT exceed eave + parapet (16.35m), strictly no wigwam
        max_l_z = max(v[2] for v in l_mesh.verts)
        self.assertLessEqual(max_l_z, 16.5)

        # 4. Verify UV coordinates are valid non-zero numbers
        for u, v in house_mesh.uvs:
            self.assertFalse(math.isnan(u) or math.isnan(v))
            self.assertFalse(math.isinf(u) or math.isinf(v))

        # 5. Verify DAE generation with set="0" on TEXCOORD and Colmesh-1 node
        with tempfile.TemporaryDirectory() as tmp_dir:
            dae_path = pathlib.Path(tmp_dir) / "test_roof.dae"
            write_sector_dae(dae_path, house_mesh, sector_origin=(0.0, 0.0, 10.0))
            self.assertTrue(dae_path.exists())
            tree = ET.parse(dae_path)
            ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
            tex_input = tree.find(".//c:triangles//c:input[@semantic='TEXCOORD']", ns)
            self.assertIsNotNone(tex_input)
            self.assertEqual(tex_input.attrib.get("set"), "0")

            col_input = tree.find(".//c:node[@id='base00']/c:node[@id='start01']/c:node[@id='Colmesh-1']", ns)
            self.assertIsNotNone(col_input)


class TestPhysicsAndCollision(unittest.TestCase):
    def test_spawn_point_height_offset(self):
        from exporter.level_builder import LevelBuilder
        from core.config import MapConfig
        cfg = MapConfig(title="Test", level_name="test_spawn", size_meters=256.0)
        builder = LevelBuilder(cfg)

        elevs = np.full((129, 129), 25.0, dtype=np.float32)
        proc = HeightmapProcessor(elevs, square_size=2.0)

        # 1. Fallback spawn height (+1.5m above terrain)
        osm_empty = OSMData(roads=[], buildings=[])
        sx, sy, sz = builder._find_spawn_point(osm_empty, proc)
        self.assertAlmostEqual(sz, 26.5, places=2)

        # 2. Road spawn height (+1.5m above road)
        r0 = (cfg.center_lat, cfg.center_lon)
        r1 = meters_to_lat_lon(10.0, 0.0, cfg.center_lat, cfg.center_lon)
        road = RoadSegment(osm_id=10, highway_type="primary", nodes=[r0, r1])
        osm_road = OSMData(roads=[road], buildings=[])
        rx, ry, rz = builder._find_spawn_point(osm_road, proc)
        self.assertAlmostEqual(rz, 26.5, places=2)

    def test_depth_map_value_solid_255(self):
        from PIL import Image
        from exporter.level_builder import LevelBuilder
        from core.config import MapConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MapConfig(
                title="Test",
                level_name="test_depth",
                size_meters=128.0,
                output_dir=pathlib.Path(tmpdir),
                install_to_beamng=False,
            )
            builder = LevelBuilder(cfg)
            elevs = np.zeros((65, 65), dtype=np.float32)
            proc = HeightmapProcessor(elevs, square_size=2.0)
            specs = proc.compute_specs()
            osm_data = OSMData(roads=[], buildings=[])
            exclusion = SpatialExclusionEngine([], cfg.center_lat, cfg.center_lon)

            builder.build_level(proc, specs, osm_data, exclusion)

            depth_file = builder.level_dir / "theTerrain.ter.depth.png"
            self.assertTrue(depth_file.exists())
            with Image.open(depth_file) as d_img:
                self.assertEqual(d_img.mode, "L")
                self.assertEqual(d_img.size, (64, 64))
                extrema = d_img.getextrema()
                # Entire depth map must be 255 (0 mud depth = solid monolithic ground)
                self.assertEqual(extrema, (255, 255))

    def test_terrain_block_max_height_and_file(self):
        import json
        from exporter.level_builder import LevelBuilder
        from core.config import MapConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MapConfig(
                title="Test TerrainBlock",
                level_name="test_tb",
                size_meters=128.0,
                output_dir=pathlib.Path(tmpdir),
                install_to_beamng=False,
            )
            builder = LevelBuilder(cfg)
            elevs = np.zeros((65, 65), dtype=np.float32)
            elevs[0, 0] = 50.0  # span 50m
            proc = HeightmapProcessor(elevs, square_size=2.0)
            specs = proc.compute_specs()
            osm_data = OSMData(roads=[], buildings=[])
            exclusion = SpatialExclusionEngine([], cfg.center_lat, cfg.center_lon)

            builder.build_level(proc, specs, osm_data, exclusion)

            # Check items.level.json
            items_file = builder.level_dir / "main" / "MissionGroup" / "items.level.json"
            self.assertTrue(items_file.exists())
            terrain_item = None
            with open(items_file, "r", encoding="utf-8") as f:
                for line in f:
                    obj = json.loads(line)
                    if obj.get("name") == "theTerrain":
                        terrain_item = obj
                        break

            self.assertIsNotNone(terrain_item)
            self.assertEqual(terrain_item.get("terrainFile"), f"/levels/{cfg.level_name}/theTerrain.ter")
            self.assertAlmostEqual(terrain_item.get("maxHeight"), specs.height_scale, places=6)
            self.assertTrue(terrain_item.get("hasCollision"))
            self.assertEqual(terrain_item.get("collisionType"), "Collision Mesh")

            # Check main.level.json
            main_file = builder.level_dir / "main.level.json"
            self.assertTrue(main_file.exists())
            with open(main_file, "r", encoding="utf-8") as f:
                main_json = json.load(f)
            level_objs = main_json["childs"][0]["childs"]
            main_terrain = next(item for item in level_objs if item.get("name") == "theTerrain")
            self.assertEqual(main_terrain.get("terrainFile"), f"/levels/{cfg.level_name}/theTerrain.ter")
            self.assertAlmostEqual(main_terrain.get("maxHeight"), specs.height_scale, places=6)
            self.assertTrue(main_terrain.get("hasCollision"))
            self.assertEqual(main_terrain.get("collisionType"), "Collision Mesh")

    def test_exclusion_building_clipping(self):
        from processing.exclusion import SpatialExclusionEngine
        from fetchers.osm import BuildingPolygon, RoadSegment
        from core.projection import meters_to_lat_lon

        origin_lat, origin_lon = 55.75, 37.62
        r0 = meters_to_lat_lon(0.0, -100.0, origin_lat, origin_lon)
        r1 = meters_to_lat_lon(0.0, 100.0, origin_lat, origin_lon)
        road = RoadSegment(osm_id=1, highway_type="primary", nodes=[r0, r1], width=10.0)
        exclusion = SpatialExclusionEngine([road], origin_lat, origin_lon, clearance_meters=0.8, min_building_area_sqm=12.0)

        # 1. Clear building away from road
        b_clear = [
            meters_to_lat_lon(20.0, 10.0, origin_lat, origin_lon),
            meters_to_lat_lon(30.0, 10.0, origin_lat, origin_lon),
            meters_to_lat_lon(30.0, 20.0, origin_lat, origin_lon),
            meters_to_lat_lon(20.0, 20.0, origin_lat, origin_lon),
        ]

        # 2. Overlapping road: clipped and preserved
        b_overlap = [
            meters_to_lat_lon(4.0, 30.0, origin_lat, origin_lon),
            meters_to_lat_lon(15.0, 30.0, origin_lat, origin_lon),
            meters_to_lat_lon(15.0, 40.0, origin_lat, origin_lon),
            meters_to_lat_lon(4.0, 40.0, origin_lat, origin_lon),
        ]

        # 3. Completely inside road
        b_on_road = [
            meters_to_lat_lon(-2.0, 50.0, origin_lat, origin_lon),
            meters_to_lat_lon(2.0, 50.0, origin_lat, origin_lon),
            meters_to_lat_lon(2.0, 55.0, origin_lat, origin_lon),
            meters_to_lat_lon(-2.0, 55.0, origin_lat, origin_lon),
        ]

        # 4. Tiny (< 12 sqm)
        b_tiny = [
            meters_to_lat_lon(40.0, 0.0, origin_lat, origin_lon),
            meters_to_lat_lon(42.0, 0.0, origin_lat, origin_lon),
            meters_to_lat_lon(42.0, 2.0, origin_lat, origin_lon),
            meters_to_lat_lon(40.0, 2.0, origin_lat, origin_lon),
        ]

        result = exclusion.filter_buildings([b_clear, b_overlap, b_on_road, b_tiny])
        self.assertEqual(len(result), 2)


class TestForestBuilder(unittest.TestCase):
    def setUp(self):
        self.center_lat = 43.58
        self.center_lon = 39.72
        elevs = np.zeros((65, 65), dtype=np.float32)
        self.heightmap = HeightmapProcessor(elevs, square_size=2.0)
        self.exclusion = SpatialExclusionEngine([], self.center_lat, self.center_lon)

    def test_default_tree_models_library(self):
        from exporter.forest_builder import DEFAULT_TREE_MODELS
        shape_files = {v["shapeFile"] for v in DEFAULT_TREE_MODELS.values()}
        required_shapes = [
            "assets/meshes/foliage/trees_library/oak/tree_oak_large_a.dae",
            "assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae",
            "assets/meshes/foliage/trees_library/beech/tree_beech_large_b.dae",
            "assets/meshes/foliage/trees_library/birch/tree_aspen_large_a.dae",
            "assets/meshes/foliage/trees_library/cork_oak/cork_oak_bush_large.dae",
        ]
        for shape in required_shapes:
            self.assertIn(shape, shape_files, f"Expected shapeFile {shape} in DEFAULT_TREE_MODELS")

    def test_street_tree_exclusions(self):
        # Excluded types like motorway, raceway, track, links must never spawn street trees
        for hw_type in ["motorway", "trunk", "raceway", "track", "primary_link", "motorway_link", "trunk_link"]:
            with tempfile.TemporaryDirectory() as tmpdir:
                level_dir = pathlib.Path(tmpdir)
                fb = ForestBuilder("test_level", self.center_lat, self.center_lon, self.heightmap, self.exclusion, 1000.0)
                r0 = (self.center_lat, self.center_lon)
                r1 = meters_to_lat_lon(0.0, 150.0, self.center_lat, self.center_lon)
                road = RoadSegment(osm_id=1, highway_type=hw_type, nodes=[r0, r1])
                osm_data = OSMData(roads=[road], buildings=[], forests=[])
                fb.generate_forest(osm_data, level_dir)

                with open(level_dir / "test_level.forest.json", "r", encoding="utf-8") as f:
                    forest_data = json.load(f)
                total_instances = sum(len(instances) for instances in forest_data["instances"].values())
                self.assertEqual(total_instances, 0, f"Expected 0 trees for highway_type={hw_type}")

    def test_street_tree_urban_generation_and_jitter(self):
        # Urban residential street should spawn green trees with jitter, no orange aspen
        with tempfile.TemporaryDirectory() as tmpdir:
            level_dir = pathlib.Path(tmpdir)
            fb = ForestBuilder("test_level", self.center_lat, self.center_lon, self.heightmap, self.exclusion, 1000.0)
            r0 = (self.center_lat, self.center_lon)
            r1 = meters_to_lat_lon(0.0, 200.0, self.center_lat, self.center_lon)
            road = RoadSegment(osm_id=2, highway_type="residential", nodes=[r0, r1])
            osm_data = OSMData(roads=[road], buildings=[], forests=[])
            fb.generate_forest(osm_data, level_dir)

            with open(level_dir / "test_level.forest.json", "r", encoding="utf-8") as f:
                forest_data = json.load(f)

            # Never spawn orange aspen on streets
            self.assertEqual(len(forest_data["instances"]["tree_aspen_large"]), 0)

            # Green trees spawned
            green_counts = {
                k: len(v) for k, v in forest_data["instances"].items()
                if k in ["tree_oak_large", "tree_oak_small", "tree_beech_large_b", "tree_beech_large_c"]
            }
            total_green = sum(green_counts.values())
            self.assertGreater(total_green, 0, "Urban road should spawn green street trees")

            # Modern BeamNG NDJSON v4 files created in forest/
            forest_dir = level_dir / "forest"
            self.assertTrue(forest_dir.exists())
            f4_files = list(forest_dir.glob("*.forest4.json"))
            self.assertGreater(len(f4_files), 0, "Modern BeamNG .forest4.json files must be generated")

            # Check organic jitter (perpendicular and step positions vary)
            all_pts = []
            for k, instances in forest_data["instances"].items():
                if k != "bush_large":
                    all_pts.extend(instances)
            x_coords = [p[0] for p in all_pts]
            # Since road is along Y axis (x=0), street trees are displaced along X (nx = +-1)
            # Jitter means absolute X values shouldn't be strictly identical
            unique_abs_x = len(set(round(abs(x), 2) for x in x_coords))
            self.assertGreater(unique_abs_x, 1, "Expected jitter to create variations in road offset")


if __name__ == "__main__":
    unittest.main()
