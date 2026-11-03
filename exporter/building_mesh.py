"""
Procedural 3D Building Extrusion and Collada Mesh Generator for BeamNG.drive.
Generates realistic multi-story architectural buildings from OSM footprints with:
- Collinear and duplicate vertex simplification (clean_ring)
- Ear-clipping triangulation for roof surfaces
- Floor-by-floor wall extrusion with UV coordinates aligned to BeamNG facade atlases
- Architectural roof cornices and parapets
- Deep foundation skirts (-3.0m below lowest ground point) preventing floating buildings on slopes
- Collada (.dae) mesh generation with sector grouping and solid collision geometry
"""

import math
import pathlib
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import triangulate as shapely_triangulate


# BeamNG highrise plaster atlas parameters (1024x1024)
# 4 bands: 0: tall windows, 1: square windows, 2: sash windows on plaster, 3: sash on red brick
BANDS_PER_1024 = [3, 4, 5, 5]
TILE_PX_M = 12.0
CORNICE_OUT_M = 0.28
CORNICE_DOWN_M = 0.45
CORNICE_UP_M = 0.20
SKIRT_DEPTH_M = 3.0


def clean_ring(
    pts: List[Tuple[float, float]],
    tol: float = 0.35,
    max_verts: int = 64,
) -> Optional[List[Tuple[float, float]]]:
    """
    Cleans and simplifies a 2D polygon ring:
    - Removes closing duplicate vertex
    - Ensures counter-clockwise (CCW) winding
    - Filters degenerate/tiny polygons (< 12 m2)
    - Removes collinear and nearly redundant vertices
    """
    if len(pts) < 3:
        return None

    ring = [tuple(p) for p in pts]
    # Remove duplicate closing point
    if math.hypot(ring[0][0] - ring[-1][0], ring[0][1] - ring[-1][1]) < 1e-4:
        ring.pop()

    if len(ring) < 3:
        return None

    # Calculate signed area
    n = len(ring)
    area2 = sum(
        ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1]
        for i in range(n)
    )
    if abs(area2) < 24.0:  # Area < 12 m2
        return None

    # Ensure CCW orientation (positive signed area)
    if area2 < 0:
        ring = ring[::-1]

    # Iterative collinear simplification
    curr_tol = tol
    for _ in range(8):
        m = len(ring)
        if m <= 3:
            break

        drop = [False] * m
        any_drop = False
        for i in range(m):
            prev_p = ring[(i - 1 + m) % m]
            curr_p = ring[i]
            next_p = ring[(i + 1) % m]

            dx = next_p[0] - prev_p[0]
            dy = next_p[1] - prev_p[1]
            seg_len = math.hypot(dx, dy)
            if seg_len < 1e-4:
                drop[i] = True
                any_drop = True
                continue

            # Perpendicular distance from curr_p to line segment (prev_p -> next_p)
            dist = abs(dx * (curr_p[1] - prev_p[1]) - dy * (curr_p[0] - prev_p[0])) / seg_len
            near = math.hypot(curr_p[0] - prev_p[0], curr_p[1] - prev_p[1]) < 0.08

            if dist < curr_tol or near:
                drop[i] = True
                any_drop = True

        if not any_drop:
            if m <= max_verts:
                break
            curr_tol *= 1.5
            continue

        # Drop every other candidate to preserve shape geometry smoothly
        keep = []
        k = 0
        for i in range(m):
            if drop[i]:
                if k % 2 == 1:
                    keep.append(ring[i])
                k += 1
            else:
                keep.append(ring[i])
        ring = keep

    return ring if len(ring) >= 3 else None


def triangulate(pts: List[Tuple[float, float]]) -> List[Tuple[int, int, int]]:
    """
    Ear-clipping triangulation for a counter-clockwise simple 2D polygon.
    Returns list of vertex index triangles [(i0, i1, i2), ...].
    Falls back to Shapely triangulation if needed for degenerate shapes.
    """
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def in_tri(p, a, b, c):
        return cross(a, b, p) >= -1e-7 and cross(b, c, p) >= -1e-7 and cross(c, a, p) >= -1e-7

    idx = list(range(n))
    tris = []
    guard = 0
    max_steps = 4 * n * n

    while len(idx) > 3 and guard < max_steps:
        guard += 1
        m = len(idx)
        found = False
        for k in range(m):
            i0 = idx[(k + m - 1) % m]
            i1 = idx[k]
            i2 = idx[(k + 1) % m]
            pa, pb, pc = pts[i0], pts[i1], pts[i2]

            # Ear must be convex (strictly CCW)
            if cross(pa, pb, pc) <= 1e-9:
                continue

            # Ear triangle must contain no other polygon vertices
            is_ear = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                if in_tri(pts[j], pa, pb, pc):
                    is_ear = False
                    break

            if is_ear:
                tris.append((i0, i1, i2))
                idx.pop(k)
                found = True
                break

        if not found:
            break

    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))

    # Fallback to Shapely if ear-clipping got stuck
    if len(tris) < n - 2:
        try:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            buffered = poly.buffer(1e-4)
            sh_tris = shapely_triangulate(poly)
            fallback_tris = []
            for tri in sh_tris:
                if buffered.contains(tri.centroid):
                    tri_coords = list(tri.exterior.coords)[:3]
                    t_indices = []
                    for tc in tri_coords:
                        best_idx = 0
                        best_d = float("inf")
                        for pi, p in enumerate(pts):
                            d = math.hypot(tc[0] - p[0], tc[1] - p[1])
                            if d < best_d:
                                best_d = d
                                best_idx = pi
                        t_indices.append(best_idx)
                    if len(set(t_indices)) == 3:
                        fallback_tris.append(tuple(t_indices))
            if len(fallback_tris) >= len(tris):
                return fallback_tris
        except Exception:
            pass

    return tris


class ProceduralBuildingMesh:
    """Accumulates visual and collision geometry for a cluster of procedural buildings."""

    def __init__(self):
        self.verts: List[Tuple[float, float, float]] = []
        self.normals: List[Tuple[float, float, float]] = []
        self.uvs: List[Tuple[float, float]] = []
        self.triangles_by_mat: Dict[str, List[int]] = {
            "facade_plaster": [],
            "roof_gravel": [],
            "roof_tiles": [],
            "facade_brick": [],
        }
        self.col_verts: List[Tuple[float, float, float]] = []
        self.col_triangles: List[int] = []

    def add_quad(
        self,
        mat: str,
        p0: Tuple[float, float, float],
        p1: Tuple[float, float, float],
        p2: Tuple[float, float, float],
        p3: Tuple[float, float, float],
        uv0: Tuple[float, float],
        uv1: Tuple[float, float],
        uv2: Tuple[float, float],
        uv3: Tuple[float, float],
        norm: Tuple[float, float, float],
    ):
        start = len(self.verts)
        self.verts.extend([p0, p1, p2, p3])
        self.normals.extend([norm, norm, norm, norm])
        self.uvs.extend([uv0, uv1, uv2, uv3])
        if mat not in self.triangles_by_mat:
            self.triangles_by_mat[mat] = []
        self.triangles_by_mat[mat].extend([
            start, start + 1, start + 2,
            start, start + 2, start + 3,
        ])

    def add_col_quad(
        self,
        p0: Tuple[float, float, float],
        p1: Tuple[float, float, float],
        p2: Tuple[float, float, float],
        p3: Tuple[float, float, float],
    ):
        start = len(self.col_verts)
        self.col_verts.extend([p0, p1, p2, p3])
        self.col_triangles.extend([
            start, start + 1, start + 2,
            start, start + 2, start + 3,
        ])

    def extrude_building(
        self,
        ring: List[Tuple[float, float]],
        base_z: float,
        z_base: float,
        z_eave: float,
        floors: int,
        floor_h: float,
        band_idx: int = 2,
        is_house: bool = False,
    ):
        """
        Extrudes a building from its foundation skirt up to its roof with architectural details:
        - Deep foundation skirt down to z_base (-3.0m under lowest terrain point)
        - Floor by floor walls with UV window bays matching BeamNG highrise plaster atlas
        - Roof: Pitched gabled roof for cottages/houses, or flat gravel roof with parapet for highrises
        - Solid collision hull
        """
        n = len(ring)
        bpt = BANDS_PER_1024[band_idx % 4]
        bay_w = TILE_PX_M / bpt

        # UV V coordinates for the selected band
        eps = 2.0 / 1024.0
        v_bottom = 1.0 - (band_idx + 1) / 4.0 + eps
        v_top = 1.0 - band_idx / 4.0 - eps

        wall_mat = "facade_brick" if band_idx == 3 else "facade_plaster"
        roof_mat = "roof_tiles" if is_house else "roof_gravel"

        # 1. Extrude walls per floor and foundation skirt
        for i in range(n):
            a = ring[i]
            b = ring[(i + 1) % n]
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            l = math.hypot(dx, dy)
            if l < 0.1:
                continue

            d = (dx / l, dy / l)
            norm = (d[1], -d[0], 0.0)  # Outward normal for CCW polygon

            # Exact whole number of window bays along wall
            nb = max(1, int(round(l / bay_w)))
            u_max = nb / bpt

            # Floor by floor walls
            for f in range(floors):
                zf0 = base_z + f * floor_h
                zf1 = base_z + (f + 1) * floor_h if f < floors - 1 else z_eave
                self.add_quad(
                    wall_mat,
                    (a[0], a[1], zf0),
                    (b[0], b[1], zf0),
                    (b[0], b[1], zf1),
                    (a[0], a[1], zf1),
                    (0.0, v_bottom),
                    (u_max, v_bottom),
                    (u_max, v_top),
                    (0.0, v_top),
                    norm,
                )

            # Foundation skirt below base_z down to z_base
            skirt_h = base_z - z_base
            u_skirt = max(1, int(round(l / 3.0)))
            # Sample neutral plaster trim band to avoid underground windows
            v_sk_b = 0.990
            v_sk_t = 0.998
            self.add_quad(
                "facade_plaster",
                (a[0], a[1], z_base),
                (b[0], b[1], z_base),
                (b[0], b[1], base_z),
                (a[0], a[1], base_z),
                (0.0, v_sk_b),
                (u_skirt, v_sk_b),
                (u_skirt, v_sk_t),
                (0.0, v_sk_t),
                norm,
            )

            # Collision wall quad
            self.add_col_quad(
                (a[0], a[1], z_base),
                (b[0], b[1], z_base),
                (b[0], b[1], z_eave),
                (a[0], a[1], z_eave),
            )

        # 2. Roof surface and architecture
        if is_house:
            self._add_pitched_roof(ring, z_eave, wall_mat, roof_mat)
        else:
            self._add_flat_roof_and_parapet(ring, z_eave, roof_mat)

        # 3. Bottom skirt collision cap (facing down)
        col_bot_start = len(self.col_verts)
        for p in ring:
            self.col_verts.append((p[0], p[1], z_base))
        roof_tris = triangulate(ring)
        for ia, ib, ic in roof_tris:
            self.col_triangles.extend([
                col_bot_start + ic, col_bot_start + ib, col_bot_start + ia,
            ])

    def _add_pitched_roof(
        self,
        ring: List[Tuple[float, float]],
        z_eave: float,
        wall_mat: str,
        roof_mat: str = "roof_tiles",
    ):
        """
        Generates realistic pitched/gabled roof for cottages and residential houses:
        - 4-vertex rectangular footprint: classic gabled roof with triangular wall gables
        - N-vertex footprint: hipped roof with elevated ridge/apex
        - UV mapping scaled to realistic roof tile dimensions (~2.0m tile repeat)
        - Synchronized collision geometry
        """
        n = len(ring)
        if n < 3:
            return

        cx = sum(p[0] for p in ring) / n
        cy = sum(p[1] for p in ring) / n
        poly_area = 0.5 * abs(sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n)))

        # Pitch height ~2.0m - 3.5m (pitch angle ~25-35 degrees)
        min_dim = math.sqrt(max(16.0, poly_area))
        pitch_h = min(4.0, max(2.2, min_dim * 0.30))
        z_ridge = z_eave + pitch_h
        tile_scale = 2.0  # 2.0m per tile repeat

        def add_roof_tri(mat, va, vb, vc):
            ab = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
            ac = (vc[0] - va[0], vc[1] - va[1], vc[2] - va[2])
            nx = ab[1] * ac[2] - ab[2] * ac[1]
            ny = ab[2] * ac[0] - ab[0] * ac[2]
            nz = ab[0] * ac[1] - ab[1] * ac[0]
            nl = math.hypot(nx, ny, nz)
            norm = (nx / nl, ny / nl, nz / nl) if nl > 1e-6 else (0.0, 0.0, 1.0)

            start = len(self.verts)
            self.verts.extend([va, vb, vc])
            self.normals.extend([norm, norm, norm])
            self.uvs.extend([
                (va[0] / tile_scale, va[1] / tile_scale),
                (vb[0] / tile_scale, vb[1] / tile_scale),
                (vc[0] / tile_scale, vc[1] / tile_scale),
            ])
            if mat not in self.triangles_by_mat:
                self.triangles_by_mat[mat] = []
            self.triangles_by_mat[mat].extend([start, start + 1, start + 2])

            col_start = len(self.col_verts)
            self.col_verts.extend([va, vb, vc])
            self.col_triangles.extend([col_start, col_start + 1, col_start + 2])

        if n == 4:
            # Rectangular footprint: Classic Gabled Roof with 2 slopes and 2 vertical wall gables
            p0, p1, p2, p3 = ring[0], ring[1], ring[2], ring[3]
            l01 = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            l12 = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            l23 = math.hypot(p3[0] - p2[0], p3[1] - p2[1])
            l30 = math.hypot(p0[0] - p3[0], p0[1] - p3[1])

            avg_l0 = (l01 + l23) / 2.0
            avg_l1 = (l12 + l30) / 2.0

            p0_eave = (p0[0], p0[1], z_eave)
            p1_eave = (p1[0], p1[1], z_eave)
            p2_eave = (p2[0], p2[1], z_eave)
            p3_eave = (p3[0], p3[1], z_eave)

            if avg_l0 >= avg_l1:
                # Longer axis along edge 0 (p0->p1) and edge 2 (p2->p3)
                m1 = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0, z_ridge)
                m3 = ((p3[0] + p0[0]) / 2.0, (p3[1] + p0[1]) / 2.0, z_ridge)

                # Roof Slope 1 (over edge 0)
                add_roof_tri(roof_mat, p0_eave, p1_eave, m1)
                add_roof_tri(roof_mat, p0_eave, m1, m3)

                # Roof Slope 2 (over edge 2)
                add_roof_tri(roof_mat, p2_eave, p3_eave, m3)
                add_roof_tri(roof_mat, p2_eave, m3, m1)

                # Gable 1 (vertical triangular wall over edge 1)
                add_roof_tri(wall_mat, p1_eave, p2_eave, m1)

                # Gable 2 (vertical triangular wall over edge 3)
                add_roof_tri(wall_mat, p3_eave, p0_eave, m3)
            else:
                # Longer axis along edge 1 (p1->p2) and edge 3 (p3->p0)
                m0 = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0, z_ridge)
                m2 = ((p2[0] + p3[0]) / 2.0, (p2[1] + p3[1]) / 2.0, z_ridge)

                # Roof Slope 1 (over edge 1)
                add_roof_tri(roof_mat, p1_eave, p2_eave, m2)
                add_roof_tri(roof_mat, p1_eave, m2, m0)

                # Roof Slope 2 (over edge 3)
                add_roof_tri(roof_mat, p3_eave, p0_eave, m0)
                add_roof_tri(roof_mat, p3_eave, m0, m2)

                # Gable 1 (vertical triangular wall over edge 0)
                add_roof_tri(wall_mat, p0_eave, p1_eave, m0)

                # Gable 2 (vertical triangular wall over edge 2)
                add_roof_tri(wall_mat, p2_eave, p3_eave, m2)
        else:
            # General N-gon hipped roof: elevated central apex
            apex = (cx, cy, z_ridge)
            for i in range(n):
                va = (ring[i][0], ring[i][1], z_eave)
                vb = (ring[(i + 1) % n][0], ring[(i + 1) % n][1], z_eave)
                vc = apex
                add_roof_tri(roof_mat, va, vb, vc)

    def _add_flat_roof_and_parapet(
        self,
        ring: List[Tuple[float, float]],
        z_eave: float,
        roof_mat: str = "roof_gravel",
    ):
        """Flat gravel roof with architectural parapet and cornice for multi-story / commercial buildings."""
        n = len(ring)
        roof_start = len(self.verts)
        tile_scale = 3.5  # Realistic 3.5m gravel/asphalt tile
        for p in ring:
            self.verts.append((p[0], p[1], z_eave))
            self.normals.append((0.0, 0.0, 1.0))
            self.uvs.append((p[0] / tile_scale, p[1] / tile_scale))

        roof_tris = triangulate(ring)
        if roof_mat not in self.triangles_by_mat:
            self.triangles_by_mat[roof_mat] = []
        for ia, ib, ic in roof_tris:
            self.triangles_by_mat[roof_mat].extend([
                roof_start + ia, roof_start + ib, roof_start + ic,
            ])

        # Roof collision cap
        col_roof_start = len(self.col_verts)
        for p in ring:
            self.col_verts.append((p[0], p[1], z_eave))
        for ia, ib, ic in roof_tris:
            self.col_triangles.extend([
                col_roof_start + ia, col_roof_start + ib, col_roof_start + ic,
            ])

        # Architectural Roof Cornice & Parapet
        zc0 = z_eave - CORNICE_DOWN_M
        zc1 = z_eave + CORNICE_UP_M
        uv_c0, uv_c1 = (0.002, 0.995), (0.012, 0.995)
        uv_c2, uv_c3 = (0.012, 0.999), (0.002, 0.999)

        for i in range(n):
            a = np.array(ring[i])
            b = np.array(ring[(i + 1) % n])
            e = b - a
            l = float(math.hypot(e[0], e[1]))
            if l < 0.25:
                continue

            d = e / l
            nn = np.array([d[1], -d[0]])  # Outward normal
            a2 = a + nn * CORNICE_OUT_M - d * (CORNICE_OUT_M * 0.5)
            b2 = b + nn * CORNICE_OUT_M + d * (CORNICE_OUT_M * 0.5)

            # Outer front face
            self.add_quad(
                "facade_plaster",
                (a2[0], a2[1], zc0),
                (b2[0], b2[1], zc0),
                (b2[0], b2[1], zc1),
                (a2[0], a2[1], zc1),
                uv_c0, uv_c1, uv_c2, uv_c3,
                (nn[0], nn[1], 0.0),
            )
            # Top cap face
            self.add_quad(
                "facade_plaster",
                (a[0], a[1], zc1),
                (a2[0], a2[1], zc1),
                (b2[0], b2[1], zc1),
                (b[0], b[1], zc1),
                uv_c0, uv_c1, uv_c2, uv_c3,
                (0.0, 0.0, 1.0),
            )
            # Under-lip moulding
            self.add_quad(
                "facade_plaster",
                (a[0], a[1], zc0),
                (b[0], b[1], zc0),
                (b2[0], b2[1], zc0),
                (a2[0], a2[1], zc0),
                uv_c0, uv_c1, uv_c2, uv_c3,
                (0.0, 0.0, -1.0),
            )
            # Inner parapet face
            self.add_quad(
                "facade_plaster",
                (b[0], b[1], z_eave),
                (a[0], a[1], z_eave),
                (a[0], a[1], zc1),
                (b[0], b[1], zc1),
                uv_c0, uv_c1, uv_c2, uv_c3,
                (-nn[0], -nn[1], 0.0),
            )


def write_sector_dae(
    output_path: pathlib.Path,
    mesh: ProceduralBuildingMesh,
    sector_origin: Tuple[float, float, float],
):
    """
    Writes aggregated procedural building sector meshes into a clean, valid Collada 1.4.1 file.
    All vertices are stored relative to sector_origin (sec_cx, sec_cy, sec_cz).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sec_x, sec_y, sec_z = sector_origin

    # Transform coordinates to sector-local space
    verts_local = [
        (v[0] - sec_x, v[1] - sec_y, v[2] - sec_z)
        for v in mesh.verts
    ]
    col_verts_local = [
        (v[0] - sec_x, v[1] - sec_y, v[2] - sec_z)
        for v in mesh.col_verts
    ]

    vert_floats = " ".join(f"{x:.3f} {y:.3f} {z:.3f}" for x, y, z in verts_local)
    norm_floats = " ".join(f"{nx:.3f} {ny:.3f} {nz:.3f}" for nx, ny, nz in mesh.normals)
    uv_floats = " ".join(f"{u:.4f} {v:.4f}" for u, v in mesh.uvs)
    col_vert_floats = " ".join(f"{x:.3f} {y:.3f} {z:.3f}" for x, y, z in col_verts_local)

    # Filter active materials with triangles
    active_mats = [mat for mat, tris in mesh.triangles_by_mat.items() if len(tris) > 0]
    if not active_mats:
        active_mats = ["facade_plaster"]

    # Build materials and effects XML
    mat_defs = []
    eff_defs = []
    inst_mats = []
    tri_elements = []

    for mat in active_mats:
        mat_defs.append(
            f'    <material id="{mat}-mat" name="{mat}"><instance_effect url="#{mat}-eff"/></material>'
        )
        eff_defs.append(f"""    <effect id="{mat}-eff">
      <profile_COMMON>
        <technique sid="common">
          <phong>
            <diffuse><color>0.85 0.85 0.85 1.0</color></diffuse>
          </phong>
        </technique>
      </profile_COMMON>
    </effect>""")
        inst_mats.append(
            f'              <instance_material symbol="{mat}" target="#{mat}-mat"/>'
        )

        tris = mesh.triangles_by_mat.get(mat, [])
        tri_count = len(tris) // 3
        # In this structure, vert_idx == norm_idx == uv_idx
        p_str = " ".join(f"{idx} {idx} {idx}" for idx in tris)
        tri_elements.append(f"""        <triangles material="{mat}" count="{tri_count}">
          <input semantic="VERTEX" source="#Building-vertices" offset="0"/>
          <input semantic="NORMAL" source="#Building-norm" offset="1"/>
          <input semantic="TEXCOORD" source="#Building-uv" offset="2" set="0"/>
          <p>{p_str}</p>
        </triangles>""")

    # Collision triangles
    col_tri_count = len(mesh.col_triangles) // 3
    col_p_str = " ".join(str(idx) for idx in mesh.col_triangles)

    dae_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><author>AroundWorldNG</author></contributor>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_materials>
{chr(10).join(mat_defs)}
  </library_materials>
  <library_effects>
{chr(10).join(eff_defs)}
  </library_effects>
  <library_geometries>
    <geometry id="Building-mesh" name="Building">
      <mesh>
        <source id="Building-pos">
          <float_array id="Building-pos-array" count="{len(verts_local)*3}">{vert_floats}</float_array>
          <technique_common>
            <accessor source="#Building-pos-array" count="{len(verts_local)}" stride="3">
              <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="Building-norm">
          <float_array id="Building-norm-array" count="{len(mesh.normals)*3}">{norm_floats}</float_array>
          <technique_common>
            <accessor source="#Building-norm-array" count="{len(mesh.normals)}" stride="3">
              <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="Building-uv">
          <float_array id="Building-uv-array" count="{len(mesh.uvs)*2}">{uv_floats}</float_array>
          <technique_common>
            <accessor source="#Building-uv-array" count="{len(mesh.uvs)}" stride="2">
              <param name="S" type="float"/><param name="T" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="Building-vertices">
          <input semantic="POSITION" source="#Building-pos"/>
        </vertices>
{chr(10).join(tri_elements)}
      </mesh>
    </geometry>
    <geometry id="Col-mesh" name="Col">
      <mesh>
        <source id="Col-pos">
          <float_array id="Col-pos-array" count="{len(col_verts_local)*3}">{col_vert_floats}</float_array>
          <technique_common>
            <accessor source="#Col-pos-array" count="{len(col_verts_local)}" stride="3">
              <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="Col-vertices">
          <input semantic="POSITION" source="#Col-pos"/>
        </vertices>
        <triangles count="{col_tri_count}">
          <input semantic="VERTEX" source="#Col-vertices" offset="0"/>
          <p>{col_p_str}</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene" name="Scene">
      <node id="BuildingNode" name="Building" type="NODE">
        <instance_geometry url="#Building-mesh">
          <bind_material>
            <technique_common>
{chr(10).join(inst_mats)}
            </technique_common>
          </bind_material>
        </instance_geometry>
        <node id="Col-1" name="Col-1" type="NODE">
          <instance_geometry url="#Col-mesh"/>
        </node>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene>
    <instance_visual_scene url="#Scene"/>
  </scene>
</COLLADA>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(dae_xml)


# -------------------------------------------------------------------------------------------------
# Backwards compatibility functions for tests and legacy archetypes
# -------------------------------------------------------------------------------------------------

def write_building_dae(
    output_path: pathlib.Path,
    width: float,
    depth: float,
    height: float,
    wall_mat: str = "facade_brick",
    roof_mat: str = "roof_gravel",
    skirt_depth: float = 3.0,
    has_gabled_roof: bool = False,
):
    """Legacy archetype generator for backward compatibility with unit tests."""
    hw = width / 2.0
    hd = depth / 2.0
    ring = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    builder = ProceduralBuildingMesh()
    floors = max(1, int(round(height / 3.0)))
    builder.extrude_building(
        ring=ring,
        base_z=0.0,
        z_base=-skirt_depth,
        z_eave=height,
        floors=floors,
        floor_h=3.0,
        band_idx=2 if wall_mat == "facade_plaster" else 3,
        is_house=has_gabled_roof,
    )
    write_sector_dae(output_path, builder, sector_origin=(0.0, 0.0, 0.0))


def create_all_building_archetypes(art_shapes_dir: pathlib.Path):
    """Creates fallback archetype shapes for testing and manual level placements."""
    bld_dir = art_shapes_dir / "buildings"
    bld_dir.mkdir(parents=True, exist_ok=True)

    write_building_dae(
        bld_dir / "bld_house_small.dae",
        width=10.0, depth=12.0, height=7.0,
        wall_mat="facade_plaster", roof_mat="roof_tiles",
        skirt_depth=3.0, has_gabled_roof=True,
    )
    write_building_dae(
        bld_dir / "bld_apartment_block.dae",
        width=24.0, depth=14.0, height=16.0,
        wall_mat="facade_brick", roof_mat="roof_gravel",
        skirt_depth=3.5,
    )
    write_building_dae(
        bld_dir / "bld_commercial_glass.dae",
        width=20.0, depth=20.0, height=26.0,
        wall_mat="facade_plaster", roof_mat="roof_gravel",
        skirt_depth=4.0,
    )
    write_building_dae(
        bld_dir / "bld_industrial_warehouse.dae",
        width=35.0, depth=20.0, height=10.0,
        wall_mat="facade_plaster", roof_mat="roof_gravel",
        skirt_depth=3.0,
    )
    write_building_dae(
        bld_dir / "bld_commercial_plaza.dae",
        width=30.0, depth=16.0, height=8.0,
        wall_mat="facade_plaster", roof_mat="roof_gravel",
        skirt_depth=3.0,
    )
    print(f"[BuildingMesh] Created 5 architectural building archetypes in {bld_dir}")
