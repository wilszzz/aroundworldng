"""
DecalRoad and MeshRoad Generator for BeamNG.drive.
Converts OSM road segments into Torque3D road splines.
"""

from typing import Any, Dict, List
import uuid
from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment
from processing.heightmap import HeightmapProcessor


def get_road_material(surface: str, highway_type: str) -> str:
    """Selects suitable BeamNG material name based on surface and classification."""
    surface = (surface or "").lower()
    if surface in {"dirt", "ground", "earth"}:
        return "road_dirt"
    elif surface in {"gravel", "compacted", "fine_gravel"}:
        return "road_gravel"
    elif highway_type in {"motorway", "trunk", "primary"}:
        return "road_asphalt_clean"
    else:
        return "road_asphalt"


class RoadExporter:
    """Translates RoadSegments into BeamNG DecalRoad and MeshRoad item descriptors."""

    def __init__(
        self,
        heightmap_processor: HeightmapProcessor,
        origin_lat: float,
        origin_lon: float,
        z_offset: float = 0.05,
    ):
        self.heightmap = heightmap_processor
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.z_offset = z_offset

    def export_roads(self, roads: List[RoadSegment]) -> List[Dict[str, Any]]:
        """Generates list of DecalRoad and MeshRoad JSON objects for items.level.json."""
        items: List[Dict[str, Any]] = []

        for idx, road in enumerate(roads):
            if len(road.nodes) < 2:
                continue

            nodes_data = []
            for lat, lon in road.nodes:
                x, y = lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                # Sample smoothed height
                z = self.heightmap.get_elevation_at_meters(x, y) + self.z_offset
                w = road.width
                nodes_data.append([round(x, 3), round(y, 3), round(z, 3), round(w, 2)])

            mat_name = get_road_material(road.surface, road.highway_type)
            road_id = str(uuid.uuid4())

            if road.is_bridge:
                # MeshRoad for bridges
                mesh_nodes = []
                for node in nodes_data:
                    # [x, y, z, width, depth, normal_x, normal_y, normal_z]
                    mesh_nodes.append([node[0], node[1], node[2] + 1.0, node[3], 0.6, 0.0, 0.0, 1.0])

                items.append({
                    "name": f"bridge_{road.osm_id}_{idx}",
                    "class": "MeshRoad",
                    "persistentId": road_id,
                    "topMaterial": mat_name,
                    "bottomMaterial": "concrete_plain",
                    "sideMaterial": "concrete_plain",
                    "nodes": mesh_nodes,
                    "widthSubdivisions": 1,
                })
            else:
                # Standard DecalRoad
                items.append({
                    "name": f"road_{road.osm_id}_{idx}",
                    "class": "DecalRoad",
                    "persistentId": road_id,
                    "material": mat_name,
                    "drivability": 1,
                    "renderPriority": 10,
                    "breakAngle": 3.0,
                    "nodes": nodes_data,
                })

        print(f"[RoadExporter] Created {len(items)} road splines for BeamNG.")
        return items
