"""
DecalRoad and MeshRoad Generator for BeamNG.drive.
Converts OSM road segments into Torque3D road splines.
"""

from typing import Any, Dict, List, Optional
import uuid
from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment
from processing.heightmap import HeightmapProcessor


def get_road_material(surface: str, highway_type: str) -> str:
    """Selects suitable BeamNG material name based on surface and classification."""
    surface = (surface or "").lower()
    if surface in {"dirt", "ground", "earth", "gravel", "compacted", "fine_gravel", "sand"}:
        return "road_dirt"
    else:
        return "AsphaltRoad_variation_01"


class RoadExporter:
    """Translates RoadSegments into BeamNG DecalRoad and MeshRoad item descriptors."""

    def __init__(
        self,
        heightmap_processor: HeightmapProcessor,
        origin_lat: float,
        origin_lon: float,
        z_offset: float = 0.08,
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

            raw_nodes = []
            for lat, lon in road.nodes:
                x, y = lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                if half is not None:
                    x = max(-half, min(half, x))
                    y = max(-half, min(half, y))
                z = self.heightmap.get_elevation_at_meters(x, y) + self.z_offset
                w = road.width
                raw_nodes.append([round(x, 3), round(y, 3), round(z, 3), round(w, 2)])

            # Discard if entire road is pegged to bounding borders
            if half is not None and all(abs(n[0]) >= half - 0.1 or abs(n[1]) >= half - 0.1 for n in raw_nodes):
                continue

            # Deduplicate closely spaced consecutive clamped nodes
            nodes_data = [raw_nodes[0]]
            for n in raw_nodes[1:]:
                dx = n[0] - nodes_data[-1][0]
                dy = n[1] - nodes_data[-1][1]
                if (dx * dx + dy * dy) > 0.25:  # at least 0.5m apart
                    nodes_data.append(n)

            if len(nodes_data) < 2:
                continue

            mat_name = get_road_material(road.surface, road.highway_type)
            road_id = str(uuid.uuid4())
            first_pos = [nodes_data[0][0], nodes_data[0][1], nodes_data[0][2]]

            if road.is_bridge:
                # MeshRoad for bridges
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
                    "renderPriority": 1,
                    "breakAngle": 3.0,
                    "improvedSpline": True,
                    "textureLength": 60.0,
                    "startEndFade": [5.0, 5.0],
                    "nodes": nodes_data,
                })

        print(f"[RoadExporter] Created {len(items)} road splines for BeamNG.")
        return items
