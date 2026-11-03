"""
BeamNG Level Builder and Packager.
Assembles the complete mod folder and produces a ready-to-play .zip mod archive
compatible with BeamNG.drive 0.3x and 0.4x with full 3D procedural generation.
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
from exporter.building_mesh import create_all_building_archetypes
from exporter.buildings import BuildingExporter
from exporter.decal_roads import RoadExporter
from exporter.forest_builder import ForestBuilder
from exporter.road_decorations import RoadDecorationBuilder
from exporter.water_builder import WaterBuilder
from fetchers.osm import OSMData
from processing.exclusion import SpatialExclusionEngine
from processing.heightmap import HeightmapProcessor, TerrainSpecs
from processing.terrain_layers import TerrainLayerEngine


class LevelBuilder:
    """Master assembler for rich, physical BeamNG.drive level environments."""

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

        print(f"\n[LevelBuilder] Assembling full procedural level '{self.cfg.level_name}'...")

        # 1. Multi-layer Terrain Biome Engine (Procedural Grass, Asphalt, Dirt, Rock)
        layer_engine = TerrainLayerEngine(
            elevations=heightmap_proc.elevations,
            square_size=heightmap_proc.square_size,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
            size_meters=self.cfg.size_meters,
        )
        layer_map = layer_engine.compute_layer_map(osm_data)

        # 2. Export 16-bit Heightmap and Native Torque3D .ter binary (Version 9)
        terrain_dir = self.level_dir / "terrain"
        terrain_dir.mkdir(exist_ok=True)
        heightmap_proc.export_16bit_png(terrain_dir / "heightmap.png")
        heightmap_proc.export_16bit_png(self.level_dir / "theTerrain.terrainheightmap.png")
        heightmap_proc.export_binary_ter(
            output_ter_path=self.level_dir / "theTerrain.ter",
            materials=TerrainLayerEngine.MATERIAL_NAMES,
            layer_map=layer_map,
            level_name=self.cfg.level_name,
        )

        # 2b. Export collision fluid depth map for BeamNG physics engine
        depth_img = Image.new("L", (heightmap_proc.res - 1, heightmap_proc.res - 1), color=0)
        depth_img.save(self.level_dir / "theTerrain.ter.depth.png")

        # 3. Export Base Terrain Textures and UI Previews (Power-of-two 2048x2048)
        art_ter_dir = self.level_dir / "art" / "terrains"
        art_ter_dir.mkdir(parents=True, exist_ok=True)

        pot_size = 2048
        # Create standard PBR base textures for Torque3D terrain cell shader
        base_img = Image.new("RGB", (pot_size, pot_size), color=(126, 116, 100))
        base_img.save(art_ter_dir / "t_terrain_base_b.png", format="PNG")

        nm_img = Image.new("RGB", (pot_size, pot_size), color=(128, 128, 255))
        nm_img.save(art_ter_dir / "t_terrain_base_nm.png", format="PNG")

        r_img = Image.new("L", (pot_size, pot_size), color=235)
        r_img.save(art_ter_dir / "t_terrain_base_r.png", format="PNG")

        ao_img = Image.new("L", (pot_size, pot_size), color=255)
        ao_img.save(art_ter_dir / "t_terrain_base_ao.png", format="PNG")

        h_img = Image.new("L", (pot_size, pot_size), color=128)
        h_img.save(art_ter_dir / "t_terrain_base_h.png", format="PNG")

        if sat_image:
            preview_img = sat_image.resize((512, 512), Image.Resampling.LANCZOS)
            preview_img.save(self.level_dir / "info.png")
            preview_img.save(self.level_dir / "_preview.png")
            print(f"[LevelBuilder] Saved UI preview and minimap textures.")

        # 4. Generate Architectural 3D Building Archetypes & Instances
        shapes_dir = self.level_dir / "art" / "shapes"
        create_all_building_archetypes(shapes_dir)

        building_items: List[Dict[str, Any]] = []
        if self.cfg.generate_buildings and osm_data.buildings:
            building_exporter = BuildingExporter(
                heightmap=heightmap_proc,
                level_name=self.cfg.level_name,
                origin_lat=self.cfg.center_lat,
                origin_lon=self.cfg.center_lon,
                output_dir=shapes_dir / "buildings",
            )
            building_items = building_exporter.export_buildings(osm_data.buildings)

        # 5. Generate Road Splines (DecalRoad & MeshRoad)
        road_exporter = RoadExporter(
            heightmap_processor=heightmap_proc,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
            size_meters=self.cfg.size_meters,
        )
        road_items = road_exporter.export_roads(osm_data.roads) if self.cfg.generate_roads else []

        # 6. Generate Roadside Props & Streetlights
        decor_builder = RoadDecorationBuilder(
            heightmap=heightmap_proc,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
            size_meters=self.cfg.size_meters,
        )
        decor_items = decor_builder.generate_decorations(osm_data.roads)

        # 7. Generate 3D Forest & Foliage Instances
        forest_obj: Optional[Dict[str, Any]] = None
        if self.cfg.generate_forest:
            forest_builder = ForestBuilder(
                level_name=self.cfg.level_name,
                origin_lat=self.cfg.center_lat,
                origin_lon=self.cfg.center_lon,
                heightmap=heightmap_proc,
                exclusion=exclusion,
                size_meters=self.cfg.size_meters,
            )
            forest_obj = forest_builder.generate_forest(osm_data, self.level_dir)

        # 8. Generate Physical Water Bodies
        water_builder = WaterBuilder(
            heightmap=heightmap_proc,
            origin_lat=self.cfg.center_lat,
            origin_lon=self.cfg.center_lon,
            specs=terrain_specs,
        )
        water_items = water_builder.generate_water_items(
            osm_data.waters,
            has_coastline=osm_data.has_coastline,
        )

        # 9. Determine Player Spawn Point (On a real road near map center)
        spawn_x, spawn_y, spawn_z = self._find_spawn_point(osm_data, heightmap_proc)

        # 10. Generate Scene Hierarchy (main/items.level.json and main/MissionGroup/items.level.json)
        self._write_scene_ndjson(
            specs=terrain_specs,
            road_items=road_items,
            building_items=building_items,
            decor_items=decor_items,
            water_items=water_items,
            forest_obj=forest_obj,
            spawn_x=spawn_x,
            spawn_y=spawn_y,
            spawn_z=spawn_z,
        )

        # 11. Generate Materials JSONs
        self._write_materials_json()

        # 12. Generate info.json
        self._write_info_json(spawn_x, spawn_y, spawn_z)

        # 13. Pack into .zip mod archive
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
            z = heightmap.get_elevation_at_meters(0.0, 0.0) + 1.0
            best_pt = (0.0, 0.0, z)

        print(f"[LevelBuilder] Spawn point set at ({best_pt[0]:.1f}, {best_pt[1]:.1f}, {best_pt[2]:.1f})")
        return best_pt

    def _write_scene_ndjson(
        self,
        specs: TerrainSpecs,
        road_items: List[Dict[str, Any]],
        building_items: List[Dict[str, Any]],
        decor_items: List[Dict[str, Any]],
        water_items: List[Dict[str, Any]],
        forest_obj: Optional[Dict[str, Any]],
        spawn_x: float,
        spawn_y: float,
        spawn_z: float,
    ):
        """
        Writes main/items.level.json and main/MissionGroup/items.level.json in NDJSON format.
        """
        main_dir = self.level_dir / "main"
        mission_group_dir = main_dir / "MissionGroup"
        mission_group_dir.mkdir(parents=True, exist_ok=True)

        with open(main_dir / "items.level.json", "w", encoding="utf-8") as f:
            root_group = {
                "name": "MissionGroup",
                "class": "SimGroup",
                "persistentId": str(uuid.uuid4()),
                "enabled": "1",
            }
            f.write(json.dumps(root_group) + "\n")

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
            # Daylight Atmosphere & Sun (Crisp High-Noon Lighting)
            {
                "name": "sunsky",
                "class": "ScatterSky",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [spawn_x, spawn_y, spawn_z + 100.0],
                "azimuth": 80.0,
                "elevation": 50.0,
                "skyBrightness": 30.0,
                "colorize": [0.22, 0.35, 0.61, 1.0],
                "sunScale": [1.0, 0.85, 0.75, 1.0],
                "ambientScale": [0.8, 0.85, 0.9, 1.0],
                "rayleighScattering": 0.01,
                "mieScattering": 0.00043,
                "exposure": 14.0,
                "useNightCubemap": True,
            },
            # Time of Day (12:00 PM Midday)
            {
                "name": "tod",
                "class": "TimeOfDay",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [spawn_x, spawn_y, spawn_z],
                "axisTilt": 10.0,
                "play": False,
                "startTime": 0.5,
                "time": 0.5,
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
            # Centered Multi-Layer TerrainBlock
            {
                "name": "theTerrain",
                "class": "TerrainBlock",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "terrainFile": f"levels/{self.cfg.level_name}/theTerrain.ter",
                "position": [-self.cfg.size_meters / 2.0, -self.cfg.size_meters / 2.0, specs.height_offset],
                "squareSize": specs.square_size,
                "maxHeight": max(specs.max_elev - specs.min_elev, 10.0),
                "baseTexSize": 2048,
                "materialTextureSet": f"{self.cfg.level_name}TerrainMaterialTextureSet",
                "minimapImage": f"levels/{self.cfg.level_name}/info.png",
                "lightMapSize": 256,
            },
        ]

        if forest_obj:
            mg_items.append(forest_obj)

        mg_items.extend(water_items)
        mg_items.extend(road_items)
        mg_items.extend(decor_items)
        mg_items.extend(building_items)

        mg_file = mission_group_dir / "items.level.json"
        with open(mg_file, "w", encoding="utf-8") as f:
            for item in mg_items:
                f.write(json.dumps(item) + "\n")

        print(f"[LevelBuilder] Wrote {len(mg_items)} objects to main/MissionGroup/items.level.json")

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
        art/shapes/buildings/main.materials.json, art/forest/main.materials.json,
        art/shapes/trees/main.materials.json, and level root main.materials.json.
        """
        import uuid

        # 1. PBR Multi-Layer Terrain Materials (Grass, Asphalt, Dirt, Rock)
        art_ter_dir = self.level_dir / "art" / "terrains"
        art_ter_dir.mkdir(parents=True, exist_ok=True)

        terrain_mats_path = pathlib.Path(__file__).parent / "terrain_materials.json"
        if terrain_mats_path.exists():
            with open(terrain_mats_path, "r", encoding="utf-8") as f:
                raw_ter_json = f.read()
            raw_ter_json = raw_ter_json.replace("{LEVEL}", self.cfg.level_name)
            ter_mats = json.loads(raw_ter_json)
        else:
            ter_mats = {}

        full_ter_mats = {
            f"{self.cfg.level_name}TerrainMaterialTextureSet": {
                "name": f"{self.cfg.level_name}TerrainMaterialTextureSet",
                "class": "TerrainMaterialTextureSet",
                "persistentId": str(uuid.uuid4()),
                "baseTexSize": [2048, 2048],
                "detailTexSize": [1024, 1024],
                "macroTexSize": [1024, 1024],
            }
        }
        full_ter_mats.update(ter_mats)

        with open(art_ter_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(full_ter_mats, f, indent=2)

        # 2. Photorealistic DecalRoad materials (West Coast USA official standard)
        art_road_dir = self.level_dir / "art" / "road"
        art_road_dir.mkdir(parents=True, exist_ok=True)

        road_mats_path = pathlib.Path(__file__).parent / "road_materials.json"
        if road_mats_path.exists():
            with open(road_mats_path, "r", encoding="utf-8") as f:
                road_mats = json.load(f)
        else:
            road_mats = {}

        with open(art_road_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(road_mats, f, indent=2)

        # 3. Tree & Foliage materials (26 complete species and leaf/bark symbols)
        art_forest_dir = self.level_dir / "art" / "forest"
        art_forest_dir.mkdir(parents=True, exist_ok=True)
        art_trees_dir = self.level_dir / "art" / "shapes" / "trees"
        art_trees_dir.mkdir(parents=True, exist_ok=True)

        tree_mats_path = pathlib.Path(__file__).parent / "tree_materials.json"
        if tree_mats_path.exists():
            with open(tree_mats_path, "r", encoding="utf-8") as f:
                tree_mats = json.load(f)
        else:
            tree_mats = {}

        with open(art_forest_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(tree_mats, f, indent=2)
        with open(art_trees_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(tree_mats, f, indent=2)

        # 4. 3D Architectural Building Facade & Roof materials (100% PBR core assets)
        art_bld_dir = self.level_dir / "art" / "shapes" / "buildings"
        art_bld_dir.mkdir(parents=True, exist_ok=True)

        bld_mats = {
            "facade_brick": {
                "name": "facade_brick",
                "mapTo": "facade_brick",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_b.color.dds",
                        "normalMap": "/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_r.data.dds",
                        "ambientOcclusionMap": "/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_ao.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "facade_glass": {
                "name": "facade_glass",
                "mapTo": "facade_glass",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/glass/modernstripwindow/t_window_strips_01_b.color.dds",
                        "normalMap": "/assets/materials/tileable/glass/modernstripwindow/t_window_strips_01_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/glass/modernstripwindow/t_window_strips_01_r.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "facade_plaster": {
                "name": "facade_plaster",
                "mapTo": "facade_plaster",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_b.color.png",
                        "normalMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_nm.normal.png",
                        "roughnessMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_r.data.png",
                        "ambientOcclusionMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_ao.data.png",
                        "metallicMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_m.data.png",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "bne_bld_facade": {
                "name": "bne_bld_facade",
                "mapTo": "bne_bld_facade",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_b.color.png",
                        "normalMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_nm.normal.png",
                        "roughnessMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_r.data.png",
                        "ambientOcclusionMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_ao.data.png",
                        "metallicMap": "/assets/materials/trim/plaster/t_highrise_plaster/t_highrise_plaster_m.data.png",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "facade_metal": {
                "name": "facade_metal",
                "mapTo": "facade_metal",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_b.color.dds",
                        "normalMap": "/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_r.data.dds",
                        "ambientOcclusionMap": "/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_ao.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "roof_gravel": {
                "name": "roof_gravel",
                "mapTo": "roof_gravel",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_b.color.dds",
                        "normalMap": "/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_r.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "roof_tiles": {
                "name": "roof_tiles",
                "mapTo": "roof_tiles",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_b.color.dds",
                        "normalMap": "/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_r.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "bne_bld_roof_flat": {
                "name": "bne_bld_roof_flat",
                "mapTo": "bne_bld_roof_flat",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_b.color.dds",
                        "normalMap": "/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_r.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
            "bne_bld_roof_slate": {
                "name": "bne_bld_roof_slate",
                "mapTo": "bne_bld_roof_slate",
                "class": "Material",
                "persistentId": str(uuid.uuid4()),
                "Stages": [
                    {
                        "baseColorMap": "/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_b.color.dds",
                        "normalMap": "/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_nm.normal.dds",
                        "roughnessMap": "/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_r.data.dds",
                    }
                ],
                "annotation": "BUILDINGS",
            },
        }

        with open(art_bld_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(bld_mats, f, indent=2)

        # 5. Root main.materials.json fallback (bundles all materials for immediate lookup)
        combined_mats = {}
        combined_mats.update(tree_mats)
        combined_mats.update(road_mats)
        combined_mats.update(bld_mats)
        with open(self.level_dir / "main.materials.json", "w", encoding="utf-8") as f:
            json.dump(combined_mats, f, indent=2)

        print(f"[LevelBuilder] Wrote full PBR multi-layer terrain, road, foliage, and architectural facade materials.")

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

        if self.cfg.install_to_beamng:
            mods_dir = get_default_beamng_mods_dir()
            if mods_dir:
                dest = mods_dir / f"{self.cfg.level_name}.zip"
                shutil.copy2(zip_path, dest)
                print(f"[LevelBuilder] Auto-installed mod directly to BeamNG mods folder: {dest}")
            else:
                print(f"[LevelBuilder] Note: BeamNG installation not found. Kept zip in build/.")

        return zip_path
