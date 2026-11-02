"""
BeamNG Level Builder and Packager.
Assembles the complete mod folder and produces a ready-to-play .zip mod archive.
"""

import json
import os
import pathlib
import shutil
from typing import Any, Dict, List, Optional, Tuple
import uuid
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

        # 1. Export 16-bit Heightmap
        terrain_dir = self.level_dir / "terrain"
        terrain_dir.mkdir(exist_ok=True)
        heightmap_png_path = terrain_dir / "heightmap.png"
        heightmap_proc.export_16bit_png(heightmap_png_path)

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

        # 6. Generate items.level.json
        self._write_items_level_json(terrain_specs, road_items, spawn_x, spawn_y, spawn_z)

        # 7. Generate main.level.json
        self._write_main_level_json()

        # 8. Generate info.json (mod descriptor)
        self._write_info_json(spawn_x, spawn_y, spawn_z)

        # 9. Pack into .zip mod archive
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
                    z = heightmap.get_elevation_at_meters(x, y) + 0.5
                    best_pt = (x, y, z)

        print(f"[LevelBuilder] Spawn point set at ({best_pt[0]:.1f}, {best_pt[1]:.1f}, {best_pt[2]:.1f})")
        return best_pt

    def _write_items_level_json(
        self,
        specs: TerrainSpecs,
        road_items: List[Dict[str, Any]],
        spawn_x: float,
        spawn_y: float,
        spawn_z: float,
    ):
        """Writes items.level.json containing TerrainBlock, DecalRoads, Sun, and Environment."""
        items: List[Dict[str, Any]] = []

        # TerrainBlock
        terrain_obj = {
            "name": "theTerrain",
            "class": "TerrainBlock",
            "persistentId": str(uuid.uuid4()),
            "terrainFile": "terrain/heightmap.png",
            "position": [0.0, 0.0, specs.height_offset],
            "squareSize": specs.square_size,
            "maxHeight": specs.max_elev - specs.min_elev,
            "heightScale": specs.height_scale,
            "baseTexSize": 2048,
            "lightMapSize": 256,
        }
        items.append(terrain_obj)

        # Sun / Lighting
        sun_obj = {
            "name": "sun",
            "class": "Sun",
            "persistentId": str(uuid.uuid4()),
            "azimuth": 45.0,
            "elevation": 55.0,
            "color": [1.0, 0.98, 0.92, 1.0],
            "ambient": [0.35, 0.38, 0.45, 1.0],
            "brightness": 1.2,
            "castShadows": True,
        }
        items.append(sun_obj)

        # Sky / Atmosphere
        sky_obj = {
            "name": "sky",
            "class": "TimeOfDay",
            "persistentId": str(uuid.uuid4()),
            "axisTilt": 23.44,
            "dayLength": 1200.0,
            "startTime": 0.35,
        }
        items.append(sky_obj)

        # Spawn Sphere
        spawn_obj = {
            "name": "spawn_default",
            "class": "SpawnSphere",
            "persistentId": str(uuid.uuid4()),
            "position": [spawn_x, spawn_y, spawn_z],
            "radius": 5.0,
            "sphereWeight": 1.0,
        }
        items.append(spawn_obj)

        # Road items
        items.extend(road_items)

        items_file = self.level_dir / "items.level.json"
        with open(items_file, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
        print(f"[LevelBuilder] Wrote {len(items)} items to items.level.json")

    def _write_main_level_json(self):
        """Writes main.level.json."""
        main_json = {
            "name": self.cfg.level_name,
            "description": self.cfg.description,
            "version": 1.0,
        }
        with open(self.level_dir / "main.level.json", "w", encoding="utf-8") as f:
            json.dump(main_json, f, indent=2)

    def _write_info_json(self, sx: float, sy: float, sz: float):
        """Writes info.json for BeamNG mod manager and map selection menu."""
        info_json = {
            "title": self.cfg.title,
            "description": self.cfg.description,
            "author": self.cfg.author,
            "size": f"{int(self.cfg.size_meters)}m x {int(self.cfg.size_meters)}m",
            "country": "Russia",
            "previews": ["info.png"],
            "spawnPoints": [
                {
                    "name": "Default Spawn",
                    "translation": [round(sx, 1), round(sy, 1), round(sz, 1)],
                }
            ],
        }
        with open(self.level_dir / "info.json", "w", encoding="utf-8") as f:
            json.dump(info_json, f, indent=2)

    def _package_mod(self) -> pathlib.Path:
        """Packs level directory into a BeamNG-compliant .zip file."""
        if not self.cfg.pack_zip:
            return self.level_dir

        zip_base = self.cfg.output_dir / self.cfg.level_name
        # In BeamNG mod zip, root should have 'levels/<level_name>/...'
        staging_dir = self.cfg.output_dir / "_staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        
        target_in_staging = staging_dir / "levels" / self.cfg.level_name
        shutil.copytree(self.level_dir, target_in_staging)

        zip_path = shutil.make_archive(str(zip_base), "zip", staging_dir)
        shutil.rmtree(staging_dir)
        print(f"[LevelBuilder] Successfully packaged mod zip: {zip_path}")

        # Install directly to BeamNG user folder if requested
        if self.cfg.install_to_beamng:
            mods_dir = get_default_beamng_mods_dir()
            if mods_dir:
                dest = mods_dir / f"{self.cfg.level_name}.zip"
                shutil.copy2(zip_path, dest)
                print(f"[LevelBuilder] Auto-installed mod directly to BeamNG mods folder: {dest}")
            else:
                print(f"[LevelBuilder] Note: BeamNG installation not found. Keep zip in build/.")

        return pathlib.Path(zip_path)
