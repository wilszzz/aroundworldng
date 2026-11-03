"""
Tests for standalone resource path resolution and main entry point.
"""

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from core.config import get_resource_path
import main


class TestStandaloneResources(unittest.TestCase):
    def test_resource_paths_in_dev_mode(self):
        """Ensure all required bundled resources exist and resolve in dev mode."""
        terrain_mats = get_resource_path("exporter/terrain_materials.json")
        road_mats = get_resource_path("exporter/road_materials.json")
        tree_mats = get_resource_path("exporter/tree_materials.json")
        ui_index = get_resource_path("ui/index.html")
        ui_dir = get_resource_path("ui")

        self.assertTrue(terrain_mats.exists(), f"Missing {terrain_mats}")
        self.assertTrue(road_mats.exists(), f"Missing {road_mats}")
        self.assertTrue(tree_mats.exists(), f"Missing {tree_mats}")
        self.assertTrue(ui_index.exists(), f"Missing {ui_index}")
        self.assertTrue(ui_dir.exists(), f"Missing {ui_dir}")

    def test_resource_paths_with_meipass(self):
        """Simulate PyInstaller bundled execution with sys._MEIPASS (--onefile)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            fake_exporter = tmp_path / "exporter"
            fake_exporter.mkdir()
            fake_road = fake_exporter / "road_materials.json"
            fake_road.write_text("{}", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
                    resolved = get_resource_path("exporter/road_materials.json")
                    self.assertEqual(resolved, fake_road)
                    self.assertTrue(resolved.exists())

    def test_resource_paths_with_onedir_internal(self):
        """Simulate PyInstaller --onedir mode where resources are in _internal subdir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            fake_exe = tmp_path / "AroundWorldNG.exe"
            fake_exe.touch()
            internal_dir = tmp_path / "_internal"
            fake_ui_dir = internal_dir / "ui"
            fake_ui_dir.mkdir(parents=True)
            fake_index = fake_ui_dir / "index.html"
            fake_index.write_text("<html></html>", encoding="utf-8")

            # In --onedir, sys._MEIPASS is not set, sys.frozen is True
            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(fake_exe)):
                    if hasattr(sys, "_MEIPASS"):
                        delattr(sys, "_MEIPASS")
                    resolved_index = get_resource_path("ui/index.html")
                    resolved_ui = get_resource_path("ui")
                    self.assertEqual(resolved_index, fake_index)
                    self.assertTrue(resolved_index.exists())
                    self.assertEqual(resolved_ui, fake_ui_dir)
                    self.assertTrue(resolved_ui.exists())

    def test_resource_paths_with_onedir_flat(self):
        """Simulate PyInstaller --onedir mode where resources are next to executable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            fake_exe = tmp_path / "AroundWorldNG.exe"
            fake_exe.touch()
            fake_exporter = tmp_path / "exporter"
            fake_exporter.mkdir()
            fake_mats = fake_exporter / "terrain_materials.json"
            fake_mats.write_text("{}", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(fake_exe)):
                    if hasattr(sys, "_MEIPASS"):
                        delattr(sys, "_MEIPASS")
                    resolved = get_resource_path("exporter/terrain_materials.json")
                    self.assertEqual(resolved, fake_mats)
                    self.assertTrue(resolved.exists())

    @patch("builtins.input", return_value="")
    @patch("ui.web_server.start_web_ui", side_effect=RuntimeError("Test crash"))
    def test_main_exception_handling_prompts_user(self, mock_web_ui, mock_input):
        """Ensure fatal exceptions in main are caught, input() is called, and sys.exit(1) is invoked."""
        with patch.object(sys, "argv", ["AroundWorldNG.exe"]):
            with self.assertRaises(SystemExit) as ctx:
                main.main()
            self.assertEqual(ctx.exception.code, 1)
            mock_input.assert_called_once()

    @patch("ui.web_server.start_web_ui")
    def test_main_no_args_launches_web_ui(self, mock_web_ui):
        """When launched without arguments (e.g. double clicking exe), start web UI."""
        with patch.object(sys, "argv", ["AroundWorldNG.exe"]):
            main.main()
            mock_web_ui.assert_called_once()

    @patch("generator.AroundWorldGenerator.generate")
    def test_main_cli_args_launches_generator(self, mock_generate):
        """When CLI arguments are passed, run generator for specified coordinates."""
        test_args = [
            "AroundWorldNG.exe",
            "--lat", "43.585",
            "--lon", "39.720",
            "--name", "sochi_test",
            "--size", "2048",
        ]
        with patch.object(sys, "argv", test_args):
            main.main()
            mock_generate.assert_called_once()
