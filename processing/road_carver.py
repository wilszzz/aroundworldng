"""
Road Carving and Terrain Conformance Engine for BeamNG.drive.
Ensures seamless road networks with unified junction elevations,
preventing pits, steps, or potholes at multi-road intersections.
Uses Hermite smoothstep shoulder transitions for stable, gap-free roadbeds.
Optimized for low RAM consumption with float32 arrays and sparse Laplacian solves.
"""

import gc
import math
from typing import Dict, List, Optional, Set, Tuple
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from shapely.geometry import LineString, Point

from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment


class RoadCarver:
    """Modifies heightmap elevations to create smooth road foundations and flat intersections."""

    def __init__(
        self,
        heightmap: np.ndarray,
        square_size: float,
        origin_lat: float,
        origin_lon: float,
        blend_margin_meters: float = 4.0,
        shoulder_margin_meters: float = 1.2,
    ):
        """
        heightmap: 2D float32 numpy array (res, res)
        square_size: meters per pixel
        origin_lat, origin_lon: geographic center
        blend_margin_meters: width of lateral transition from road shoulder to natural terrain
        shoulder_margin_meters: extra flat roadbed margin beyond road edge to prevent mesh overhang
        """
        self.heights = np.asarray(heightmap, dtype=np.float32)
        self.res = self.heights.shape[0]
        self.square_size = float(square_size)
        self.origin_lat = float(origin_lat)
        self.origin_lon = float(origin_lon)
        self.margin = float(blend_margin_meters)
        self.shoulder = float(shoulder_margin_meters)
        self.half_span = (self.res - 1) * self.square_size / 2.0

    def sample_height(self, x_meters: float, y_meters: float) -> float:
        """Bilinear height sampling from terrain heightmap."""
        px = (x_meters + self.half_span) / self.square_size
        py = (y_meters + self.half_span) / self.square_size
        px = max(0.0, min(float(self.res - 1), px))
        py = max(0.0, min(float(self.res - 1), py))

        ix = int(px)
        iy = int(py)
        ix1 = min(ix + 1, self.res - 1)
        iy1 = min(iy + 1, self.res - 1)
        fx = px - ix
        fy = py - iy

        h00 = self.heights[iy, ix]
        h01 = self.heights[iy, ix1]
        h10 = self.heights[iy1, ix]
        h11 = self.heights[iy1, ix1]

        top = h00 * (1.0 - fx) + h01 * fx
        bot = h10 * (1.0 - fx) + h11 * fx
        return float(top * (1.0 - fy) + bot * fy)

    def carve_roads(self, roads: List[RoadSegment], sigma: float = 3.0) -> np.ndarray:
        """
        Applies network-wide road carving and junction-unified longitudinal smoothing.
        Returns the modified heightmap array in float32.
        """
        # Filter valid surface roads (exclude bridges, tunnels, single-node roads)
        ground_roads: List[Tuple[RoadSegment, List[Tuple[float, float]]]] = []
        for r in roads:
            if r.is_bridge or r.is_tunnel or len(r.nodes) < 2:
                continue

            pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in r.nodes
            ]

            # Deduplicate consecutive points
            dedup_pts: List[Tuple[float, float]] = []
            for p in pts:
                if not dedup_pts or math.hypot(p[0] - dedup_pts[-1][0], p[1] - dedup_pts[-1][1]) > 0.2:
                    dedup_pts.append(p)

            if len(dedup_pts) < 2:
                continue

            # Check length
            total_len = sum(
                math.hypot(dedup_pts[i + 1][0] - dedup_pts[i][0], dedup_pts[i + 1][1] - dedup_pts[i][1])
                for i in range(len(dedup_pts) - 1)
            )
            if total_len < 3.0:
                continue

            ground_roads.append((r, dedup_pts))

        if not ground_roads:
            return self.heights.copy()

        print(f"[RoadCarver] Building connected road graph for {len(ground_roads)} roads (sigma={sigma})...")

        # 1. Cluster road vertices within 1.5m to unify intersections and junctions
        snap_tol = 1.5
        grid_cell = snap_tol
        spatial_grid: Dict[Tuple[int, int], List[int]] = {}
        junction_coords: List[Tuple[float, float]] = []

        def get_or_create_junction(x: float, y: float) -> int:
            cx = int(math.floor(x / grid_cell))
            cy = int(math.floor(y / grid_cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cell = (cx + dx, cy + dy)
                    if cell in spatial_grid:
                        for j_idx in spatial_grid[cell]:
                            jx, jy = junction_coords[j_idx]
                            if math.hypot(x - jx, y - jy) <= snap_tol:
                                return j_idx
            # New junction node
            new_idx = len(junction_coords)
            junction_coords.append((x, y))
            spatial_grid.setdefault((cx, cy), []).append(new_idx)
            return new_idx

        # Map each road to a sequence of junction indices
        road_junction_sequences: List[Tuple[RoadSegment, List[int]]] = []
        for road, pts in ground_roads:
            seq = [get_or_create_junction(p[0], p[1]) for p in pts]
            road_junction_sequences.append((road, seq))

        # 2. Build station graph: sample intermediate stations between junctions
        step = 2.5  # meters per station
        station_coords: List[Tuple[float, float]] = list(junction_coords)
        road_station_sequences: List[Tuple[RoadSegment, List[int]]] = []
        station_incident_widths: Dict[int, float] = {}

        for road, j_seq in road_junction_sequences:
            st_seq = [j_seq[0]]
            station_incident_widths[j_seq[0]] = max(
                station_incident_widths.get(j_seq[0], 0.0), road.width
            )

            for i in range(len(j_seq) - 1):
                u_idx, v_idx = j_seq[i], j_seq[i + 1]
                p_u = junction_coords[u_idx]
                p_v = junction_coords[v_idx]
                dist = math.hypot(p_v[0] - p_u[0], p_v[1] - p_u[1])

                num_sub = max(1, int(round(dist / step)))
                for s in range(1, num_sub):
                    t = s / num_sub
                    sx = p_u[0] + (p_v[0] - p_u[0]) * t
                    sy = p_u[1] + (p_v[1] - p_u[1]) * t
                    new_st_idx = len(station_coords)
                    station_coords.append((sx, sy))
                    st_seq.append(new_st_idx)
                    station_incident_widths[new_st_idx] = road.width

                st_seq.append(v_idx)
                station_incident_widths[v_idx] = max(
                    station_incident_widths.get(v_idx, 0.0), road.width
                )

            road_station_sequences.append((road, st_seq))

        num_stations = len(station_coords)
        print(f"[RoadCarver] Road graph contains {num_stations} stations across {len(junction_coords)} junctions.")

        # 3. Sample raw terrain elevations at all stations
        raw_h = np.zeros(num_stations, dtype=np.float32)
        for i, (sx, sy) in enumerate(station_coords):
            raw_h[i] = self.sample_height(sx, sy)

        # 4. Global Network Longitudinal Smoothing via Sparse SPD Laplacian System
        # Minimizes: sum w*(z_i - h_i)^2 + alpha * sum (z_i - z_j)^2 / L_ij
        # Shared junction nodes have a SINGLE variable, guaranteeing Z1 = Z2 = ... = Zn at every intersection!
        sigma_clamped = max(0.5, float(sigma))
        alpha = 40.0 * (sigma_clamped ** 2)
        w_diag = np.ones(num_stations, dtype=np.float32)

        edge_dict: Dict[Tuple[int, int], float] = {}
        for road, st_seq in road_station_sequences:
            for i in range(len(st_seq) - 1):
                u, v = st_seq[i], st_seq[i + 1]
                if u == v:
                    continue
                pair = (min(u, v), max(u, v))
                p_u, p_v = station_coords[u], station_coords[v]
                L = max(0.5, math.hypot(p_v[0] - p_u[0], p_v[1] - p_u[1]))
                edge_dict[pair] = min(edge_dict.get(pair, L), L)

        rows: List[int] = []
        cols: List[int] = []
        data: List[float] = []

        for i in range(num_stations):
            rows.append(i)
            cols.append(i)
            data.append(float(w_diag[i]))

        for (u, v), L in edge_dict.items():
            stiff = alpha / L
            rows.extend([u, v, u, v])
            cols.extend([u, v, v, u])
            data.extend([stiff, stiff, -stiff, -stiff])

        A = sp.csr_matrix((data, (rows, cols)), shape=(num_stations, num_stations), dtype=np.float32)
        b = w_diag * raw_h

        # Direct sparse solve (strictly diagonally dominant & SPD -> guaranteed unique, smooth solution)
        smooth_z = spla.spsolve(A, b).astype(np.float32)

        # Clean graph solve structures from memory
        del rows, cols, data, edge_dict, A, b
        gc.collect()

        # 5. Carve roads into terrain with Hermite smoothstep and protective weight buffer
        carved = self.heights.copy()
        max_weights = np.zeros((self.res, self.res), dtype=np.float32)

        for road, st_seq in road_station_sequences:
            flat_radius = (road.width / 2.0) + self.shoulder
            influence_radius = flat_radius + self.margin

            for i in range(len(st_seq) - 1):
                u, v = st_seq[i], st_seq[i + 1]
                p_u = station_coords[u]
                p_v = station_coords[v]
                z_u = smooth_z[u]
                z_v = smooth_z[v]

                seg_len = math.hypot(p_v[0] - p_u[0], p_v[1] - p_u[1])
                sub_steps = max(2, int(seg_len / min(1.5, self.square_size)))

                for step_i in range(sub_steps + 1):
                    t = step_i / sub_steps
                    cx = p_u[0] + (p_v[0] - p_u[0]) * t
                    cy = p_u[1] + (p_v[1] - p_u[1]) * t
                    target_h = z_u + (z_v - z_u) * t

                    # Subgrid bounding box in pixels
                    px_min = max(0, int((cx - influence_radius + self.half_span) / self.square_size))
                    px_max = min(self.res - 1, int((cx + influence_radius + self.half_span) / self.square_size))
                    py_min = max(0, int((cy - influence_radius + self.half_span) / self.square_size))
                    py_max = min(self.res - 1, int((cy + influence_radius + self.half_span) / self.square_size))

                    if px_max < px_min or py_max < py_min:
                        continue

                    gy, gx = np.ogrid[py_min : py_max + 1, px_min : px_max + 1]
                    dist = np.hypot(
                        gx * self.square_size - self.half_span - cx,
                        gy * self.square_size - self.half_span - cy,
                    )

                    in_flat = dist <= flat_radius
                    in_blend = (dist > flat_radius) & (dist <= influence_radius)

                    w_grid = np.zeros_like(dist, dtype=np.float32)
                    w_grid[in_flat] = 1.0

                    # Hermite smoothstep: s^2 * (3 - 2s)
                    s = (influence_radius - dist[in_blend]) / self.margin
                    w_grid[in_blend] = s * s * (3.0 - 2.0 * s)

                    # Update only pixels where current road point exerts higher influence
                    # This prevents shoulder slopes of intersecting roads from degrading flat roadbeds
                    sub_max_w = max_weights[py_min : py_max + 1, px_min : px_max + 1]
                    mask = w_grid > sub_max_w
                    if np.any(mask):
                        sub_nat = self.heights[py_min : py_max + 1, px_min : px_max + 1]
                        sub_carved = carved[py_min : py_max + 1, px_min : px_max + 1]
                        w_sub = w_grid[mask]
                        sub_carved[mask] = w_sub * target_h + (1.0 - w_sub) * sub_nat[mask]
                        sub_max_w[mask] = w_sub

        del max_weights, smooth_z, station_coords, junction_coords
        gc.collect()

        print(f"[RoadCarver] Successfully carved and blended road foundations into terrain.")
        return carved
