"""Standalone BeamNG Level Exporter for AroundWorldNG.

Pre-bakes a selected real-world bounding box into an independent, classic BeamNG level:
  levels/awng_<slug>/
    info.json                      (Level metadata, title, spawn points)
    preview.jpg                    (16:9 level selector preview)
    theTerrain.ter                 (v9 Torque3D binary terrain heightmap)
    theTerrain.terrain.json        (Terrain config & materials)
    main/items.level.json          (MissionGroup root)
    main/MissionGroup/...          (DecalRoads, Sky, Buildings, Props, SpawnSphere)
    art/shapes/buildings/*.dae     (3D extruded Collada building meshes with collision)
    art/terrains/main.materials.json
    art/main.materials.json

Loads in 3-5 seconds in BeamNG with ZERO runtime procedural generation delay!
"""
from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import time
import zipfile
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import triangulate

import fast_sources
import country_fetch
import places
import looks

if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).resolve().parent
    HERE = Path(__file__).resolve().parent
else:
    HERE = Path(__file__).resolve().parent
    ROOT = HERE.parent

SKY = [
    {'class': 'ScatterSky', 'name': 'sunsky', 'azimuth': 142, 'elevation': 48, 'brightness': 0.85, 'castShadows': True,
     'flareType': 'BNG_Sunflare_2', 'flareScale': 3, 'moonEnabled': True, 'moonMat': 'Moon_Glow_Mat', 'moonScale': 0.06,
     'nightCubemap': 'BNG_Sky_02_cubemap', 'shadowDistance': 1400, 'shadowSoftness': 0.2, 'skyBrightness': 26,
     'texSize': 2048, 'ambientScale': [0.36, 0.4, 0.48, 1], 'colorize': [0.42, 0.55, 0.74, 1], 'colorizeAmount': 0.3,
     'fogScale': [0.55, 0.66, 0.82, 1], 'sunScale': [1, 0.97, 0.92, 1], 'mieScattering': 0.0018,
     'rayleighScattering': 0.0032, 'nightColor': [0.07, 0.08, 0.12, 1], 'nightFogColor': [0.09, 0.11, 0.16, 1]},
    {'class': 'CloudLayer', 'name': 'clouds', 'baseColor': [0.93, 0.94, 0.96, 1], 'coverage': 0.35, 'exposure': 0.5,
     'height': 4.5, 'position': [0, 0, 400], 'texture': 'art/skies/clouds/clouds_normal_displacement.png', 'windSpeed': 1.2,
     'Textures': [{'texDirection': [0.3, 0.1], 'texScale': 0.55, 'texSpeed': 0.0035},
                  {'texDirection': [0.2, 0.9], 'texScale': 0.75, 'texSpeed': 0.005},
                  {'texDirection': [0.1, 0.4], 'texScale': 0.95, 'texSpeed': 0.0065}]},
    {'class': 'TimeOfDay', 'name': 'tod', 'position': [0, 0, 0], 'axisTilt': 23.44, 'day': 200, 'dayLength': 1800,
     'latitude': 50.45, 'longitude': 30.52, 'play': False, 'startTime': 0.10, 'time': 0.10, 'version': 2},
    {'class': 'LevelInfo', 'name': 'theLevelInfo', 'canvasClearColor': [0.58, 0.66, 0.76, 255], 'fogAtmosphereHeight': 700,
     'fogColor': [0.66, 0.71, 0.77, 1], 'fogDensity': 0.00015, 'globalEnviromentMap': 'BNG_Sky_02_cubemap', 'gravity': -9.81,
     'visibleDistance': 8000},
]


CYRILLIC_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
}


def slugify(text: str) -> str:
    t = ''.join(CYRILLIC_MAP.get(c, c) for c in text.lower())
    return re.sub(r'[^a-z0-9]+', '_', t).strip('_')


def write_ter_bytes(heightmap_u16: np.ndarray, materials=('Grass', 'BeachSand', 'dirt_rocky_large', 'rock')) -> bytes:
    """Encode 1024x1024 v9 Torque3D binary terrain."""
    size = heightmap_u16.shape[0]
    buf = bytearray()
    buf.append(9)  # version 9
    buf.extend(struct.pack('<I', size))
    buf.extend(heightmap_u16.astype('<u2').tobytes())
    buf.extend(b'\x01' * (size * size))  # layermap: default layer 1
    buf.extend(struct.pack('<I', len(materials)))
    for mat in materials:
        bname = mat.encode('ascii')
        buf.append(len(bname))
        buf.extend(bname)
    return bytes(buf)


def generate_collada_dae(buildings: list[dict], mat_name="bld_facade") -> str:
    """Generate Collada 1.4.1 XML string for extruded 3D buildings."""
    positions = []
    uvs = []
    indices = []
    v_idx = 0

    for b in buildings:
        rings = b.get('rings', [])
        if not rings:
            continue
        outer = rings[0]
        if len(outer) < 3:
            continue
        h = float(b.get('height', 10.0))
        z_base = float(min(p[2] for p in outer)) if len(outer[0]) > 2 else 0.0
        z_roof = z_base + h

        # 1. Extrude Walls
        for k in range(len(outer) - 1):
            xa, ya = outer[k][0], outer[k][1]
            xb, yb = outer[k + 1][0], outer[k + 1][1]
            dx, dy = xb - xa, yb - ya
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len < 0.1:
                continue
            u_max = max(1.0, seg_len / 3.2)
            v_max = max(1.0, h / 3.0)

            # 4 vertices per wall quad
            positions.extend([xa, ya, z_base, xb, yb, z_base, xb, yb, z_roof, xa, ya, z_roof])
            uvs.extend([0.0, 0.0, u_max, 0.0, u_max, v_max, 0.0, v_max])
            # Two triangles (offset 0: pos, offset 1: uv)
            indices.extend([v_idx, v_idx, v_idx + 1, v_idx + 1, v_idx + 2, v_idx + 2,
                            v_idx, v_idx, v_idx + 2, v_idx + 2, v_idx + 3, v_idx + 3])
            v_idx += 4

        # 2. Triangulate Roof
        try:
            poly = Polygon([(p[0], p[1]) for p in outer])
            if poly.is_valid and poly.area > 1.0:
                for tri in triangulate(poly):
                    if poly.buffer(1e-4).contains(tri.centroid):
                        coords = list(tri.exterior.coords)[:3]
                        for px, py in coords:
                            positions.extend([px, py, z_roof])
                            uvs.extend([px / 6.0, py / 6.0])
                        indices.extend([v_idx, v_idx, v_idx + 1, v_idx + 1, v_idx + 2, v_idx + 2])
                        v_idx += 3
        except Exception:
            pass

    pos_str = ' '.join(f'{v:.3f}' for v in positions)
    uv_str = ' '.join(f'{v:.3f}' for v in uvs)
    idx_str = ' '.join(str(i) for i in indices)
    tri_count = len(indices) // 6

    dae = f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
  <library_effects>
    <effect id="{mat_name}-fx">
      <profile_COMMON>
        <technique sid="common"><lambert><diffuse><color>0.75 0.75 0.75 1</color></diffuse></lambert></technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="{mat_name}" name="{mat_name}"><instance_effect url="#{mat_name}-fx"/></material>
  </library_materials>
  <library_geometries>
    <geometry id="bld_geom" name="bld_geom">
      <mesh>
        <source id="bld_geom-pos">
          <float_array id="bld_geom-pos-array" count="{len(positions)}">{pos_str}</float_array>
          <technique_common>
            <accessor source="#bld_geom-pos-array" count="{len(positions)//3}" stride="3">
              <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="bld_geom-uv">
          <float_array id="bld_geom-uv-array" count="{len(uvs)}">{uv_str}</float_array>
          <technique_common>
            <accessor source="#bld_geom-uv-array" count="{len(uvs)//2}" stride="2">
              <param name="S" type="float"/><param name="T" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="bld_geom-vtx"><input semantic="POSITION" source="#bld_geom-pos"/></vertices>
        <triangles material="{mat_name}" count="{tri_count}">
          <input semantic="VERTEX" source="#bld_geom-vtx" offset="0"/>
          <input semantic="TEXCOORD" source="#bld_geom-uv" offset="1" set="0"/>
          <p>{idx_str}</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="bld_node" name="bld_node">
        <instance_geometry url="#bld_geom">
          <bind_material>
            <technique_common><instance_material symbol="{mat_name}" target="#{mat_name}"/></technique_common>
          </bind_material>
        </instance_geometry>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
'''
    return dae


def generate_preview_image(title: str, roads_xy: list, bounds: tuple) -> bytes:
    """Generate 512x288 JPEG preview image with minimap sketch & title."""
    w, h = 512, 288
    img = Image.new('RGB', (w, h), (19, 21, 26))
    draw = ImageDraw.Draw(img)

    # Background subtle grid
    for x in range(0, w, 32):
        draw.line([(x, 0), (x, h)], fill=(25, 28, 35), width=1)
    for y in range(0, h, 32):
        draw.line([(0, y), (w, y)], fill=(25, 28, 35), width=1)

    min_x, min_y, max_x, max_y = bounds
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)
    scale = min((w - 60) / span_x, (h - 70) / span_y)

    # Draw roads
    for pts in roads_xy:
        if len(pts) < 2:
            continue
        mapped = []
        for p in pts:
            px = 30 + (p[0] - min_x) * scale
            py = (h - 35) - (p[1] - min_y) * scale
            mapped.append((px, py))
        draw.line(mapped, fill=(120, 145, 175), width=2, joint='curve')

    # Card header bar
    draw.rectangle([(0, 0), (w, 38)], fill=(15, 16, 20, 230))
    draw.line([(0, 38), (w, 38)], fill=(60, 65, 80), width=1)

    # Accent badge
    draw.rectangle([(12, 10), (16, 28)], fill=(75, 130, 205))
    draw.text((24, 8), title, fill=(235, 238, 245))
    draw.text((24, 23), "AroundWorldNG Standalone Level", fill=(130, 135, 150))

    # Bottom status badge
    draw.rectangle([(w - 130, h - 26), (w - 12, h - 8)], fill=(30, 35, 45), outline=(55, 65, 85))
    draw.text((w - 122, h - 24), "100% PRE-BAKED", fill=(100, 180, 255))

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return buf.getvalue()


def choose_road_material(tags: dict) -> str:
    highway = tags.get('highway', '')
    surface = tags.get('surface', '')
    if surface in ('dirt', 'ground', 'unpaved', 'gravel', 'sand'):
        return 'DirtRoad_variation_01_d'
    if highway in ('motorway', 'trunk', 'motorway_link', 'trunk_link'):
        return 'AsphaltRoad_variation_two_way'
    if highway in ('primary', 'secondary', 'tertiary'):
        return 'AsphaltRoad_variation_two_way'
    if highway in ('service', 'track'):
        return 'DefaultDecalRoadMaterial'
    return 'AsphaltRoad_variation_two_way'


def safe_scenery(store: fast_sources.Store, rect: list[float], depth: int = 0) -> list:
    """Read scenery safely, subdividing into quarters if the rectangle spans multiple tiles."""
    try:
        return store.scenery(rect)
    except ValueError as exc:
        if 'no_osm' not in str(exc) or depth >= 4:
            return []
    mx, my = (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0
    out = []
    seen = set()
    for part in ([rect[0], rect[1], mx, my], [mx, rect[1], rect[2], my],
                 [rect[0], my, mx, rect[3]], [mx, my, rect[2], rect[3]]):
        for item in safe_scenery(store, part, depth + 1):
            key = (item[0], item[1])
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def find_covering_fast_index(box: list[float]) -> tuple[Optional[Path], Optional[dict]]:
    """Check if any already indexed fast-index region covers the requested box."""
    target = shapely.geometry.box(*box)
    fast_dir = ROOT / 'out' / 'world' / 'fast-index'
    if not fast_dir.is_dir():
        return None, None
    for p in sorted(fast_dir.glob('fast-*'), key=lambda x: x.stat().st_mtime, reverse=True):
        reg_p = p / 'region.json'
        if reg_p.is_file():
            try:
                reg = json.loads(reg_p.read_text(encoding='utf-8'))
                bbox = reg.get('bbox')
                if bbox and shapely.geometry.box(*bbox).covers(target):
                    return p, reg
            except Exception:
                pass
    return None, None


def find_covering_tiles(slug_id: str, box: list[float]) -> Optional[Path]:
    """Check if an existing cut of OSM tiles already covers the requested box."""
    target = shapely.geometry.box(*box)
    tiles_base = ROOT / 'data' / 'osm_tiles'
    if not tiles_base.is_dir():
        return None
    for p in sorted(tiles_base.glob(f'{slug_id}*'), key=lambda x: x.stat().st_mtime, reverse=True):
        idx_p = p / 'index.json'
        if idx_p.is_file():
            try:
                idx = json.loads(idx_p.read_text(encoding='utf-8'))
                pkg_box = idx.get('package_box')
                if pkg_box and shapely.geometry.box(*pkg_box).covers(target):
                    if country_fetch.tiles_current(p):
                        return p
            except Exception:
                pass
    return None


def export_standalone_level(
    place: dict,
    mods_dir: str | Path,
    box: list[float],
    look: Optional[dict] = None,
    include: Optional[dict] = None,
    title: Optional[str] = None,
    emit: Callable[[str], None] = print,
    cancel: Optional[object] = None,
    progress: Optional[Callable[[str, Optional[float]], None]] = None,
) -> Path:
    """Export a standalone BeamNG level from OSM and DEM data.

    Returns the path of the created mods/awng_<slug>.zip file.
    """
    root = ROOT
    pbf_source_id = place.get('pbf_id') or place['id']
    slug_id = places.slug(pbf_source_id)
    box_w, box_s, box_e, box_n = box
    center_lon = (box_w + box_e) / 2.0
    center_lat = (box_s + box_n) / 2.0

    raw_slug = slugify(title or place['name'])
    level_slug = f"awng_{raw_slug[:28]}"
    if title is None:
        title = f"{place['name']} - AWNG"

    emit(f"=== Запуск сборки готовой карты: {title} ===")
    emit(f"Область: lon [{box_w:.4f}, {box_e:.4f}], lat [{box_s:.4f}, {box_n:.4f}]")

    def check_cancel():
        if cancel is not None and getattr(cancel, 'is_set', lambda: False)():
            raise InterruptedError("Экспорт прерван пользователем")

    check_cancel()

    # 1. Sources & Tiles
    t0 = time.monotonic()
    if progress:
        progress('Sources', None)
    emit("Шаг 1/6: Подготовка источников данных (OSM и высоты DEM)...")

    # Fast path: check if covering fast-index already exists
    cov_fast_dir, cov_reg = find_covering_fast_index(box)
    if cov_fast_dir is not None:
        emit(f"Найден готовый кэш геометрии: {cov_fast_dir.name} (повторная нарезка не требуется)")
        store_dir = cov_fast_dir
    else:
        # Check covering tiles
        tiles = find_covering_tiles(slug_id, box) or country_fetch.tiles_dir(root, slug_id, box)
        cached_tiles = country_fetch.tiles_current(tiles)
        if not cached_tiles:
            pbf = country_fetch.pbf_path(root, slug_id)
            if not pbf.is_file():
                # Check candidate filenames in data/pbf
                candidates = [
                    Path(root) / 'data' / 'pbf' / f"{places.slug(pbf_source_id)}.osm.pbf",
                    Path(root) / 'data' / 'pbf' / f"{pbf_source_id}.osm.pbf",
                    Path(root) / 'data' / 'pbf' / f"{Path(place['pbf']).name}",
                    Path(root) / 'data' / 'pbf' / f"{Path(place['pbf']).stem}.osm.pbf",
                    Path(root) / 'data' / 'pbf' / f"{Path(place['pbf']).name.replace('-latest', '')}",
                ]
                for cand in candidates:
                    if cand.is_file():
                        pbf = cand
                        break
            if not pbf.is_file():
                emit(f"Скачивание PBF: {place['pbf']}...")
                country_fetch.download(place['pbf'], pbf, emit, cancel)
            emit("Нарезка тайлов OSM...")
            country_fetch.cut_tiles(pbf, tiles, box, emit=emit, cancel=cancel)

        index = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))
        dem = root / 'out' / 'world' / 'cache'
        emit("Загрузка высотных данных DEM...")
        country_fetch.fetch_dem(index, dem, emit, cancel)

        work = root / 'out' / 'world'
        regions_path = work / 'regions.json'
        country_fetch.run_build_job({'command': 'index', 'sources': str(tiles), 'dem': str(dem),
                                     'work': str(work), 'result': str(regions_path)}, emit, cancel)
        regions = json.loads(regions_path.read_text(encoding='utf-8'))
        if not regions:
            raise ValueError("Не удалось проиндексировать регион для выбранной области.")
        store_dir = Path(regions[0]['dir'])

    if progress:
        progress('Sources', time.monotonic() - t0)

    # 2. Local Frame & Geometry Sampling
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Geometry', None)
    emit("Шаг 2/6: Загрузка дорог и объектов из индекса...")

    store = fast_sources.Store(store_dir)
    frame = store.frame

    min_x, min_y = frame.local(box_w, box_s)
    max_x, max_y = frame.local(box_e, box_n)
    if min_x > max_x:
        min_x, max_x = max_x, min_x
    if min_y > max_y:
        min_y, max_y = max_y, min_y

    query_rect = [min_x - 50.0, min_y - 50.0, max_x + 50.0, max_y + 50.0]

    # Query roads
    roads = []
    seen_roads = set()
    for fid, kind, data, geometry in store.query(query_rect):
        if kind == 'road' and fid not in seen_roads:
            seen_roads.add(fid)
            road_info = json.loads(data) if isinstance(data, str) else data
            roads.append(road_info)

    emit(f"Найдено сегментов дорог: {len(roads)}")

    # Query scenery (buildings, trees, lamps)
    scenery = safe_scenery(store, query_rect)
    buildings = []
    trees = []
    lamps = []

    for fid, kind, data, geom in scenery:
        tags = data.get('tags', {})
        if kind == 'building':
            h = max(3.0, min(800.0, float(tags.get('height') or (float(tags.get('building:levels') or 3) * 3.2))))
            # rings
            parts = [geom] if geom.geom_type == 'Polygon' else list(getattr(geom, 'geoms', []))
            for p in parts:
                coords = list(p.exterior.coords)
                z_sampled = store.terrain.sample(coords)
                rings_3d = [[(c[0], c[1], float(z)) for c, z in zip(coords, z_sampled)]]
                buildings.append({'id': fid, 'height': h, 'rings': rings_3d, 'tags': tags})
        elif kind == 'tree':
            trees.append((geom.x, geom.y, float(store.terrain.sample([[geom.x, geom.y]])[0])))
        elif kind == 'lamp':
            lamps.append((geom.x, geom.y, float(store.terrain.sample([[geom.x, geom.y]])[0])))

    emit(f"Найдено зданий: {len(buildings)}, деревьев: {len(trees)}, фонарей: {len(lamps)}")

    if progress:
        progress('Geometry', time.monotonic() - t0)

    # 3. Terrain Generation (theTerrain.ter)
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Terrain', None)
    emit("Шаг 3/6: Запекание высотной карты theTerrain.ter (1024x1024)...")

    ter_size = 1024
    span_x = max_x - min_x
    span_y = max_y - min_y
    max_span = max(span_x, span_y)
    square_size = max(1.0, max_span / (ter_size - 1))

    # Center terrain at (0, 0)
    origin_x = - (ter_size * square_size) / 2.0
    origin_y = - (ter_size * square_size) / 2.0

    # Grid sampling
    gx = origin_x + np.arange(ter_size) * square_size
    gy = origin_y + np.arange(ter_size) * square_size
    grid_x, grid_y = np.meshgrid(gx, gy)
    sample_pts = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    z_grid = store.terrain.sample(sample_pts).reshape(ter_size, ter_size)

    min_z = float(np.min(z_grid))
    max_z = float(np.max(z_grid))
    base_z = min_z - 3.0
    max_height = max(10.0, (max_z - base_z) + 10.0)

    z_norm = np.clip((z_grid - base_z) / max_height, 0.0, 1.0)
    heightmap_u16 = (z_norm * 65535.0).astype('<u2')

    ter_bytes = write_ter_bytes(heightmap_u16)
    emit(f"Высота рельефа: от {min_z:.1f} м до {max_z:.1f} м (диапазон: {max_height:.1f} м)")

    if progress:
        progress('Terrain', time.monotonic() - t0)

    # 4. DecalRoads Generation
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Roads', None)
    emit("Шаг 4/6: Создание дорог DecalRoad...")

    decal_roads = []
    spawn_pos = None
    spawn_heading = 0.0
    roads_sketch = []

    for idx, r in enumerate(roads):
        pts_2d = r.get('xy', [])
        if len(pts_2d) < 2:
            continue
        roads_sketch.append(pts_2d)
        tags = r.get('tags', {})
        mat = choose_road_material(tags)
        width = float(r.get('width', 6.0))

        # Sample or interpolate z
        z_pts = store.terrain.sample(pts_2d)
        nodes = []
        for (x, y), z in zip(pts_2d, z_pts):
            nodes.append([round(float(x), 2), round(float(y), 2), round(float(z) + 0.06, 2), round(width, 2)])

        decal_roads.append({
            'name': f"road_{idx}_{r.get('id', idx)}",
            'class': 'DecalRoad',
            '__parent': 'Roads',
            'drivability': 1,
            'improvedSpline': True,
            'material': mat,
            'nodes': nodes,
        })

        # Select first good road near center for spawn
        if spawn_pos is None and len(nodes) >= 2:
            dist_to_center = math.hypot(nodes[0][0], nodes[0][1])
            if dist_to_center < max_span * 0.4:
                spawn_pos = [nodes[0][0], nodes[0][1], nodes[0][2] + 0.6]
                dx = nodes[1][0] - nodes[0][0]
                dy = nodes[1][1] - nodes[0][1]
                spawn_heading = math.atan2(dy, dx)

    if spawn_pos is None:
        center_z = float(store.terrain.sample([[0, 0]])[0])
        spawn_pos = [0.0, 0.0, center_z + 1.0]

    emit(f"Сгенерировано DecalRoad объектов: {len(decal_roads)}")
    emit(f"Точка спавна: X={spawn_pos[0]:.1f}, Y={spawn_pos[1]:.1f}, Z={spawn_pos[2]:.1f}")

    if progress:
        progress('Roads', time.monotonic() - t0)

    # 5. 3D Building Meshes (Collada .dae) & Props
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Buildings', None)
    emit("Шаг 5/6: Экструзия 3D-зданий и расстановка объектов...")

    dae_files = {}
    bld_statics = []
    chunk_size = 600

    for chunk_idx, i in enumerate(range(0, len(buildings), chunk_size)):
        chunk = buildings[i:i + chunk_size]
        dae_name = f"buildings_chunk_{chunk_idx}.dae"
        dae_xml = generate_collada_dae(chunk, mat_name="bld_facade")
        dae_files[f"levels/{level_slug}/art/shapes/buildings/{dae_name}"] = dae_xml
        bld_statics.append({
            'name': f"buildings_chunk_{chunk_idx}",
            'class': 'TSStatic',
            '__parent': 'Buildings',
            'position': [0.0, 0.0, 0.0],
            'shapeName': f"/levels/{level_slug}/art/shapes/buildings/{dae_name}",
            'collisionType': 'Visible Mesh Final',
            'decalType': 'Visible Mesh',
            'useInstanceRenderData': True,
        })

    # Props (trees & street lamps)
    prop_statics = []
    tree_shape = "/levels/east_coast_usa/art/shapes/trees/trees_douglasfir/s_douglasfir_large_01.dae"
    lamp_shape = "/levels/west_coast_usa/art/shapes/objects/street_light_single.dae"

    for idx, (tx, ty, tz) in enumerate(trees[:500]):
        prop_statics.append({
            'name': f"tree_{idx}",
            'class': 'TSStatic',
            '__parent': 'Props',
            'position': [round(tx, 2), round(ty, 2), round(tz, 2)],
            'shapeName': tree_shape,
            'collisionType': 'Visible Mesh Final',
            'useInstanceRenderData': True,
        })

    for idx, (lx, ly, lz) in enumerate(lamps[:300]):
        prop_statics.append({
            'name': f"lamp_{idx}",
            'class': 'TSStatic',
            '__parent': 'Props',
            'position': [round(lx, 2), round(ly, 2), round(lz, 2)],
            'shapeName': lamp_shape,
            'collisionType': 'Visible Mesh Final',
            'useInstanceRenderData': True,
        })

    if progress:
        progress('Buildings', time.monotonic() - t0)

    # 6. Assembly & Packaging
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Packaging', None)
    emit("Шаг 6/6: Упаковка готового мода уровней...")

    # SpawnSphere
    yaw = spawn_heading
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)
    spawn_obj = {
        'class': 'SpawnSphere',
        'name': 'spawn_default',
        '__parent': 'MissionGroup',
        'position': [round(spawn_pos[0], 2), round(spawn_pos[1], 2), round(spawn_pos[2], 2)],
        'rotation': [0.0, 0.0, round(qz, 4), round(qw, 4)],
        'radius': 2.0,
        'dataBlock': 'SpawnSphereMarker',
    }

    # TerrainBlock
    terrain_block = {
        'name': 'theTerrain',
        'class': 'TerrainBlock',
        '__parent': 'MissionGroup',
        'position': [round(origin_x, 2), round(origin_y, 2), round(base_z, 2)],
        'maxHeight': round(max_height, 2),
        'squareSize': round(square_size, 3),
        'terrainFile': f"/levels/{level_slug}/theTerrain.ter",
    }

    mission_group_items = [
        {'class': 'SimGroup', 'name': 'Sky', '__parent': 'MissionGroup'},
        {'class': 'SimGroup', 'name': 'Roads', '__parent': 'MissionGroup'},
        {'class': 'SimGroup', 'name': 'Buildings', '__parent': 'MissionGroup'},
        {'class': 'SimGroup', 'name': 'Props', '__parent': 'MissionGroup'},
        spawn_obj,
        terrain_block,
    ]

    # Info.json
    info_json = {
        'title': title,
        'description': f"Автономная готовая карта, сгенерированная в AroundWorldNG Map Studio. "
                       f"Реальный рельеф DEM и дорожная сеть OSM ({title}). Загружается мгновенно.",
        'authors': 'AroundWorldNG',
        'size': [int(max_span), int(max_span)],
        'defaultSpawnPointName': 'spawn_default',
        'previews': ['preview.jpg'],
        'spawnPoints': [{
            'name': 'Старт',
            'objectname': 'spawn_default',
            'preview': 'preview.jpg',
        }],
    }

    # Terrain json
    terrain_json = {
        'binaryFormat': 'version(char), size(unsigned int), heightMap(heightMapSize * heightMapItemSize), layerMap(layerMapSize * layerMapItemSize), layerTextureMap(layerMapSize * layerMapItemSize), materialNames',
        'datafile': f"/levels/{level_slug}/theTerrain.ter",
        'heightMapItemSize': 2,
        'heightMapSize': ter_size * ter_size,
        'layerMapItemSize': 1,
        'layerMapSize': ter_size * ter_size,
        'materials': ['Grass', 'BeachSand', 'dirt_rocky_large', 'rock'],
        'size': ter_size,
        'version': 9,
    }

    # Materials
    bld_materials = {
        'bld_facade': {
            'name': 'bld_facade',
            'mapTo': 'bld_facade',
            'class': 'Material',
            'version': 1.5,
            'Stages': [
                {
                    'baseColorMap': '/levels/east_coast_usa/art/shapes/buildings/eca_bld_brick_01_d.color.png',
                    'roughnessFactor': 0.8,
                },
                {}, {}, {}
            ],
        }
    }

    terrain_materials = {
        'templateTerrainMaterialTextureSet': {
            'name': 'templateTerrainMaterialTextureSet',
            'class': 'TerrainMaterialTextureSet',
            'baseTexSize': [512, 512],
            'detailTexSize': [1024, 1024],
            'macroTexSize': [1024, 1024],
        }
    }

    preview_jpg = generate_preview_image(title, roads_sketch, (min_x, min_y, max_x, max_y))

    # Assemble mod zip
    out_dir = root / 'out' / 'standalone'
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{level_slug}.zip"
    tmp_zip = zip_path.with_suffix('.zip.tmp')

    with zipfile.ZipFile(tmp_zip, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        # Base files
        z.writestr(f"levels/{level_slug}/info.json", json.dumps(info_json, ensure_ascii=False, indent=2))
        z.writestr(f"levels/{level_slug}/preview.jpg", preview_jpg)
        z.writestr(f"levels/{level_slug}/theTerrain.ter", ter_bytes)
        z.writestr(f"levels/{level_slug}/theTerrain.terrain.json", json.dumps(terrain_json, ensure_ascii=False, indent=2))
        z.writestr(f"levels/{level_slug}/art/shapes/buildings/main.materials.json", json.dumps(bld_materials, indent=2))
        z.writestr(f"levels/{level_slug}/art/terrains/main.materials.json", json.dumps(terrain_materials, indent=2))

        # Main SimGroup files
        z.writestr(f"levels/{level_slug}/main/items.level.json", json.dumps({'class': 'SimGroup', 'name': 'MissionGroup'}) + '\n')
        z.writestr(f"levels/{level_slug}/main/MissionGroup/items.level.json", ''.join(json.dumps(o) + '\n' for o in mission_group_items))
        z.writestr(f"levels/{level_slug}/main/MissionGroup/Sky/items.level.json", ''.join(json.dumps({**o, '__parent': 'Sky'}) + '\n' for o in SKY))
        z.writestr(f"levels/{level_slug}/main/MissionGroup/Roads/items.level.json", ''.join(json.dumps(o) + '\n' for o in decal_roads))
        z.writestr(f"levels/{level_slug}/main/MissionGroup/Buildings/items.level.json", ''.join(json.dumps(o) + '\n' for o in bld_statics))
        z.writestr(f"levels/{level_slug}/main/MissionGroup/Props/items.level.json", ''.join(json.dumps(o) + '\n' for o in prop_statics))

        # DAE files
        for fname, content in dae_files.items():
            z.writestr(fname, content)

    if tmp_zip.exists():
        tmp_zip.replace(zip_path)

    emit(f"Архив карты создан: {zip_path.name} ({zip_path.stat().st_size / 2**20:.1f} MB)")

    # Install directly to mods if requested
    dest_path = zip_path
    if mods_dir:
        mods_path = Path(mods_dir)
        target_dir = mods_path / 'mods' if (mods_path / 'mods').is_dir() else mods_path
        if target_dir.is_dir():
            target_zip = target_dir / f"{level_slug}.zip"
            shutil.copy2(zip_path, target_zip)
            dest_path = target_zip
            emit(f"Установлено в BeamNG mods: {dest_path}")

    if progress:
        progress('Packaging', time.monotonic() - t0)

    emit(f"=== Готово! Карта «{title}» доступна в главном меню BeamNG.drive ===")
    return dest_path
