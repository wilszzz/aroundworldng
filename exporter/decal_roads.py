"""
DecalRoad and MeshRoad Generator for BeamNG.drive.
Converts OSM road segments into Torque3D road splines with realistic PBR materials,
adaptive elevation resampling, and crisp road markings.
"""

import math
from typing import Any, Dict, List, Optional, Tuple
import uuid
from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment
from processing.heightmap import HeightmapProcessor

# Unpaved surface keywords in OSM
UNPAVED_SURFACES = {
    "dirt", "ground", "earth", "gravel", "compacted", "fine_gravel",
    "sand", "unpaved", "mud", "soil", "grass", "pebblestone", "rock", "clay"
}

# Highway types that are typically unpaved if surface tag is absent
UNPAVED_HIGHWAYS = {"track", "path"}

# Major paved highway types qualifying for 2-lane asphalt and centerline markings
MARKING_HIGHWAY_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"
}


def get_road_look(surface: str, highway_type: str, width: float = 6.0) -> Tuple[str, float, int]:
    """
    Selects suitable BeamNG material name, textureLength and renderPriority
    based on surface classification, highway type and width.
    Returns: (material_name, texture_length, render_priority)
    """
    s = (surface or "").lower().strip()
    h = (highway_type or "").lower().strip()

    # Unpaved / Dirt roads
    if s in UNPAVED_SURFACES or (not s and h in UNPAVED_HIGHWAYS):
        return "road_dirt", 40.0, 20

    # 2-lane asphalt: major roads, residential, or standard wide carriageways
    if h in MARKING_HIGHWAY_TYPES or h == "residential" or width >= 5.5:
        return "road_asphalt_2lane", 11.0, 20
    else:
        # Narrow / single lane / service asphalt
        return "road_asphalt", 12.0, 20


def get_road_material(surface: str, highway_type: str) -> str:
    """Backward-compatible helper returning material name."""
    mat, _, _ = get_road_look(surface, highway_type)
    return mat


def clip_segment_to_box(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    half: float,
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Clips a directed line segment p0 -> p1 to [-half, half] x [-half, half]
    using the Liang-Barsky algorithm.
    Returns (clipped_p0, clipped_p1) or None if entirely outside.
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]

    t0 = 0.0
    t1 = 1.0

    checks = [
        (-dx, p0[0] + half),     # left
        (dx, half - p0[0]),      # right
        (-dy, p0[1] + half),     # bottom
        (dy, half - p0[1]),      # top
    ]

    for p, q in checks:
        if abs(p) < 1e-12:
            if q < 0.0:
                return None
        else:
            r = q / p
            if p < 0.0:
                if r > t1:
                    return None
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return None
                if r < t1:
                    t1 = r

    if t0 > t1:
        return None

    cp0 = (p0[0] + t0 * dx, p0[1] + t0 * dy)
    cp1 = (p0[0] + t1 * dx, p0[1] + t1 * dy)
    return cp0, cp1


def clip_polyline_to_box(
    pts: List[Tuple[float, float]],
    half: float,
) -> List[List[Tuple[float, float]]]:
    """
    Clips a polyline against the bounding box [-half, half] x [-half, half].
    Returns a list of continuous polylines located inside the box.
    """
    if len(pts) < 2:
        return []

    polylines: List[List[Tuple[float, float]]] = []
    current_line: List[Tuple[float, float]] = []

    for i in range(len(pts) - 1):
        seg = clip_segment_to_box(pts[i], pts[i + 1], half)
        if seg is None:
            if len(current_line) >= 2:
                polylines.append(current_line)
            current_line = []
            continue

        cp0, cp1 = seg
        if math.hypot(cp1[0] - cp0[0], cp1[1] - cp0[1]) < 0.01:
            continue

        if not current_line:
            current_line = [cp0, cp1]
        else:
            last = current_line[-1]
            if math.hypot(cp0[0] - last[0], cp0[1] - last[1]) < 0.05:
                current_line.append(cp1)
            else:
                if len(current_line) >= 2:
                    polylines.append(current_line)
                current_line = [cp0, cp1]

    if len(current_line) >= 2:
        polylines.append(current_line)

    return polylines


def resample_polyline(
    pts: List[Tuple[float, float]],
    target_step: float = 10.0,
    half: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """
    Resamples a 2D polyline so that distance between adjacent nodes is roughly 8-12 meters (target 10m).
    Clips line to [-half, half] if half is specified.
    """
    if len(pts) < 2:
        return pts

    working_pts = pts
    if half is not None:
        clipped = clip_polyline_to_box(pts, half)
        if not clipped:
            return []
        working_pts = max(clipped, key=lambda l: len(l))

    # Deduplicate points closer than 0.3m
    filtered: List[Tuple[float, float]] = []
    for x, y in working_pts:
        if not filtered:
            filtered.append((x, y))
        else:
            dx = x - filtered[-1][0]
            dy = y - filtered[-1][1]
            if (dx * dx + dy * dy) > 0.09:  # at least 0.3m apart
                filtered.append((x, y))

    if len(filtered) < 2:
        return filtered

    resampled: List[Tuple[float, float]] = [filtered[0]]
    for i in range(1, len(filtered)):
        p0 = resampled[-1]
        p1 = filtered[i]
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dist = math.hypot(dx, dy)

        if dist < 0.3:
            continue

        # Split so each subsegment is at most ~11m (keeping within 8-12m bounds)
        num_sub = max(1, int(math.ceil(dist / 11.0)))
        for s in range(1, num_sub + 1):
            t = s / num_sub
            nx = p0[0] + dx * t
            ny = p0[1] + dy * t
            if half is not None:
                nx = max(-half, min(half, nx))
                ny = max(-half, min(half, ny))
            resampled.append((nx, ny))

    return resampled


class RoadExporter:
    """Translates RoadSegments into BeamNG DecalRoad and MeshRoad item descriptors."""

    def __init__(
        self,
        heightmap_processor: HeightmapProcessor,
        origin_lat: float,
        origin_lon: float,
        z_offset: float = 0.05,
        size_meters: Optional[float] = None,
    ):
        self.heightmap = heightmap_processor
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.z_offset = z_offset
        self.size_meters = size_meters

    def export_roads(self, roads: List[RoadSegment]) -> List[Dict[str, Any]]:
        """Generates list of DecalRoad and MeshRoad JSON objects for items.level.json."""
        items: List[Dict[str, Any]] = []
        half = (self.size_meters / 2.0 - 2.0) if self.size_meters else None

        for idx, road in enumerate(roads):
            if len(road.nodes) < 2:
                continue

            # Convert OSM lat/lon to local coordinates (meters)
            raw_pts: List[Tuple[float, float]] = []
            for lat, lon in road.nodes:
                x, y = lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                raw_pts.append((x, y))

            # Clip polyline to map bounding box [-half, half] so roads touching boundary aren't lost
            if half is not None:
                clipped_polylines = clip_polyline_to_box(raw_pts, half)
            else:
                clipped_polylines = [raw_pts]

            if not clipped_polylines:
                continue

            for poly_idx, poly_pts in enumerate(clipped_polylines):
                # Resample polyline with 8-12m step to hug terrain height variations
                resampled_pts = resample_polyline(poly_pts, target_step=10.0, half=half)
                if len(resampled_pts) < 2:
                    continue

                # Sample exact terrain elevation at each resampled node
                nodes_data = []
                for sx, sy in resampled_pts:
                    sz = self.heightmap.get_elevation_at_meters(sx, sy) + self.z_offset
                    nodes_data.append([round(sx, 3), round(sy, 3), round(sz, 3), round(road.width, 2)])

                # Bridge elevation smoothing: prevent bridge deck from dropping into riverbeds
                if road.is_bridge and len(nodes_data) >= 2:
                    z_start = nodes_data[0][2]
                    z_end = nodes_data[-1][2]
                    cum_dists = [0.0]
                    for i in range(1, len(nodes_data)):
                        dx = nodes_data[i][0] - nodes_data[i - 1][0]
                        dy = nodes_data[i][1] - nodes_data[i - 1][1]
                        cum_dists.append(cum_dists[-1] + math.hypot(dx, dy))

                    total_len = cum_dists[-1]
                    if total_len > 0.0:
                        for i in range(len(nodes_data)):
                            t = cum_dists[i] / total_len
                            z_interp = z_start + t * (z_end - z_start)
                            # Bridge deck stays at or above interpolated elevation across river
                            nodes_data[i][2] = round(max(nodes_data[i][2], z_interp), 3)

                mat_name, texture_length, render_priority = get_road_look(
                    road.surface, road.highway_type, road.width
                )
                road_id = str(uuid.uuid4())
                first_pos = [nodes_data[0][0], nodes_data[0][1], nodes_data[0][2]]
                suffix = f"_{poly_idx}" if len(clipped_polylines) > 1 else ""

                if road.is_bridge:
                    # MeshRoad for 3D elevated bridge structures
                    mesh_nodes = []
                    for node in nodes_data:
                        mesh_nodes.append([node[0], node[1], node[2] + 1.0, node[3], 0.6, 0.0, 0.0, 1.0])

                    items.append({
                        "name": f"bridge_{road.osm_id}_{idx}{suffix}",
                        "class": "MeshRoad",
                        "persistentId": road_id,
                        "__parent": "MissionGroup",
                        "position": first_pos,
                        "topMaterial": mat_name,
                        "bottomMaterial": "concrete_plain",
                        "sideMaterial": "concrete_plain",
                        "nodes": mesh_nodes,
                        "widthSubdivisions": 1,
                    })
                else:
                    # Standard DecalRoad with official BeamNG properties
                    items.append({
                        "name": f"road_{road.osm_id}_{idx}{suffix}",
                        "class": "DecalRoad",
                        "persistentId": road_id,
                        "__parent": "MissionGroup",
                        "position": first_pos,
                        "material": mat_name,
                        "drivability": 1,
                        "overObjects": True,
                        "detail": 0.2,
                        "distanceFade": [500, 100],
                        "renderPriority": render_priority,  # 20 for asphalt and dirt
                        "breakAngle": 3.0,
                        "improvedSpline": True,
                        "textureLength": texture_length,
                        "startEndFade": [5.0, 5.0],
                        "nodes": nodes_data,
                    })

                    # Lane Markings for multi-lane paved roads (lanes >= 2)
                    if road.lanes >= 2 and mat_name != "road_dirt":
                        lane_w = road.width / road.lanes
                        half_w = road.width / 2.0
                        for lane_idx in range(1, road.lanes):
                            offset = -half_w + lane_idx * lane_w
                            marking_nodes = []
                            for j in range(len(nodes_data)):
                                x, y, z, _ = nodes_data[j]
                                if abs(offset) < 1e-4:
                                    marking_nodes.append([x, y, z, 0.25])
                                else:
                                    if j == 0:
                                        dx = nodes_data[1][0] - nodes_data[0][0]
                                        dy = nodes_data[1][1] - nodes_data[0][1]
                                    elif j == len(nodes_data) - 1:
                                        dx = nodes_data[-1][0] - nodes_data[-2][0]
                                        dy = nodes_data[-1][1] - nodes_data[-2][1]
                                    else:
                                        dx = nodes_data[j + 1][0] - nodes_data[j - 1][0]
                                        dy = nodes_data[j + 1][1] - nodes_data[j - 1][1]

                                    seg_len = math.hypot(dx, dy)
                                    if seg_len > 1e-6:
                                        ux, uy = dx / seg_len, dy / seg_len
                                    else:
                                        ux, uy = 1.0, 0.0

                                    nx = -uy
                                    ny = ux
                                    ox = x + nx * offset
                                    oy = y + ny * offset
                                    oz = self.heightmap.get_elevation_at_meters(ox, oy) + self.z_offset
                                    marking_nodes.append([round(ox, 3), round(oy, 3), round(oz, 3), 0.25])

                            m_first_pos = [marking_nodes[0][0], marking_nodes[0][1], marking_nodes[0][2]]
                            marking_name = (
                                f"marking_{road.osm_id}_{idx}{suffix}"
                                if road.lanes == 2
                                else f"marking_{road.osm_id}_{idx}{suffix}_{lane_idx}"
                            )
                            items.append({
                                "name": marking_name,
                                "class": "DecalRoad",
                                "persistentId": str(uuid.uuid4()),
                                "__parent": "MissionGroup",
                                "position": m_first_pos,
                                "material": "line_white",
                                "drivability": -1,
                                "overObjects": True,
                                "detail": 0.2,
                                "distanceFade": [500, 100],
                                "renderPriority": 22,  # Renders on top of road surface (20)
                                "breakAngle": 3.0,
                                "improvedSpline": True,
                                "textureLength": 8.0,
                                "startEndFade": [5.0, 5.0],
                                "nodes": marking_nodes,
                            })

        print(f"[RoadExporter] Created {len(items)} road splines & markings for BeamNG.")
        return items
