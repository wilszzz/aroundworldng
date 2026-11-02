"""
BeamNG Level Builder and Packager.
Assembles the complete mod folder and produces a ready-to-play .zip mod archive
compatible with BeamNG.drive 0.3x and 0.4x.
"""

import json
import os
import pathlib
import shutil
from typing import Any, Dict, List, Optional, Tuple
import uuid
import zipfile
from PIL import Image

from core.config import MapConfig, get_default_beamng_mods_dir
from core.projection import lat_lon_to_meters
from exporter.decal_roads import RoadExporter
from exporter.forest import ForestExporter
from fetchers.osm import OSMData
from processing.exclusion import SpatialExclusionEngine
from processing.heightmap import HeightmapProcessor, TerrainSpecs


class LevelBuilder:
    """Assembles all components into a complete BeamNG.drive level mod."""

    def __init__(self, config: MapConfig):
        self.cfg = config
        self.level_dir = self.cfg.output_dir / self.cfg.level_name

    def build_level(
        self,
        heightmap_proc: HeightmapProcessor,
        terrain_specs: TerrainSpecs,
        osm_data: OSMData,
        exclusion: SpatialExclusionEngine,
        sat_image: Optional[Image.Image] = None,
    ) -> pathlib.Path:
        """Constructs full level structure and returns path to mod directory or zip."""
        if self.level_dir.exists():
            shutil.rmtree(self.level_dir)
        self.level_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[LevelBuilder] Assembling level '{self.cfg.level_name}'...")

        # 1. Export 16-bit Heightmap and Native Torque3D .ter binary
        terrain_dir = self.level_dir / "terrain"
        terrain_dir.mkdir(exist_ok=True)
        heightmap_png_path = terrain_dir / "heightmap.png"
        heightmap_proc.export_16bit_png(heightmap_png_path)
        
        # Export binary .ter for instant physical collision in BeamNG
        ter_path = self.level_dir / "theTerrain.ter"
        heightmap_proc.export_binary_ter(ter_path)

        # Also save as theTerrain.terrainheightmap.png for BeamNG editor
        heightmap_proc.export_16bit_png(self.level_dir / "theTerrain.terrainheightmap.png")

        # 2. Export Satellite Texture and Preview
        art_dir = self.level_dir / "art" / "textures"
        art_dir.mkdir(parents=True, exist_ok=True)

        if sat_image:
            sat_path = art_dir / "satellite_ground.png"
            sat_image.save(sat_path, format="PNG")
            # Save 512x512 preview image for level selector
            preview_img = sat_image.resize((512, 512), Image.Resampling.LANCZOS)
            preview_img.save(self.level_dir / "info.png")
            print(f"[LevelBuilder] Saved satellite orthophoto & preview image.")

        # 3. Determine Player Spawn Point (On a real road near center)
        spawn_x, spawn_y, spawn_z = self._find_spawn_point(osm_data, heightmap_proc)

        # 4. Generate Road Splines (DecalRoad & MeshRoad)
        road_exporter = RoadExporter(
            heightmap_processor=heightmap_proc,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
        )
        road_items = road_exporter.export_roads(osm_data.roads) if self.cfg.generate_roads else []

        # 5. Generate Forest
        if self.cfg.generate_forest and osm_data.forests:
            forest_exporter = ForestExporter(
                heightmap=heightmap_proc,
                exclusion=exclusion,
                origin_lat=self.cfg.center_lat,
                origin_lon=self.cfg.center_lon,
            )
            forest_file = self.level_dir / "forest" / "managedData.json"
            forest_exporter.export_managed_data(forest_file, osm_data.forests)

        # 6. Generate Scene Files (main.level.json and main/items.level.json)
        self._write_scene_files(terrain_specs, road_items, spawn_x, spawn_y, spawn_z)

        # 7. Generate info.json (mod descriptor recognized by BeamNG UI)
        self._write_info_json(spawn_x, spawn_y, spawn_z)

        # 8. Pack into .zip mod archive with root 'levels/<level_name>/...'
        archive_path = self._package_mod()
        return archive_path

    def _find_spawn_point(
        self, osm_data: OSMData, heightmap: HeightmapProcessor
    ) -> Tuple[float, float, float]:
        """Finds a road point closest to map center for spawning."""
        best_pt = (self.cfg.size_meters / 2.0, self.cfg.size_meters / 2.0, 50.0)
        min_dist = float("inf")
        center_x = self.cfg.size_meters / 2.0
        center_y = self.cfg.size_meters / 2.0

        for road in osm_data.roads:
            if road.is_bridge or road.is_tunnel:
                continue
            for lat, lon in road.nodes:
                x, y = lat_lon_to_meters(lat, lon, self.cfg.center_lat, self.cfg.center_lon)
                dist = (x - center_x) ** 2 + (y - center_y) ** 2
                if dist < min_dist:
                    min_dist = dist
                    z = heightmap.get_elevation_at_meters(x, y) + 0.8
                    best_pt = (x, y, z)

        print(f"[LevelBuilder] Spawn point set at ({best_pt[0]:.1f}, {best_pt[1]:.1f}, {best_pt[2]:.1f})")
        return best_pt

    def _write_scene_files(
        self,
        specs: TerrainSpecs,
        road_items: List[Dict[str, Any]],
        spawn_x: float,
        spawn_y: float,
        spawn_z: float,
    ):
        """
        Writes main.level.json and main/items.level.json.
        Compatible with Torque3D MissionGroup hierarchy in BeamNG 0.3x - 0.4x.
        """
        # Child objects inside MissionGroup
        level_objects: List[Dict[str, Any]] = [
            {
                "class": "LevelInfo",
                "name": "theLevelInfo",
                "gravity": -9.81,
                "visibleDistance": 4500.0,
                "fogColor": [0.74, 0.81, 0.92, 1.0],
                "fogDensity": 0.0006,
                "canvasClearColor": "black",
            },
            {
                "class": "TimeOfDay",
                "name": "tod",
                "startTime": 0.35,
                "dayLength": 1200.0,
                "axisTilt": 23.44,
                "play": False,
            },
            {
                "class": "Sun",
                "name": "sun",
                "azimuth": 45.0,
                "elevation": 55.0,
                "color": [1.0, 0.98, 0.92, 1.0],
                "ambient": [0.35, 0.38, 0.45, 1.0],
                "brightness": 1.2,
                "castShadows": True,
            },
            {
                "class": "SpawnSphere",
                "name": "spawn_default",
                "position": [spawn_x, spawn_y, spawn_z],
                "radius": 5.0,
                "sphereWeight": 1.0,
            },
            {
                "class": "TerrainBlock",
                "name": "theTerrain",
                "terrainFile": f"levels/{self.cfg.level_name}/theTerrain.ter",
                "position": [0.0, 0.0, specs.height_offset],
                "squareSize": specs.square_size,
                "maxHeight": specs.max_elev - specs.min_elev,
                "heightScale": specs.height_scale,
                "baseTexSize": 2048,
                "lightMapSize": 256,
            },
        ]
        level_objects.extend(road_items)

        # 1. main.level.json (Structured SimGroup hierarchy)
        main_json = {
            "class": "SimGroup",
            "name": "MissionGroup",
            "enabled": "1",
            "childs": [
                {
                    "class": "SimGroup",
                    "name": "Level_objects",
                    "childs": level_objects,
                }
            ],
        }

        with open(self.level_dir / "main.level.json", "w", encoding="utf-8") as f:
            json.dump(main_json, f, indent=2)

        # 2. main/items.level.json (For new prefab scene loader)
        main_dir = self.level_dir / "main"
        main_dir.mkdir(exist_ok=True)
        with open(main_dir / "items.level.json", "w", encoding="utf-8") as f:
            f.write(json.dumps({"name": "MissionGroup", "class": "SimGroup", "enabled": "1"}) + "\n")

        # 3. main.materials.json (Material definitions)
        mat_json = {
            "satellite_ground": {
                "name": "satellite_ground",
                "mapTo": "satellite_ground",
                "class": "Material",
                "Stages": [
                    {
                        "colorMap": f"levels/{self.cfg.level_name}/art/textures/satellite_ground.png",
                        "useAnisotropic": True,
                    }
                ],
            }
        }
        with open(self.level_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(mat_json, f, indent=2)

    def _write_info_json(self, sx: float, sy: float, sz: float):
        """Writes info.json for BeamNG Free Roam level selector."""
        info_json = {
            "title": self.cfg.title,
            "description": self.cfg.description,
            "authors": self.cfg.author,
            "size": [int(self.cfg.size_meters), int(self.cfg.size_meters)],
            "previews": ["info.png"],
            "defaultSpawnPointName": "spawn_default",
            "supportsTraffic": True,
            "spawnPoints": [
                {
                    "name": "spawn_default",
                    "object": "spawn_default",
                    "translation": [round(sx, 1), round(sy, 1), round(sz, 1)],
                }
            ],
        }
        with open(self.level_dir / "info.json", "w", encoding="utf-8") as f:
            json.dump(info_json, f, indent=2, ensure_ascii=False)
        print(f"[LevelBuilder] Wrote info.json with title: {self.cfg.title}")

    def _package_mod(self) -> pathlib.Path:
        """Packs level directory into a BeamNG-compliant .zip file."""
        zip_path = self.cfg.output_dir / f"{self.cfg.level_name}.zip"

        # Explicitly pack so every file inside starts with 'levels/<level_name>/'
        prefix = f"levels/{self.cfg.level_name}"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(self.level_dir):
                for file in files:
                    file_path = pathlib.Path(root) / file
                    rel_path = file_path.relative_to(self.level_dir)
                    arcname = f"{prefix}/{rel_path.as_posix()}"
                    zf.write(file_path, arcname=arcname)

        print(f"[LevelBuilder] Successfully packaged mod zip: {zip_path}")

        # Install directly to BeamNG user folder if requested
        if self.cfg.install_to_beamng:
            mods_dir = get_default_beamng_mods_dir()
            if mods_dir:
                dest = mods_dir / f"{self.cfg.level_name}.zip"
                shutil.copy2(zip_path, dest)
                print(f"[LevelBuilder] Auto-installed mod directly to BeamNG mods folder: {dest}")
            else:
                print(f"[LevelBuilder] Note: BeamNG installation not found. Kept zip in build/.")

        return zip_path
