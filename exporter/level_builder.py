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
from exporter.building_mesh import create_cube_dae
from exporter.buildings import BuildingExporter
from exporter.decal_roads import RoadExporter
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

        # 1. Export 16-bit Heightmap and Native Torque3D .ter binary (Version 9)
        terrain_dir = self.level_dir / "terrain"
        terrain_dir.mkdir(exist_ok=True)
        heightmap_proc.export_16bit_png(terrain_dir / "heightmap.png")
        heightmap_proc.export_16bit_png(self.level_dir / "theTerrain.terrainheightmap.png")
        heightmap_proc.export_binary_ter(
            self.level_dir / "theTerrain.ter",
            materials=["Grass"],
            level_name=self.cfg.level_name,
        )

        # 2. Export Satellite Texture and Previews (Power-of-two 2048x2048 RGBA for PBR Terrain)
        art_ter_dir = self.level_dir / "art" / "terrains"
        art_ter_dir.mkdir(parents=True, exist_ok=True)

        if sat_image:
            # Resize satellite orthophoto to power-of-two
            pot_size = 2048
            sat_pot = sat_image.resize((pot_size, pot_size), Image.Resampling.LANCZOS).convert("RGBA")
            sat_pot.save(art_ter_dir / "t_terrain_base_b.png", format="PNG")

            # Generate companion PBR maps for terrain texture cooker
            # Normal map: neutral flat tangent normal (128, 128, 255)
            nm_img = Image.new("RGB", (pot_size, pot_size), color=(128, 128, 255))
            nm_img.save(art_ter_dir / "t_terrain_base_nm.png", format="PNG")

            # Roughness map: (200)
            r_img = Image.new("L", (pot_size, pot_size), color=200)
            r_img.save(art_ter_dir / "t_terrain_base_r.png", format="PNG")

            # Ambient occlusion: (255)
            ao_img = Image.new("L", (pot_size, pot_size), color=255)
            ao_img.save(art_ter_dir / "t_terrain_base_ao.png", format="PNG")

            # Save 512x512 preview images for BeamNG UI
            preview_img = sat_image.resize((512, 512), Image.Resampling.LANCZOS)
            preview_img.save(self.level_dir / "info.png")
            preview_img.save(self.level_dir / "_preview.png")
            print(f"[LevelBuilder] Saved satellite orthophoto (2048x2048 PBR) & preview images.")

        # 3. Create 3D Building Base Mesh (.dae)
        building_dae_path = self.level_dir / "art" / "shapes" / "buildings" / "building_box.dae"
        create_cube_dae(building_dae_path)

        # 4. Determine Player Spawn Point (On a real road near center)
        spawn_x, spawn_y, spawn_z = self._find_spawn_point(osm_data, heightmap_proc)

        # 5. Generate Road Splines (DecalRoad & MeshRoad)
        road_exporter = RoadExporter(
            heightmap_processor=heightmap_proc,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
        )
        road_items = road_exporter.export_roads(osm_data.roads) if self.cfg.generate_roads else []

        # 6. Generate 3D Buildings (TSStatic)
        building_items: List[Dict[str, Any]] = []
        if self.cfg.generate_buildings and osm_data.buildings:
            building_exporter = BuildingExporter(
                heightmap=heightmap_proc,
                level_name=self.cfg.level_name,
                origin_lat=self.cfg.center_lat,
                origin_lon=self.cfg.center_lon,
            )
            building_items = building_exporter.export_buildings(osm_data.buildings)

        # 7. Generate Scene Hierarchy (main/items.level.json and main/MissionGroup/items.level.json)
        self._write_scene_ndjson(terrain_specs, road_items, building_items, spawn_x, spawn_y, spawn_z)

        # 8. Generate main.materials.json and art/terrains/main.materials.json
        self._write_materials_json()

        # 9. Generate info.json
        self._write_info_json(spawn_x, spawn_y, spawn_z)

        # 10. Pack into .zip mod archive with root 'levels/<level_name>/...'
        archive_path = self._package_mod()
        return archive_path

    def _find_spawn_point(
        self, osm_data: OSMData, heightmap: HeightmapProcessor
    ) -> Tuple[float, float, float]:
        """Finds a road point closest to map center (0, 0) for player vehicle spawning."""
        best_pt = (0.0, 0.0, 50.0)
        min_dist = float("inf")

        for road in osm_data.roads:
            if road.is_bridge or road.is_tunnel:
                continue
            for lat, lon in road.nodes:
                x, y = lat_lon_to_meters(lat, lon, self.cfg.center_lat, self.cfg.center_lon)
                dist = x ** 2 + y ** 2
                if dist < min_dist:
                    min_dist = dist
                    z = heightmap.get_elevation_at_meters(x, y) + 0.8
                    best_pt = (x, y, z)

        if min_dist == float("inf"):
            # Fallback to map center
            z = heightmap.get_elevation_at_meters(0.0, 0.0) + 1.0
            best_pt = (0.0, 0.0, z)

        print(f"[LevelBuilder] Spawn point set at ({best_pt[0]:.1f}, {best_pt[1]:.1f}, {best_pt[2]:.1f})")
        return best_pt

    def _write_scene_ndjson(
        self,
        specs: TerrainSpecs,
        road_items: List[Dict[str, Any]],
        building_items: List[Dict[str, Any]],
        spawn_x: float,
        spawn_y: float,
        spawn_z: float,
    ):
        """
        Writes main/items.level.json and main/MissionGroup/items.level.json in NDJSON format.
        This provides native object loading and full daytime lighting in BeamNG 0.40.
        """
        # Directory structure
        main_dir = self.level_dir / "main"
        mission_group_dir = main_dir / "MissionGroup"
        mission_group_dir.mkdir(parents=True, exist_ok=True)

        # 1. main/items.level.json: Defines root MissionGroup
        with open(main_dir / "items.level.json", "w", encoding="utf-8") as f:
            root_group = {
                "name": "MissionGroup",
                "class": "SimGroup",
                "persistentId": str(uuid.uuid4()),
                "enabled": "1",
            }
            f.write(json.dumps(root_group) + "\n")

        # 2. main/MissionGroup/items.level.json: All scene objects as JSON Lines
        mg_items: List[Dict[str, Any]] = [
            # Environment & Fog
            {
                "name": "theLevelInfo",
                "class": "LevelInfo",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "canvasClearColor": "black",
                "enabled": "1",
                "fogAtmosphereHeight": 800.0,
                "fogColor": [0.74, 0.81, 0.92, 1.0],
                "fogDensity": 0.0001,
                "globalEnviromentMap": "BNG_Sky_01_cubemap",
                "gravity": -9.81,
                "visibleDistance": 10000.0,
            },
            # Daylight Atmosphere & Sun
            {
                "name": "sunsky",
                "class": "ScatterSky",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [spawn_x, spawn_y, spawn_z + 100.0],
                "azimuth": 57.3,
                "elevation": 144.0,
                "skyBrightness": 40.0,
                "colorize": [0.22, 0.35, 0.61, 1.0],
                "sunScale": [1.0, 0.81, 0.71, 1.0],
                "ambientScale": [1.0, 0.89, 0.78, 1.0],
                "rayleighScattering": 0.01,
                "mieScattering": 0.00043,
                "exposure": 15.0,
                "useNightCubemap": True,
            },
            # Time of Day
            {
                "name": "tod",
                "class": "TimeOfDay",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [spawn_x, spawn_y, spawn_z],
                "axisTilt": 10.0,
                "play": False,
                "startTime": 0.15,
                "time": 0.15,
            },
            # Default Spawn Sphere
            {
                "name": "spawn_default",
                "class": "SpawnSphere",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [spawn_x, spawn_y, spawn_z],
                "radius": 5.0,
                "sphereWeight": 1.0,
                "dataBlock": "SpawnSphereMarker",
                "enabled": "1",
            },
            # Physical TerrainBlock
            {
                "name": "theTerrain",
                "class": "TerrainBlock",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "terrainFile": f"/levels/{self.cfg.level_name}/theTerrain.ter",
                "position": [-self.cfg.size_meters / 2.0, -self.cfg.size_meters / 2.0, specs.height_offset],
                "squareSize": specs.square_size,
                "maxHeight": max(specs.max_elev - specs.min_elev, 10.0),
                "baseTexSize": 2048,
                "materialTextureSet": f"{self.cfg.level_name}TerrainMaterialTextureSet",
                "minimapImage": f"levels/{self.cfg.level_name}/info.png",
                "lightMapSize": 256,
            },
        ]

        # Add all roads
        mg_items.extend(road_items)

        # Add all 3D buildings
        mg_items.extend(building_items)

        # Write lines
        mg_file = mission_group_dir / "items.level.json"
        with open(mg_file, "w", encoding="utf-8") as f:
            for item in mg_items:
                f.write(json.dumps(item) + "\n")

        print(f"[LevelBuilder] Wrote {len(mg_items)} objects to main/MissionGroup/items.level.json")

        # Also write main.level.json for backward compatibility
        main_json = {
            "class": "SimGroup",
            "name": "MissionGroup",
            "enabled": "1",
            "childs": [
                {
                    "class": "SimGroup",
                    "name": "Level_objects",
                    "childs": mg_items,
                }
            ],
        }
        with open(self.level_dir / "main.level.json", "w", encoding="utf-8") as f:
            json.dump(main_json, f, indent=2)

    def _write_materials_json(self):
        """
        Writes art/terrains/main.materials.json, art/road/main.materials.json,
        art/shapes/buildings/main.materials.json and root main.materials.json
        strictly conforming to BeamNG.drive 0.40 PBR material standards.
        """
        import uuid

        # 1. art/terrains/main.materials.json: PBR Terrain Materials and Texture Set
        art_ter_dir = self.level_dir / "art" / "terrains"
        art_ter_dir.mkdir(parents=True, exist_ok=True)

        ter_mats = {
            f"{self.cfg.level_name}TerrainMaterialTextureSet": {
                "name": f"{self.cfg.level_name}TerrainMaterialTextureSet",
                "class": "TerrainMaterialTextureSet",
                "baseTexSize": [2048, 2048],
                "detailTexSize": [1024, 1024],
                "macroTexSize": [1024, 1024],
            },
            "Grass": {
                "internalName": "Grass",
                "class": "TerrainMaterial",
                "persistentId": str(uuid.uuid4()),
                "annotation": "GRASS",
                "groundmodelName": "GRASS",
                "baseColorBaseTex": f"/levels/{self.cfg.level_name}/art/terrains/t_terrain_base_b.png",
                "baseColorBaseTexSize": int(self.cfg.size_meters),
                "normalBaseTex": f"/levels/{self.cfg.level_name}/art/terrains/t_terrain_base_nm.png",
                "normalBaseTexSize": int(self.cfg.size_meters),
                "roughnessBaseTex": f"/levels/{self.cfg.level_name}/art/terrains/t_terrain_base_r.png",
                "roughnessBaseTexSize": int(self.cfg.size_meters),
                "aoBaseTex": f"/levels/{self.cfg.level_name}/art/terrains/t_terrain_base_ao.png",
                "aoBaseTexSize": int(self.cfg.size_meters),
                "baseColorDetailTex": "/assets/materials/terrain/grass/ind_grass/t_ind_grass_b.png",
                "baseColorDetailStrength": [0.25, 0.25],
                "normalDetailTex": "/assets/materials/terrain/grass/ind_grass/t_ind_grass_nm.png",
                "normalDetailStrength": [0.6, 0.2],
                "roughnessDetailTex": "/assets/materials/terrain/grass/ind_grass/t_ind_grass_r.png",
                "roughnessDetailStrength": [0.3, 0.3],
                "macroDistances": [0, 10, 100, 3000],
            },
        }

        with open(art_ter_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(ter_mats, f, indent=2)

        # 2. art/road/main.materials.json: Photorealistic DecalRoad materials using BeamNG built-in core PBR maps
        art_road_dir = self.level_dir / "art" / "road"
        art_road_dir.mkdir(parents=True, exist_ok=True)

        road_mats = {
            "road_asphalt": {
                "name": "road_asphalt",
                "mapTo": "road_asphalt",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "ambientOcclusionMap": "/assets/materials/decalroad/asphalt/AsphaltRoad_variation_02/t_asphalt_variation_02_ao.data.dds",
                        "baseColorFactor": [1.0, 1.0, 1.0, 0.95],
                        "baseColorMap": "/assets/materials/decalroad/asphalt/AsphaltRoad_variation_02/t_asphalt_variation_02_b.color.dds",
                        "normalMap": "/assets/materials/decalroad/asphalt/AsphaltRoad_variation_02/t_asphalt_variation_02_nm.normal.dds",
                        "opacityMap": "/assets/materials/decalroad/asphalt/AsphaltRoad_variation_02/t_asphalt_variation_02_o.data.dds",
                        "roughnessMap": "/assets/materials/decalroad/asphalt/AsphaltRoad_variation_02/t_asphalt_variation_02_r.data.dds",
                    },
                    {},
                    {},
                    {},
                ],
                "alphaRef": 0,
                "annotation": "ASPHALT",
                "castShadows": False,
                "groundType": "ASPHALT_OLD",
                "materialTag0": "RoadAndPath",
                "materialTag1": "beamng",
                "specularStrength0": "0",
                "translucent": True,
                "translucentZWrite": True,
                "version": 1.5,
            },
            "road_dirt": {
                "name": "road_dirt",
                "mapTo": "road_dirt",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "ambientOcclusionMap": "/assets/materials/decalroad/dirt/DirtRoad_variation_01/t_dirt_variation_01_ao.data.dds",
                        "baseColorFactor": [1.0, 1.0, 1.0, 0.95],
                        "baseColorMap": "/assets/materials/decalroad/dirt/DirtRoad_variation_01/t_dirt_variation_01_b.color.dds",
                        "normalMap": "/assets/materials/decalroad/dirt/DirtRoad_variation_01/t_dirt_variation_01_nm.normal.dds",
                        "roughnessMap": "/assets/materials/decalroad/dirt/DirtRoad_variation_01/t_dirt_variation_01_r.data.dds",
                    },
                    {},
                    {},
                    {},
                ],
                "annotation": "DIRT",
                "castShadows": False,
                "groundType": "DIRT",
                "materialTag0": "RoadAndPath",
                "materialTag1": "beamng",
                "translucent": True,
                "translucentZWrite": True,
                "version": 1.5,
            },
        }

        with open(art_road_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(road_mats, f, indent=2)

        # 3. art/shapes/buildings/main.materials.json: 3D TSStatic Building materials
        art_bld_dir = self.level_dir / "art" / "shapes" / "buildings"
        art_bld_dir.mkdir(parents=True, exist_ok=True)

        bld_mats = {
            "building_mat": {
                "name": "building_mat",
                "mapTo": "building_mat",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "diffuseColor": [0.82, 0.80, 0.78, 1.0],
                        "roughness": 0.75,
                    }
                ],
                "annotation": "BUILDINGS",
            }
        }

        with open(art_bld_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(bld_mats, f, indent=2)

        # 4. Level root main.materials.json: Contains combined references for complete fallback compatibility
        combined_mats = {}
        combined_mats.update(road_mats)
        combined_mats.update(bld_mats)
        with open(self.level_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(combined_mats, f, indent=2)

        print(f"[LevelBuilder] Wrote terrain materials (v0.40 TextureSet), road PBR materials, and building materials.")
        print(f"[LevelBuilder] Wrote terrain materials and decal road materials.")

    def _write_info_json(self, sx: float, sy: float, sz: float):
        """Writes info.json for BeamNG Free Roam level selector."""
        info_json = {
            "title": self.cfg.title,
            "description": self.cfg.description,
            "authors": self.cfg.author,
            "size": [int(self.cfg.size_meters), int(self.cfg.size_meters)],
            "previews": ["info.png", "_preview.png"],
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
