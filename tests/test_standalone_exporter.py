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


if __name__ == '__main__':
    unittest.main()
