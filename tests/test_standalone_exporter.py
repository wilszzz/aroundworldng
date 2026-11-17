"""Tests for AroundWorldNG Standalone Level Exporter."""
import json
import sys
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'aroundworldng'))

import export_standalone


class TestStandaloneExporter(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(export_standalone.slugify('Кудрово (СПб)'), 'kudrovo_spb')
        self.assertEqual(export_standalone.slugify('Москва-Сити'), 'moskva_siti')
        self.assertEqual(export_standalone.slugify('Paris Downtown!'), 'paris_downtown')
        self.assertEqual(export_standalone.slugify('Мой Город #1'), 'moy_gorod_1')

    def test_write_ter_bytes(self):
        import numpy as np
        h = np.zeros((1024, 1024), dtype='<u2')
        data = export_standalone.write_ter_bytes(h, materials=('Grass', 'BeachSand', 'dirt_rocky_large', 'rock'))
        # 1 byte ver + 4 bytes size + 2MB height + 1MB layermap + 4 bytes count + mats (30B) = 3145775
        self.assertEqual(len(data), 3145775)
        self.assertEqual(data[0], 9)  # version 9

    def test_collada_dae_generation(self):
        buildings = [{
            'rings': [[(0, 0, 10), (20, 0, 10), (20, 15, 10), (0, 15, 10), (0, 0, 10)]],
            'height': 12.0
        }]
        dae_xml = export_standalone.generate_collada_dae(buildings)
        self.assertIn('<COLLADA', dae_xml)
        self.assertIn('bld_geom', dae_xml)
        self.assertIn('triangles', dae_xml)
        self.assertIn('</COLLADA>', dae_xml)

    def test_road_markings_integration(self):
        self.assertTrue(hasattr(export_standalone, 'road_markings'))

    def test_road_material_selection(self):
        # 1. Paved two-way road
        mat = export_standalone.choose_road_material({'highway': 'primary', 'lanes': '2'})
        self.assertEqual(mat, 'AsphaltRoad_variation_two_way')

        # 2. Motorway one-way
        mat = export_standalone.choose_road_material({'highway': 'motorway', 'oneway': 'yes', 'lanes': '3'})
        self.assertEqual(mat, 'AsphaltRoad_variation_one_way')

        # 3. Unpaved dirt road
        mat = export_standalone.choose_road_material({'highway': 'track', 'surface': 'dirt'})
        self.assertIn(mat, ('dirt_tiretracks', 'DirtRoad_variation_01_d'))

        # 4. Gravel road
        mat = export_standalone.choose_road_material({'highway': 'unclassified', 'surface': 'gravel'})
        self.assertEqual(mat, 'dirt_road_gravels')

        # 5. Service / alley
        mat = export_standalone.choose_road_material({'highway': 'service'})
        self.assertEqual(mat, 'DefaultDecalRoadMaterial')

        # 6. Cobblestone / sett
        mat = export_standalone.choose_road_material({'highway': 'secondary', 'surface': 'cobblestone'})
        self.assertEqual(mat, 'm_asphalt_damaged_01_east_coast_usa')

    def test_road_width_and_resampling(self):
        import road_markings
        # Test width parsing
        w1 = road_markings.calculate_road_width({'width': '7.5 m'})
        self.assertEqual(w1, 7.5)

        w2 = road_markings.calculate_road_width({'highway': 'motorway', 'lanes': '3'})
        self.assertEqual(w2, 11.25)

        w3 = road_markings.calculate_road_width({'highway': 'track'})
        self.assertEqual(w3, 3.0)

        # Mock terrain: flat at z=20.0
        class MockTerrain:
            def sample(self, pts):
                return [20.0] * len(pts)

        # Polyline with micro-step (0.5m) and long span (45m)
        raw_pts = [[0.0, 0.0], [0.5, 0.0], [45.0, 0.0]]
        nodes = road_markings.resample_polyline_3d(
            pts_2d=raw_pts,
            store_terrain=MockTerrain(),
            width=6.0,
            tags={'highway': 'residential'},
            target_spacing=10.0,
            min_dist=1.2,
            z_offset=0.18
        )
        # 0.5m step should be pruned; 45m span should be subdivided into ~5 segments
        self.assertGreaterEqual(len(nodes), 5)
        # Verify Z offset is exactly +0.18m (20.0 + 0.18 = 20.18)
        for n in nodes:
            self.assertAlmostEqual(n[2], 20.18, places=2)
            self.assertEqual(n[3], 6.0)

    def test_decal_road_mandatory_fields_and_map_json(self):
        import road_markings

        class MockTerrain:
            def sample(self, pts):
                return [15.0] * len(pts)

        raw_roads = [
            {
                'id': 101,
                'tags': {'highway': 'secondary', 'lanes': '2'},
                'xy': [[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]],
                'width': 6.5
            },
            {
                'id': 102,
                'tags': {'highway': 'residential'},
                'xy': [[50.0, 0.0], [50.0, 30.0]],
                'width': 5.5
            }
        ]

        result = road_markings.process_roads_and_markings(
            raw_roads=raw_roads,
            store_terrain=MockTerrain(),
            material_selector=export_standalone.choose_road_material
        )

        self.assertGreater(len(result.base_roads), 0)
        for road_obj in result.base_roads:
            self.assertIn('position', road_obj)
            self.assertEqual(road_obj['position'], [round(road_obj['nodes'][0][0], 2),
                                                    round(road_obj['nodes'][0][1], 2),
                                                    round(road_obj['nodes'][0][2], 2)])
            self.assertTrue(road_obj.get('overObjects'))
            self.assertEqual(road_obj.get('renderPriority'), 10)
            self.assertTrue(road_obj.get('improvedSpline'))
            self.assertEqual(road_obj.get('breakAngle'), 3.0)

        # Test map.json generation for in-game radar
        map_json = road_markings.generate_navigation_map(
            raw_roads=raw_roads,
            base_roads=result.base_roads
        )
        self.assertIn('nodes', map_json)
        self.assertIn('segments', map_json)
        self.assertGreater(len(map_json['nodes']), 0)
        self.assertGreater(len(map_json['segments']), 0)

        # Verify a node has pos, radius, and links
        sample_node = next(iter(map_json['nodes'].values()))
        self.assertIn('pos', sample_node)
        self.assertEqual(len(sample_node['pos']), 3)
        self.assertIn('radius', sample_node)
        self.assertIn('links', sample_node)


if __name__ == '__main__':
    unittest.main()
