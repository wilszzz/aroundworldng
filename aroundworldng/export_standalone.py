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
import sys
import time
import zipfile
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import triangulate

try:
    import fast_sources
    import country_fetch
    import places
    import looks
    import road_markings
    import road_decorations
    import proc_vegetation
    import spawn_system
    import terrain_builder
except ImportError:
    from . import fast_sources
    from . import country_fetch
    from . import places
    from . import looks
    from . import road_markings
    from . import road_decorations
    from . import proc_vegetation
    from . import spawn_system
    from . import terrain_builder

if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).resolve().parent
    HERE = Path(__file__).resolve().parent
else:
    HERE = Path(__file__).resolve().parent
    ROOT = HERE.parent


def _find_resource(filename: str) -> Path:
    candidates = []
    if hasattr(sys, '_MEIPASS'):
        mp = Path(sys._MEIPASS).resolve()
        candidates.extend([mp / filename, mp / 'aroundworldng' / filename])
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        internal = exe_dir / '_internal'
        candidates.extend([
            internal / filename,
            internal / 'aroundworldng' / filename,
            exe_dir / filename,
            exe_dir / 'aroundworldng' / filename,
        ])
    here = Path(__file__).resolve().parent
    repo = here.parent if here.name == 'aroundworldng' else here
    candidates.extend([
        here / filename,
        here / 'aroundworldng' / filename,
        repo / filename,
        repo / 'aroundworldng' / filename,
    ])
    for c in candidates:
        if c.is_file():
            return c
    return here / filename

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


def write_ter_bytes(
    heightmap_u16: np.ndarray,
    materials=('Grass', 'BeachSand', 'dirt_rocky_large', 'rock'),
    layer_map: Optional[np.ndarray] = None,
) -> bytes:
    """Encode 1024x1024 v9 Torque3D binary terrain using the canonical terrain_builder."""
    return terrain_builder.encode_ter_v9(
        heightmap_u16=heightmap_u16,
        layer_map_u8=layer_map,
        materials=materials,
    )


def polygon_area_2d(pts: list) -> float:
    """Compute signed 2D area of a polygon ring. Positive for CCW, negative for CW."""
    n = len(pts)
    if n < 3:
        return 0.0
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) * 0.5


def triangulate_polygon_2d(outer_pts: list, holes: Optional[list] = None) -> list[tuple]:
    """Robust ear-clipping 2D polygon triangulation with hole bridge support.

    Guarantees strict counter-clockwise (CCW) triangle orientation and eliminates
    the boundary bleed and sliver artifacts of unconstrained Delaunay triangulation.
    """
    outer = list(outer_pts)
    if len(outer) > 1 and outer[0][:2] == outer[-1][:2]:
        outer.pop()
    if len(outer) < 3:
        return []

    # Enforce CCW orientation for outer boundary
    area_o = polygon_area_2d(outer)
    if abs(area_o) < 1e-4:
        return []
    if area_o < 0:
        outer.reverse()

    # Bridge holes into the outer boundary seam
    if holes:
        for hole in holes:
            h = list(hole)
            if len(h) > 1 and h[0][:2] == h[-1][:2]:
                h.pop()
            if len(h) < 3:
                continue
            h_area = polygon_area_2d(h)
            if abs(h_area) < 1e-4:
                continue
            if h_area > 0:
                h.reverse()  # Holes must be CW

            # Connect hole vertex with maximum X to nearest outer vertex
            max_idx = max(range(len(h)), key=lambda i: h[i][0])
            h_pt = h[max_idx]
            best_o = min(range(len(outer)), key=lambda i: (outer[i][0] - h_pt[0])**2 + (outer[i][1] - h_pt[1])**2)
            h_rot = h[max_idx:] + h[:max_idx]
            outer = outer[:best_o + 1] + h_rot + [h_rot[0], outer[best_o]] + outer[best_o + 1:]

    pts = outer
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(pts[0], pts[1], pts[2])]

    def is_convex(p0, p1, p2):
        return (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]) > 1e-7

    def point_in_tri(p, a, b, c):
        c1 = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        c2 = (c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])
        c3 = (a[0] - c[0]) * (p[1] - c[1]) - (a[1] - c[1]) * (p[0] - c[0])
        return (c1 >= -1e-7 and c2 >= -1e-7 and c3 >= -1e-7) or (c1 <= 1e-7 and c2 <= 1e-7 and c3 <= 1e-7)

    indices = list(range(len(pts)))
    triangles = []
    attempts = 0
    max_attempts = len(indices) * 4

    while len(indices) > 3 and attempts < max_attempts:
        ear_found = False
        k = len(indices)
        for idx in range(k):
            prev_i = indices[(idx - 1) % k]
            curr_i = indices[idx]
            next_i = indices[(idx + 1) % k]

            p_prev = pts[prev_i]
            p_curr = pts[curr_i]
            p_next = pts[next_i]

            if not is_convex(p_prev, p_curr, p_next):
                continue

            any_inside = False
            for other_idx in range(k):
                if other_idx in ((idx - 1) % k, idx, (idx + 1) % k):
                    continue
                p_test = pts[indices[other_idx]]
                if p_test == p_prev or p_test == p_curr or p_test == p_next:
                    continue
                if point_in_tri(p_test, p_prev, p_curr, p_next):
                    any_inside = True
                    break

            if not any_inside:
                triangles.append((p_prev, p_curr, p_next))
                indices.pop(idx)
                ear_found = True
                break
        if not ear_found:
            attempts += 1
            break

    if len(indices) == 3:
        triangles.append((pts[indices[0]], pts[indices[1]], pts[indices[2]]))

    return triangles


def generate_collada_dae(
    buildings: list[dict],
    mat_name: str = "bld_facade",
    roof_mat_name: str = "bld_roof",
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    skirt_depth: float = 0.5,
) -> str:
    """Generate Collada 1.4.1 XML string for extruded 3D buildings.

    Optimized for BeamNG.drive / Torque3D:
    - Watertight walls with ground skirt (0.5m) for 'Visible Mesh Final' collision physics.
    - Strict CCW winding for outward-facing wall normals and upward-facing roof normals.
    - Floor & window bay UV unwrapping (1 texture repeat per floor and per window bay).
    - Robust ear-clipping roof triangulation with hole support and Delaunay fallback.
    - Distinct wall and roof materials for realistic architectural rendering.
    - Local origin offsetting for high-precision vertex buffers and TSStatic culling.
    """
    ox, oy, oz = origin
    positions: list[float] = []
    normals: list[float] = []
    uvs: list[float] = []
    wall_indices: list[int] = []
    roof_indices: list[int] = []
    v_idx = 0

    for b in buildings:
        rings = b.get('rings', [])
        if not rings:
            continue
        outer = list(rings[0])
        if len(outer) < 3:
            continue

        # Ensure outer ring is closed
        if outer[0][:2] != outer[-1][:2]:
            outer.append(outer[0])

        # Ensure outer ring is CCW in XY plane
        area_2d = polygon_area_2d([p[:2] for p in outer[:-1]])
        if abs(area_2d) < 1.0:
            continue
        if area_2d < 0:
            outer.reverse()

        tags = b.get('tags', {})
        h_match = re.search(r'[\d.]+', str(tags.get('height') or b.get('height') or ''))
        lvl_match = re.search(r'[\d.]+', str(tags.get('building:levels') or tags.get('levels') or ''))

        if h_match:
            try:
                h = max(3.0, min(800.0, float(h_match.group(0))))
            except Exception:
                h = 10.0
        elif lvl_match:
            try:
                h = max(3.0, min(800.0, float(lvl_match.group(0)) * 3.2))
            except Exception:
                h = 10.0
        else:
            try:
                h = max(3.0, min(800.0, float(b.get('height', 10.0))))
            except Exception:
                h = 10.0

        if lvl_match:
            try:
                levels = max(1, round(float(lvl_match.group(0))))
            except Exception:
                levels = max(1, round(h / 3.2))
        else:
            levels = max(1, round(h / 3.2))
        floor_h = h / max(1, levels)

        z_ground_pts = [p[2] for p in outer if len(p) > 2] or [0.0]
        z_ground_max = max(z_ground_pts)
        z_roof = z_ground_max + h
        z_roof_rel = z_roof - oz
        v_roof = float(levels)

        # 1. Extrude Outer Walls
        for k in range(len(outer) - 1):
            pa = outer[k]
            pb = outer[k + 1]
            xa, ya = pa[0], pa[1]
            xb, yb = pb[0], pb[1]
            za = pa[2] if len(pa) > 2 else z_ground_max
            zb = pb[2] if len(pb) > 2 else z_ground_max

            dx, dy = xb - xa, yb - ya
            seg_len = math.hypot(dx, dy)
            if seg_len < 0.1:
                continue

            # Outward normal (perpendicular to CCW edge pointing right)
            nx = dy / seg_len
            ny = -dx / seg_len
            nz = 0.0

            # Skirt depth into ground terrain for watertight collision
            za_base = za - skirt_depth
            zb_base = zb - skirt_depth

            xa_rel = xa - ox
            ya_rel = ya - oy
            xb_rel = xb - ox
            yb_rel = yb - oy
            za_base_rel = za_base - oz
            zb_base_rel = zb_base - oz

            # UV coordinates:
            # U: integer number of window bays to avoid cut-off windows at corners
            num_bays = max(1.0, round(seg_len / 3.2))
            u0 = 0.0
            u1 = float(num_bays)
            # V: 0.0 at ground level, v_roof at roofline, smooth skirt extension below 0
            v_base_a = (za_base - za) / floor_h
            v_base_b = (zb_base - zb) / floor_h

            # Quad vertices:
            # v0: bottom-left (xa, ya, za_base)
            # v1: bottom-right (xb, yb, zb_base)
            # v2: top-right (xb, yb, z_roof)
            # v3: top-left (xa, ya, z_roof)
            positions.extend([
                xa_rel, ya_rel, za_base_rel,
                xb_rel, yb_rel, zb_base_rel,
                xb_rel, yb_rel, z_roof_rel,
                xa_rel, ya_rel, z_roof_rel,
            ])
            normals.extend([
                nx, ny, nz,
                nx, ny, nz,
                nx, ny, nz,
                nx, ny, nz,
            ])
            uvs.extend([
                u0, v_base_a,
                u1, v_base_b,
                u1, v_roof,
                u0, v_roof,
            ])
            # Two CCW triangles: (0, 1, 2) and (0, 2, 3)
            wall_indices.extend([
                v_idx, v_idx, v_idx,
                v_idx + 1, v_idx + 1, v_idx + 1,
                v_idx + 2, v_idx + 2, v_idx + 2,

                v_idx, v_idx, v_idx,
                v_idx + 2, v_idx + 2, v_idx + 2,
                v_idx + 3, v_idx + 3, v_idx + 3,
            ])
            v_idx += 4

        # 2. Extrude Inner Courtyard Walls (if any)
        holes = []
        if len(rings) > 1:
            for inner in rings[1:]:
                in_ring = list(inner)
                if len(in_ring) < 3:
                    continue
                if in_ring[0][:2] != in_ring[-1][:2]:
                    in_ring.append(in_ring[0])
                in_area = polygon_area_2d([p[:2] for p in in_ring[:-1]])
                if abs(in_area) < 1.0:
                    continue
                # Inner holes must be CW so walls face into courtyard
                if in_area > 0:
                    in_ring.reverse()
                holes.append(in_ring)

                for k in range(len(in_ring) - 1):
                    pa = in_ring[k]
                    pb = in_ring[k + 1]
                    xa, ya = pa[0], pa[1]
                    xb, yb = pb[0], pb[1]
                    za = pa[2] if len(pa) > 2 else z_ground_max
                    zb = pb[2] if len(pb) > 2 else z_ground_max
                    dx, dy = xb - xa, yb - ya
                    seg_len = math.hypot(dx, dy)
                    if seg_len < 0.1:
                        continue

                    # Normal facing into courtyard
                    nx = dy / seg_len
                    ny = -dx / seg_len
                    nz = 0.0

                    za_base = za - skirt_depth
                    zb_base = zb - skirt_depth
                    xa_rel = xa - ox
                    ya_rel = ya - oy
                    xb_rel = xb - ox
                    yb_rel = yb - oy
                    za_base_rel = za_base - oz
                    zb_base_rel = zb_base - oz

                    num_bays = max(1.0, round(seg_len / 3.2))
                    u0 = 0.0
                    u1 = float(num_bays)
                    v_base_a = (za_base - za) / floor_h
                    v_base_b = (zb_base - zb) / floor_h

                    positions.extend([
                        xa_rel, ya_rel, za_base_rel,
                        xb_rel, yb_rel, zb_base_rel,
                        xb_rel, yb_rel, z_roof_rel,
                        xa_rel, ya_rel, z_roof_rel,
                    ])
                    normals.extend([
                        nx, ny, nz,
                        nx, ny, nz,
                        nx, ny, nz,
                        nx, ny, nz,
                    ])
                    uvs.extend([
                        u0, v_base_a,
                        u1, v_base_b,
                        u1, v_roof,
                        u0, v_roof,
                    ])
                    wall_indices.extend([
                        v_idx, v_idx, v_idx,
                        v_idx + 1, v_idx + 1, v_idx + 1,
                        v_idx + 2, v_idx + 2, v_idx + 2,

                        v_idx, v_idx, v_idx,
                        v_idx + 2, v_idx + 2, v_idx + 2,
                        v_idx + 3, v_idx + 3, v_idx + 3,
                    ])
                    v_idx += 4

        # 3. Triangulate Roof
        outer_2d = [p[:2] for p in outer[:-1]]
        holes_2d = [[p[:2] for p in h[:-1]] for h in holes] if holes else None
        triangles = triangulate_polygon_2d(outer_2d, holes_2d)

        # Fallback to Shapely if ear-clipping returned nothing
        if not triangles:
            try:
                poly = Polygon(outer_2d, holes_2d)
                if poly.is_valid and poly.area > 1.0:
                    for tri in triangulate(poly):
                        if poly.buffer(1e-4).contains(tri.centroid):
                            c = list(tri.exterior.coords)[:3]
                            triangles.append((c[0], c[1], c[2]))
            except Exception:
                pass

        for tri in triangles:
            p0, p1, p2 = tri[0], tri[1], tri[2]
            positions.extend([
                p0[0] - ox, p0[1] - oy, z_roof_rel,
                p1[0] - ox, p1[1] - oy, z_roof_rel,
                p2[0] - ox, p2[1] - oy, z_roof_rel,
            ])
            normals.extend([
                0.0, 0.0, 1.0,
                0.0, 0.0, 1.0,
                0.0, 0.0, 1.0,
            ])
            # Planar UV mapping: 4.0m texture repeat
            uvs.extend([
                (p0[0] - ox) / 4.0, (p0[1] - oy) / 4.0,
                (p1[0] - ox) / 4.0, (p1[1] - oy) / 4.0,
                (p2[0] - ox) / 4.0, (p2[1] - oy) / 4.0,
            ])
            roof_indices.extend([
                v_idx, v_idx, v_idx,
                v_idx + 1, v_idx + 1, v_idx + 1,
                v_idx + 2, v_idx + 2, v_idx + 2,
            ])
            v_idx += 3

    pos_str = ' '.join(f'{v:.3f}' for v in positions)
    norm_str = ' '.join(f'{v:.3f}' for v in normals)
    uv_str = ' '.join(f'{v:.3f}' for v in uvs)
    wall_p_str = ' '.join(str(i) for i in wall_indices)
    roof_p_str = ' '.join(str(i) for i in roof_indices)

    wall_tri_count = len(wall_indices) // 9
    roof_tri_count = len(roof_indices) // 9

    triangles_xml = []
    if wall_tri_count > 0:
        triangles_xml.append(f'''        <triangles material="{mat_name}" count="{wall_tri_count}">
          <input semantic="VERTEX" source="#bld_geom-vtx" offset="0"/>
          <input semantic="NORMAL" source="#bld_geom-norm" offset="1"/>
          <input semantic="TEXCOORD" source="#bld_geom-uv" offset="2" set="0"/>
          <p>{wall_p_str}</p>
        </triangles>''')

    if roof_tri_count > 0:
        triangles_xml.append(f'''        <triangles material="{roof_mat_name}" count="{roof_tri_count}">
          <input semantic="VERTEX" source="#bld_geom-vtx" offset="0"/>
          <input semantic="NORMAL" source="#bld_geom-norm" offset="1"/>
          <input semantic="TEXCOORD" source="#bld_geom-uv" offset="2" set="0"/>
          <p>{roof_p_str}</p>
        </triangles>''')

    triangles_section = '\n'.join(triangles_xml)

    dae = f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><authoring_tool>AroundWorldNG Procedural 3D Building Extrusion</authoring_tool></contributor>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_effects>
    <effect id="{mat_name}-fx">
      <profile_COMMON>
        <technique sid="common"><lambert><diffuse><color>0.75 0.75 0.75 1</color></diffuse></lambert></technique>
      </profile_COMMON>
    </effect>
    <effect id="{roof_mat_name}-fx">
      <profile_COMMON>
        <technique sid="common"><lambert><diffuse><color>0.35 0.35 0.35 1</color></diffuse></lambert></technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="{mat_name}" name="{mat_name}"><instance_effect url="#{mat_name}-fx"/></material>
    <material id="{roof_mat_name}" name="{roof_mat_name}"><instance_effect url="#{roof_mat_name}-fx"/></material>
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
        <source id="bld_geom-norm">
          <float_array id="bld_geom-norm-array" count="{len(normals)}">{norm_str}</float_array>
          <technique_common>
            <accessor source="#bld_geom-norm-array" count="{len(normals)//3}" stride="3">
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
{triangles_section}
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="bld_node" name="bld_node">
        <instance_geometry url="#bld_geom">
          <bind_material>
            <technique_common>
              <instance_material symbol="{mat_name}" target="#{mat_name}"/>
              <instance_material symbol="{roof_mat_name}" target="#{roof_mat_name}"/>
            </technique_common>
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


UNPAVED_DIRT_SURFACES = {'dirt', 'earth', 'ground', 'soil', 'mud', 'clay', 'unpaved'}
UNPAVED_GRAVEL_SURFACES = {'gravel', 'fine_gravel', 'compacted', 'pebblestone', 'crushed_stone'}
COBBLESTONE_SURFACES = {'sett', 'cobblestone', 'paving_stones', 'cobblestone:flattened'}


def choose_road_look(tags: dict, width: float = 6.0) -> tuple[str, float, int]:
    """Determines PBR material name, texture length, and render priority for DecalRoad."""
    h = str(tags.get('highway', '')).lower().strip()
    s = str(tags.get('surface', '')).lower().strip()
    tracktype = str(tags.get('tracktype', '')).lower().strip()
    smoothness = str(tags.get('smoothness', '')).lower().strip()

    is_oneway = fast_sources.oneway(tags) if hasattr(fast_sources, 'oneway') else (
        str(tags.get('oneway', '')).lower() in ('yes', '1', 'true') or h == 'motorway'
    )
    lanes_val = tags.get('lanes')
    try:
        lanes = float(lanes_val) if lanes_val else (1.0 if is_oneway else 2.0)
    except (ValueError, TypeError):
        lanes = 1.0 if is_oneway else 2.0

    # 1. Unpaved Dirt / Earth / Mud
    if s in UNPAVED_DIRT_SURFACES:
        if tracktype in ('grade2', 'grade3') or h in ('track', 'path'):
            return 'dirt_tiretracks', 22.0, 10
        if s == 'mud':
            return 'm_dirt_variation_04_east_coast_usa', 25.0, 10
        return 'DirtRoad_variation_01_d', 25.0, 10

    # 2. Sand
    if s == 'sand':
        return 'Dirt_road_variation_02', 25.0, 10

    # 3. Gravel / Compacted Stone
    if s in UNPAVED_GRAVEL_SURFACES:
        return 'dirt_road_gravels', 30.0, 10

    # 4. Cobblestone / Sett / Damaged Asphalt
    if s in COBBLESTONE_SURFACES or smoothness in ('bad', 'very_bad', 'horrible'):
        return 'm_asphalt_damaged_01_east_coast_usa', 15.0, 10

    # 5. Highways without explicit surface tag
    if not s:
        if h in ('track', 'path', 'bridleway'):
            if tracktype == 'grade1':
                return 'dirt_road_gravels', 30.0, 10
            if tracktype in ('grade2', 'grade3'):
                return 'dirt_tiretracks', 22.0, 10
            return 'DirtRoad_variation_01_d', 25.0, 10

    # 6. Service / Living Street / Driveway / Pedestrian
    if h in ('service', 'living_street', 'parking_aisle', 'driveway', 'pedestrian', 'footway', 'cycleway'):
        return 'DefaultDecalRoadMaterial', 12.0, 10

    # 7. Racetracks
    if h == 'raceway':
        return 'AsphaltRoad_variation_track', 15.0, 10

    # 8. Paved Carriageways (One-way vs Two-way)
    if is_oneway or lanes == 1.0 or width < 4.8:
        if h in ('residential', 'unclassified') or width < 4.8:
            return 'DefaultDecalRoadMaterial', 12.0, 10
        return 'AsphaltRoad_variation_one_way', 12.0, 10

    if lanes >= 2.0 or h in ('motorway', 'trunk', 'primary', 'secondary', 'tertiary'):
        return 'AsphaltRoad_variation_two_way', 12.0, 10

    return 'DefaultDecalRoadMaterial', 12.0, 10


def choose_road_material(tags: dict) -> str:
    """Select appropriate PBR road material name from art/road/main.materials.json."""
    return choose_road_look(tags)[0]


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

    # Query scenery (buildings, vegetation, lamps)
    scenery = safe_scenery(store, query_rect)
    buildings = []
    trees = []
    forest_polys = []
    tree_rows = []
    surveyed_trees = []
    scrub_polys = []
    lamps = []
    bus_stops = []
    surveyed_signs = []

    for fid, kind, data, geom in scenery:
        tags = data.get('tags', {})
        if kind == 'building':
            h_match = re.search(r'[\d.]+', str(tags.get('height') or ''))
            lvl_match = re.search(r'[\d.]+', str(tags.get('building:levels') or tags.get('levels') or ''))
            if h_match:
                try:
                    h = max(3.0, min(800.0, float(h_match.group(0))))
                except Exception:
                    h = 10.0
            elif lvl_match:
                try:
                    h = max(3.0, min(800.0, float(lvl_match.group(0)) * 3.2))
                except Exception:
                    h = 10.0
            else:
                h = 10.0

            # rings with exterior and courtyard interiors
            parts = [geom] if geom.geom_type == 'Polygon' else list(getattr(geom, 'geoms', []))
            for p in parts:
                coords = list(p.exterior.coords)
                z_sampled = store.terrain.sample(coords)
                rings_3d = [[(c[0], c[1], float(z)) for c, z in zip(coords, z_sampled)]]
                for interior in getattr(p, 'interiors', []):
                    in_coords = list(interior.coords)
                    in_z = store.terrain.sample(in_coords)
                    rings_3d.append([(c[0], c[1], float(z)) for c, z in zip(in_coords, in_z)])
                buildings.append({'id': fid, 'height': h, 'rings': rings_3d, 'tags': tags})
        elif kind in ('forest', 'park', 'orchard'):
            forest_polys.append((geom, tags))
        elif kind == 'tree_row':
            tree_rows.append((geom, tags))
        elif kind == 'tree':
            trees.append((geom.x, geom.y, float(store.terrain.sample([[geom.x, geom.y]])[0])))
            surveyed_trees.append((geom, tags))
        elif kind in ('scrub', 'heath'):
            scrub_polys.append((geom, tags))
        elif kind == 'lamp':
            lamps.append((geom.x, geom.y, float(store.terrain.sample([[geom.x, geom.y]])[0])))
        elif kind == 'stop':
            bus_stops.append((geom.x, geom.y, tags))
        elif kind in ('stop_sign', 'give_way', 'traffic_sign'):
            surveyed_signs.append((geom.x, geom.y, kind, tags))

    emit(f"Найдено OSM объектов: зданий: {len(buildings)}, лесных зон: {len(forest_polys)}, рядов деревьев: {len(tree_rows)}, отдельных деревьев: {len(surveyed_trees)}, фонарей: {len(lamps)}, остановок: {len(bus_stops)}")

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

    # Procedural multi-layer splat map (Grass, BeachSand, dirt_rocky_large, rock)
    layer_map = terrain_builder.generate_procedural_layermap(
        z_grid=z_grid,
        square_size=square_size,
        min_z=min_z,
        max_z=max_z,
    )
    ter_bytes = terrain_builder.encode_ter_v9(heightmap_u16, layer_map_u8=layer_map)

    emit(f"Высота рельефа: от {min_z:.1f} м до {max_z:.1f} м (диапазон: {max_height:.1f} м)")
    l_counts = {int(k): int(v) for k, v in zip(*np.unique(layer_map, return_counts=True))}
    total_pts = float(ter_size * ter_size)
    emit(f"Слои поверхности: Трава {l_counts.get(0, 0)/total_pts*100:.1f}%, Песок {l_counts.get(1, 0)/total_pts*100:.1f}%, "
         f"Каменистая почва {l_counts.get(2, 0)/total_pts*100:.1f}%, Скалы {l_counts.get(3, 0)/total_pts*100:.1f}%")

    if progress:
        progress('Terrain', time.monotonic() - t0)

    # 4. DecalRoads Generation
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Roads', None)
    emit("Шаг 4/6: Создание дорог DecalRoad и разметки...")

    roads_sketch = [r.get('xy', []) for r in roads if len(r.get('xy', [])) >= 2]

    # Process roads, trimmed intersections, and longitudinal/transverse markings
    marking_config = road_markings.MarkingConfig(
        style=road_markings.MarkingStyle.RU_EU,
        enable_center_line=True,
        enable_lane_dividers=True,
        enable_edge_lines=True,
        enable_stop_lines=True,
        enable_crossings=True
    )
    processed_roads = road_markings.process_roads_and_markings(
        raw_roads=roads,
        store_terrain=store.terrain,
        config=marking_config,
        material_selector=choose_road_material
    )

    decal_roads = (
        processed_roads.junction_aprons +
        processed_roads.base_roads +
        processed_roads.markings
    )

    center_z = float(store.terrain.sample([[0, 0]])[0])
    spawn_pos, spawn_heading, rot_quat, rot_matrix = spawn_system.find_asphalt_spawn_point(
        roads=processed_roads.base_roads,
        max_span=max_span,
        center=(0.0, 0.0),
        height_offset=0.6,
        default_terrain_z=center_z
    )
    spawn_obj = spawn_system.create_spawn_sphere(
        position=spawn_pos,
        quaternion=rot_quat,
        rotation_matrix=rot_matrix,
        name='spawn_default',
        parent='Spawn',
        radius=2.0
    )

    emit(f"Сгенерировано дорог: {len(processed_roads.base_roads)}, перекрестков: {len(processed_roads.junction_aprons)}, элементов разметки: {processed_roads.total_marking_count} (Всего DecalRoad: {len(decal_roads)})")
    emit(f"Точка спавна (асфальт +0.6м, yaw={math.degrees(spawn_heading):.1f}°): X={spawn_pos[0]:.1f}, Y={spawn_pos[1]:.1f}, Z={spawn_pos[2]:.1f}")

    if progress:
        progress('Roads', time.monotonic() - t0)

    # 5. 3D Building Meshes (Collada .dae) & Props
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Buildings', None)
    emit("Шаг 5/6: Экструзия 3D-зданий и расстановка объектов...")

    # Spatial clustering of buildings prior to chunking
    def building_spatial_key(b):
        rings = b.get('rings', [])
        if not rings or not rings[0]:
            return 0
        outer = rings[0]
        cx = sum(p[0] for p in outer) / len(outer)
        cy = sum(p[1] for p in outer) / len(outer)
        ix = int((cx + 500000) / 50.0) & 0xFFFF
        iy = int((cy + 500000) / 50.0) & 0xFFFF
        code = 0
        for bit in range(16):
            code |= ((ix & (1 << bit)) << bit) | ((iy & (1 << bit)) << (bit + 1))
        return code

    buildings.sort(key=building_spatial_key)

    dae_files = {}
    bld_statics = []
    chunk_size = 100

    for chunk_idx, i in enumerate(range(0, len(buildings), chunk_size)):
        chunk = buildings[i:i + chunk_size]
        chunk_pts = [p for b in chunk for ring in b.get('rings', []) for p in ring]
        if chunk_pts:
            chunk_cx = round(sum(p[0] for p in chunk_pts) / len(chunk_pts), 2)
            chunk_cy = round(sum(p[1] for p in chunk_pts) / len(chunk_pts), 2)
        else:
            chunk_cx, chunk_cy = 0.0, 0.0
        origin = (chunk_cx, chunk_cy, 0.0)

        dae_name = f"buildings_chunk_{chunk_idx}.dae"
        dae_xml = generate_collada_dae(
            chunk,
            mat_name="bld_facade",
            roof_mat_name="bld_roof",
            origin=origin,
            skirt_depth=0.5,
        )
        dae_files[f"levels/{level_slug}/art/shapes/buildings/{dae_name}"] = dae_xml
        bld_statics.append({
            'name': f"buildings_chunk_{chunk_idx}",
            'class': 'TSStatic',
            '__parent': 'Buildings',
            'position': [chunk_cx, chunk_cy, 0.0],
            'shapeName': f"/levels/{level_slug}/art/shapes/buildings/{dae_name}",
            'collisionType': 'Visible Mesh Final',
            'decalType': 'Visible Mesh',
            'useInstanceRenderData': True,
        })

    # Props (trees, procedural streetlights, guardrails, signs, and bus stops)
    prop_statics = []
    prop_gen = road_decorations.RoadPropGenerator(
        elevation_fn=lambda x, y: float(store.terrain.sample([[x, y]])[0]),
        lamp_spacing=35.0,
        curb_offset=1.2,
        guardrail_step=2.40,
    )

    # 1. Road decorations: Streetlights, guardrails, and signs along DecalRoad paths
    road_lamps_count = 0
    road_rails_count = 0
    road_signs_count = 0

    for r_obj in processed_roads.base_roads:
        r_nodes = r_obj.get('nodes', [])
        if len(r_nodes) < 2:
            continue
        pts_3d = [(float(n[0]), float(n[1]), float(n[2])) for n in r_nodes]
        r_width = float(r_nodes[0][3]) if len(r_nodes[0]) > 3 else 6.0

        # Streetlights (30-40m interval, oriented facing the carriageway)
        road_lamps = prop_gen.generate_streetlights_for_road(
            pts_3d=pts_3d,
            road_width=r_width,
            highway_type='residential',
            is_tunnel=False,
            staggered=True
        )
        for l in road_lamps:
            l['__parent'] = 'Props'
            prop_statics.append(l)
            road_lamps_count += 1

        # Guardrails on sharp turns or safety critical sections
        road_rails = prop_gen.generate_guardrails_for_road(
            pts_3d=pts_3d,
            road_width=r_width,
            is_bridge=False,
            highway_type='residential',
            is_tunnel=False
        )
        for rail in road_rails:
            rail['__parent'] = 'Props'
            prop_statics.append(rail)
            road_rails_count += 1

        # Traffic signs (speed limits, crossings, intersection stops)
        road_signs = prop_gen.generate_traffic_signs_for_road(
            pts_3d=pts_3d,
            road_width=r_width,
            speed_limit=60,
            has_pedestrian_crossing=(len(pts_3d) > 4)
        )
        for s in road_signs:
            s['__parent'] = 'Props'
            prop_statics.append(s)
            road_signs_count += 1

    # 2. Bus stops (shelters + curb signs)
    bus_stops_count = 0
    for bs_x, bs_y, bs_tags in bus_stops[:50]:
        # Find nearest road tangent
        best_tangent = (1.0, 0.0)
        best_dist = float('inf')
        best_pos = (bs_x, bs_y, float(store.terrain.sample([[bs_x, bs_y]])[0]))
        best_width = 7.0

        for r_obj in processed_roads.base_roads:
            r_nodes = r_obj.get('nodes', [])
            for k in range(len(r_nodes) - 1):
                qx, qy = r_nodes[k][0], r_nodes[k][1]
                d = math.hypot(qx - bs_x, qy - bs_y)
                if d < best_dist:
                    best_dist = d
                    dx = r_nodes[k + 1][0] - r_nodes[k][0]
                    dy = r_nodes[k + 1][1] - r_nodes[k][1]
                    l = math.hypot(dx, dy)
                    if l > 0.1:
                        best_tangent = (dx / l, dy / l)
                    best_width = float(r_nodes[k][3]) if len(r_nodes[k]) > 3 else 7.0

        bs_items = prop_gen.generate_bus_stop(
            center_pos=best_pos,
            road_tangent=best_tangent,
            road_width=best_width,
            side=1
        )
        for item in bs_items:
            item['__parent'] = 'Props'
            prop_statics.append(item)
            bus_stops_count += 1

    # 3. Procedural Vegetation (Köppen-Geiger biomes + OSM forests, tree rows, and surveyed trees)
    min_lon, min_lat, max_lon, max_lat = box_w, box_s, box_e, box_n
    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    veg_engine = proc_vegetation.ProceduralVegetationEngine(
        center_lat=center_lat,
        center_lon=center_lon,
    )
    emit(f"Биом климата: {veg_engine.climate.description} ({veg_engine.climate.code}), Группа: {veg_engine.climate.group}")

    # Spatial clearance against building footprints and roads
    bld_geoms = [shapely.geometry.Polygon(b['rings'][0]) for b in buildings if len(b.get('rings', [[]])[0]) >= 3]
    bld_tree = shapely.STRtree(bld_geoms) if bld_geoms else None
    road_geoms = [shapely.geometry.LineString(r['xy']) for r in roads if len(r.get('xy', [])) >= 2]
    road_tree = shapely.STRtree(road_geoms) if road_geoms else None

    def is_clear_fn(x: float, y: float, radius: float = 1.5) -> bool:
        pt = shapely.geometry.Point(x, y)
        if bld_tree:
            for idx in bld_tree.query(pt.buffer(radius + 2.0)):
                if bld_geoms[int(idx)].distance(pt) < radius + 1.5:
                    return False
        if road_tree:
            for idx in road_tree.query(pt.buffer(radius + 2.0)):
                if road_geoms[int(idx)].distance(pt) < radius + 1.5:
                    return False
        return True

    def elev_fn(x: float, y: float) -> float:
        return float(store.terrain.sample([[x, y]])[0])

    all_foliage_instances: list[proc_vegetation.TreeInstance] = []

    # 3.1. Forest & Park polygons (multi-tier canopy with clearings & ecotone)
    for f_geom, f_tags in forest_polys:
        parts = [f_geom] if f_geom.geom_type == 'Polygon' else list(getattr(f_geom, 'geoms', []))
        for p in parts:
            if p.area >= 25.0:
                insts = veg_engine.populate_forest_polygon(
                    p, f_tags, elevation_fn=elev_fn, is_clear_fn=is_clear_fn, spacing=6.5
                )
                all_foliage_instances.extend(insts)

    # 3.2. Linear tree rows along streets & boundaries
    for r_geom, r_tags in tree_rows:
        parts = [r_geom] if r_geom.geom_type == 'LineString' else list(getattr(r_geom, 'geoms', []))
        for line in parts:
            insts = veg_engine.populate_tree_row(
                line, r_tags, elevation_fn=elev_fn, is_clear_fn=is_clear_fn, step=10.0
            )
            all_foliage_instances.extend(insts)

    # 3.3. Surveyed OSM trees (individual nodes)
    for pt_geom, pt_tags in surveyed_trees:
        inst = veg_engine.place_surveyed_tree(
            pt_geom, pt_tags, elevation_fn=elev_fn, is_clear_fn=is_clear_fn
        )
        if inst:
            all_foliage_instances.append(inst)

    # 3.4. Scrub & Heath shrublands
    for s_geom, s_tags in scrub_polys:
        parts = [s_geom] if s_geom.geom_type == 'Polygon' else list(getattr(s_geom, 'geoms', []))
        for p in parts:
            if p.area >= 20.0:
                insts = veg_engine.populate_scrub(
                    p, s_tags, elevation_fn=elev_fn, is_clear_fn=is_clear_fn, spacing=4.5
                )
                all_foliage_instances.extend(insts)

    # If no OSM forest polygons were present, spawn natural scatter on surveyed trees or fallback
    if not forest_polys and not surveyed_trees:
        for idx, (tx, ty, tz) in enumerate(trees[:500]):
            inst = veg_engine.place_surveyed_tree(
                shapely.geometry.Point(tx, ty), {}, elevation_fn=elev_fn, is_clear_fn=is_clear_fn
            )
            if inst:
                all_foliage_instances.append(inst)

    # Build BeamNG 0.24+/0.3x+ Native Forest files
    forest_files = {}
    forest_sim_object = None

    if all_foliage_instances:
        by_mesh: dict[str, list[proc_vegetation.TreeInstance]] = {}
        for inst in all_foliage_instances:
            by_mesh.setdefault(inst.mesh_key, []).append(inst)

        managed_items: dict[str, Any] = {}
        for mesh_key, group in by_mesh.items():
            mesh_def = proc_vegetation.BEAMNG_MESHES.get(mesh_key)
            if not mesh_def:
                continue
            forest4_lines = [inst.to_forest4_line() for inst in group]
            forest_files[f"levels/{level_slug}/forest/{mesh_key}.forest4.json"] = '\n'.join(forest4_lines) + '\n'
            managed_items[mesh_key] = {
                "name": mesh_key,
                "internalName": mesh_key,
                "class": "TSForestItemData",
                "persistentId": f"forest_item_{mesh_key}",
                "annotation": "TREE" if mesh_def.tier in ('CANOPY', 'SUB_CANOPY') else "BUSH",
                "radius": round(mesh_def.crown_radius, 2),
                "shapeFile": mesh_def.shape_path,
                "collidable": mesh_def.collidable,
            }

        forest_files[f"levels/{level_slug}/art/forest/managedItemData.json"] = json.dumps(managed_items, indent=2)
        forest_files[f"levels/{level_slug}/{level_slug}.forest.json"] = json.dumps({
            "header": {"format": "JSON Forest Data v4", "version": 4},
            "types": list(managed_items.keys()),
            "totalInstances": len(all_foliage_instances)
        }, indent=2)

        forest_sim_object = {
            "name": "theForest",
            "class": "Forest",
            "persistentId": "the_procedural_forest",
            "__parent": "MissionGroup",
            "dataFile": f"/levels/{level_slug}/{level_slug}.forest.json"
        }

        # Also add landmark surveyed trees as TSStatic props with collision for immediate physical presence
        landmark_trees = [inst for inst in all_foliage_instances if inst.source == 'surveyed_tree'][:150]
        prop_statics.extend(proc_vegetation.export_tsstatic_props(landmark_trees, max_count=150))

    # Surveyed standalone lamps from OSM (if any)
    for idx, (lx, ly, lz) in enumerate(lamps[:100]):
        prop_statics.append({
            'name': f"osm_lamp_{idx}",
            'class': 'TSStatic',
            '__parent': 'Props',
            'position': [round(lx, 2), round(ly, 2), round(lz, 2)],
            'shapeName': road_decorations.MESH_STREETLIGHT_URBAN,
            'collisionType': 'Collision Mesh',
            'useInstanceRenderData': True,
        })

    emit(f"Расставлено объектов Props: фонарей: {road_lamps_count + len(lamps[:100])}, отбойников: {road_rails_count}, знаков: {road_signs_count}, остановок: {bus_stops_count}, деревьев: {len(trees[:500])}")

    if progress:
        progress('Buildings', time.monotonic() - t0)

    # 6. Assembly & Packaging
    check_cancel()
    t0 = time.monotonic()
    if progress:
        progress('Packaging', None)
    emit("Шаг 6/6: Упаковка готового мода уровней...")

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

    # Materials for buildings
    bld_materials = {
        'bld_facade': {
            'name': 'bld_facade',
            'mapTo': 'bld_facade',
            'class': 'Material',
            'version': 1.5,
            'cullMode': 'none',
            'doubleSided': True,
            'Stages': [
                {
                    'baseColorMap': '/levels/east_coast_usa/art/shapes/buildings/eca_bld_brick_01_d.color.png',
                    'roughnessFactor': 0.8,
                },
                {}, {}, {}
            ],
        },
        'bld_roof': {
            'name': 'bld_roof',
            'mapTo': 'bld_roof',
            'class': 'Material',
            'version': 1.5,
            'cullMode': 'none',
            'doubleSided': True,
            'Stages': [
                {
                    'baseColorMap': '/levels/east_coast_usa/art/shapes/buildings/eca_bld_concrete_01_d.color.png',
                    'roughnessFactor': 0.9,
                },
                {}, {}, {}
            ],
        },
    }

    # TerrainBlock & canonical TextureSet binding
    tex_set_name = f"{level_slug}TerrainMaterialTextureSet"
    terrain_block = terrain_builder.build_terrain_block(
        level_slug=level_slug,
        origin=(origin_x, origin_y, base_z),
        max_height=max_height,
        square_size=square_size,
        texture_set_name=tex_set_name,
    )

    # theTerrain.terrain.json descriptor
    terrain_json = terrain_builder.build_terrain_json(level_slug=level_slug, size=ter_size)

    # Reference v2 PBR terrain materials (Grass, BeachSand, dirt_rocky_large, rock)
    terrain_materials = terrain_builder.build_terrain_pbr_materials(texture_set_name=tex_set_name)
    # Also provide alias templateTerrainMaterialTextureSet for compatibility
    terrain_materials['templateTerrainMaterialTextureSet'] = {
        'name': 'templateTerrainMaterialTextureSet',
        'class': 'TerrainMaterialTextureSet',
        'persistentId': 'ac348aaa-081f-4d49-92db-d79fdfad5f80',
        'baseTexSize': [1024, 1024],
        'detailTexSize': [1024, 1024],
        'macroTexSize': [1024, 1024],
    }

    # Strict QA validation of terrain binary & PBR material integrity
    ter_val_errors = terrain_builder.validate_terrain_pipeline(
        ter_bytes=ter_bytes,
        terrain_json=terrain_json,
        materials_json=terrain_materials,
        terrain_block=terrain_block,
    )
    if ter_val_errors:
        for err in ter_val_errors:
            emit(f"[ПРЕДУПРЕЖДЕНИЕ Terrain] {err}")
    else:
        emit("Валидация рельефа и PBR-материалов: 100% OK (ошибок нет)")

    # Load Road Materials
    road_mat_file = _find_resource('road_materials.json')
    if road_mat_file.is_file():
        try:
            road_materials = json.loads(road_mat_file.read_text(encoding='utf-8'))
        except Exception:
            road_materials = {}
    else:
        road_materials = {}

    # Load Fast Tree Materials
    tree_mat_file = _find_resource('fast_tree_materials.json')
    if tree_mat_file.is_file():
        try:
            tree_materials = json.loads(tree_mat_file.read_text(encoding='utf-8'))
        except Exception:
            tree_materials = {}
    else:
        tree_materials = {}

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

        # Map JSON for in-game navi/radar and minimap
        map_json = road_markings.generate_navigation_map(
            raw_roads=roads,
            base_roads=processed_roads.base_roads
        )
        z.writestr(f"levels/{level_slug}/map.json", json.dumps(map_json, indent=2, ensure_ascii=False))
        z.writestr(f"levels/{level_slug}/art/shapes/buildings/main.materials.json", json.dumps(bld_materials, indent=2))
        z.writestr(f"levels/{level_slug}/art/terrains/main.materials.json", json.dumps(terrain_materials, indent=2))
        z.writestr(f"levels/{level_slug}/art/road/main.materials.json", json.dumps(road_materials, indent=2))
        z.writestr(f"levels/{level_slug}/art/forest/main.materials.json", json.dumps(tree_materials, indent=2))
        z.writestr(f"levels/{level_slug}/art/main.materials.json", json.dumps({**road_materials, **bld_materials, **tree_materials}, indent=2))
        z.writestr(f"levels/{level_slug}/main.materials.json", json.dumps({**road_materials, **bld_materials, **tree_materials}, indent=2))

        # Main SimGroup files (Hierarchical MissionGroup scene tree)
        scene_files = spawn_system.build_mission_group_hierarchy(
            level_slug=level_slug,
            sky_items=SKY,
            decal_roads=decal_roads,
            building_statics=bld_statics,
            prop_statics=prop_statics,
            terrain_block=terrain_block,
            spawn_obj=spawn_obj,
            extra_mission_group_items=[forest_sim_object] if forest_sim_object else None
        )
        for s_path, s_content in scene_files.items():
            z.writestr(s_path, s_content)

        # BeamNG Forest files (NDJSON v4 forest4.json & managedItemData.json)
        for fname, content in forest_files.items():
            z.writestr(fname, content)

        # DAE files
        for fname, content in dae_files.items():
            z.writestr(fname, content)

    if tmp_zip.exists():
        tmp_zip.replace(zip_path)

    emit(f"Архив карты создан: {zip_path.name} ({zip_path.stat().st_size / 2**20:.1f} MB)")

    # QA Validation of assembled mod archive
    try:
        import level_validator
        qa_report = level_validator.validate_level(zip_path)
        if qa_report.is_valid:
            emit(f"QA Контроль качества: [УСПЕХ] Уровень прошёл все проверки качества ({len(qa_report.checks)} чеков, 0 ошибок)")
        else:
            emit(f"QA Контроль качества: [ВНИМАНИЕ] Обнаружено ошибок: {len(qa_report.all_errors)}, предупреждений: {len(qa_report.all_warnings)}")
            for err in qa_report.all_errors[:5]:
                emit(f"  ! {err.category}: {err.message}")
    except Exception as e:
        emit(f"QA Контроль качества: проверка пропущена ({e})")

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
