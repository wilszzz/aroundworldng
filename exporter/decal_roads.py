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


def resample_polyline(
    pts: List[Tuple[float, float]],
    target_step: float = 10.0,
    half: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """
    Resamples a 2D polyline so that distance between adjacent nodes is roughly 8-12 meters (target 10m).
    Applies boundary clamping to [-half, half] if half is specified.
    """
    if len(pts) < 2:
        return pts

    # Clamp and deduplicate points closer than 0.3m
    clamped: List[Tuple[float, float]] = []
    for x, y in pts:
        if half is not None:
            x = max(-half, min(half, x))
            y = max(-half, min(half, y))
        if not clamped:
            clamped.append((x, y))
        else:
            dx = x - clamped[-1][0]
            dy = y - clamped[-1][1]
            if (dx * dx + dy * dy) > 0.09:  # at least 0.3m apart
                clamped.append((x, y))

    if len(clamped) < 2:
        return clamped

    # If all points are pegged to boundaries, road is outside map area
    if half is not None and all(abs(p[0]) >= half - 0.1 or abs(p[1]) >= half - 0.1 for p in clamped):
        return []

    resampled: List[Tuple[float, float]] = [clamped[0]]
    for i in range(1, len(clamped)):
        p0 = resampled[-1]
        p1 = clamped[i]
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

            # Resample polyline with 8-12m step to hug terrain height variations
            resampled_pts = resample_polyline(raw_pts, target_step=10.0, half=half)
            if len(resampled_pts) < 2:
                continue

            # Sample exact terrain elevation at each resampled node
            nodes_data = []
            for sx, sy in resampled_pts:
                sz = self.heightmap.get_elevation_at_meters(sx, sy) + self.z_offset
                nodes_data.append([round(sx, 3), round(sy, 3), round(sz, 3), round(road.width, 2)])

            mat_name, texture_length, render_priority = get_road_look(
                road.surface, road.highway_type, road.width
            )
            road_id = str(uuid.uuid4())
            first_pos = [nodes_data[0][0], nodes_data[0][1], nodes_data[0][2]]

            if road.is_bridge:
                # MeshRoad for 3D elevated bridge structures
                mesh_nodes = []
                for node in nodes_data:
                    mesh_nodes.append([node[0], node[1], node[2] + 1.0, node[3], 0.6, 0.0, 0.0, 1.0])

                items.append({
                    "name": f"bridge_{road.osm_id}_{idx}",
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
                    "name": f"road_{road.osm_id}_{idx}",
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

                # Centerline Road Markings for major paved roads
                h_type = (road.highway_type or "").lower().strip()
                if h_type in MARKING_HIGHWAY_TYPES and mat_name != "road_dirt":
                    marking_nodes = [[n[0], n[1], n[2], 0.25] for n in nodes_data]
                    marking_id = str(uuid.uuid4())
                    items.append({
                        "name": f"marking_{road.osm_id}_{idx}",
                        "class": "DecalRoad",
                        "persistentId": marking_id,
                        "__parent": "MissionGroup",
                        "position": first_pos,
                        "material": "line_white",
                        "drivability": 1,
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
