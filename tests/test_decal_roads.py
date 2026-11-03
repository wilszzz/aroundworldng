"""
Unit tests for DecalRoad and MeshRoad exporter.
"""

import unittest
import numpy as np

from fetchers.osm import RoadSegment
from processing.heightmap import HeightmapProcessor
from exporter.decal_roads import RoadExporter, get_road_look, resample_polyline


class TestDecalRoads(unittest.TestCase):
    def setUp(self):
        # 100x100 elevation grid, constant 15.0m
        self.elevs = np.full((100, 100), 15.0, dtype=np.float32)
        self.proc = HeightmapProcessor(self.elevs, square_size=1.0)
        self.origin_lat = 43.4057
        self.origin_lon = 39.9572
        self.exporter = RoadExporter(
            heightmap_processor=self.proc,
            origin_lat=self.origin_lat,
            origin_lon=self.origin_lon,
            z_offset=0.05,
            size_meters=1000.0,
        )

    def test_materials_and_properties(self):
        # Dirt road
        mat, tl, rp = get_road_look("dirt", "track", 4.0)
        self.assertEqual(mat, "road_dirt")
        self.assertEqual(tl, 40.0)
        self.assertEqual(rp, 20)

        # 2-lane major highway
        mat, tl, rp = get_road_look("asphalt", "primary", 8.0)
        self.assertEqual(mat, "road_asphalt_2lane")
        self.assertEqual(tl, 11.0)
        self.assertEqual(rp, 20)

        # Narrow single lane service road
        mat, tl, rp = get_road_look("asphalt", "service", 3.5)
        self.assertEqual(mat, "road_asphalt")
        self.assertEqual(tl, 12.0)
        self.assertEqual(rp, 20)

    def test_node_resampling(self):
        # 100 meter straight line between (0, 0) and (100, 0)
        pts = [(0.0, 0.0), (100.0, 0.0)]
        resampled = resample_polyline(pts, target_step=10.0)
        
        # Verify that distance between any consecutive pair is between 8 and 12 meters
        for i in range(1, len(resampled)):
            dist = np.hypot(resampled[i][0] - resampled[i-1][0], resampled[i][1] - resampled[i-1][1])
            self.assertGreaterEqual(dist, 8.0)
            self.assertLessEqual(dist, 12.0)

    def test_export_roads_with_markings(self):
        # Primary highway ~100m long
        # lat 43.4057, lon 39.9572 is (0, 0)
        # lat 43.4066 is ~100m North
        nodes = [(43.4057, 39.9572), (43.4066, 39.9572)]
        road = RoadSegment(
            osm_id=12345,
            highway_type="primary",
            nodes=nodes,
            lanes=2,
            width=8.0,
            surface="asphalt",
        )

        items = self.exporter.export_roads([road])
        
        # Should generate 2 items: main road DecalRoad + marking DecalRoad
        self.assertEqual(len(items), 2)

        main_road = items[0]
        self.assertEqual(main_road["class"], "DecalRoad")
        self.assertEqual(main_road["material"], "road_asphalt_2lane")
        self.assertEqual(main_road["renderPriority"], 20)
        self.assertEqual(main_road["textureLength"], 11.0)
        self.assertTrue(main_road["improvedSpline"])
        self.assertTrue(main_road["overObjects"])
        self.assertEqual(main_road["detail"], 0.2)
        self.assertEqual(main_road["drivability"], 1)

        # Elevation check (15.0 + 0.05 = 15.05)
        for node in main_road["nodes"]:
            self.assertAlmostEqual(node[2], 15.05, places=2)
            self.assertEqual(node[3], 8.0)

        # Marking road check
        marking = items[1]
        self.assertEqual(marking["class"], "DecalRoad")
        self.assertEqual(marking["material"], "line_white")
        self.assertEqual(marking["renderPriority"], 22)
        self.assertEqual(marking["textureLength"], 8.0)
        self.assertTrue(marking["overObjects"])
        self.assertTrue(marking["improvedSpline"])
        self.assertEqual(marking["detail"], 0.2)
        self.assertEqual(marking["drivability"], 1)

        for node in marking["nodes"]:
            self.assertAlmostEqual(node[2], 15.05, places=2)
            self.assertEqual(node[3], 0.25)


if __name__ == "__main__":
    unittest.main()
