"""
Road Decorations and Street Furniture Generator.
Generates streetlights, crash barriers, guardrails, and traffic barrels along road trajectories.
"""

import math
import random
from typing import Any, Dict, List
import uuid

from core.projection import lat_lon_to_meters
from fetchers.osm import RoadSegment
from processing.heightmap import HeightmapProcessor

LAMP_POST_DAE = "/assets/meshes/props/urban/lighting/s_lamp_post_street_single_01.dae"
GUARDRAIL_DAE = "/assets/meshes/props/assembly_kit/ak_guardrail_001/ak_bridge_guardrail_001.dae"
TRAFFIC_BARREL_DAE = "/assets/meshes/props/race_event/equipment/s_trafficbarrel_01.dae"


class RoadDecorationBuilder:
    """Generates 3D physical props along the road network."""

    def __init__(
        self,
        heightmap: HeightmapProcessor,
        origin_lat: float,
        origin_lon: float,
        size_meters: float,
    ):
        self.heightmap = heightmap
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.size = size_meters

    def generate_decorations(self, roads: List[RoadSegment]) -> List[Dict[str, Any]]:
        """Generates TSStatic props (streetlights, barriers) along roads."""
        items: List[Dict[str, Any]] = []

        lamp_idx = 0
        barrel_idx = 0

        for road in roads:
            if len(road.nodes) < 2:
                continue

            pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in road.nodes
            ]

            # 1. Streetlights along urban & primary roads (every 50 meters)
            is_urban = road.highway_type in {
                "primary", "secondary", "tertiary", "residential", "raceway", "trunk"
            }
            if is_urban and not road.is_tunnel:
                step = 50.0
                cur_dist = 0.0

                for i in range(len(pts) - 1):
                    p1, p2 = pts[i], pts[i + 1]
                    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                    seg_len = math.hypot(dx, dy)
                    if seg_len < 5.0:
                        continue

                    ux, uy = dx / seg_len, dy / seg_len
                    # Normal vector pointing to the right side of the road
                    nx, ny = uy, -ux

                    # Orient streetlight so its arm (extending along -Y in local mesh) hangs over the road
                    yaw = math.atan2(-nx, ny)

                    while cur_dist < seg_len:
                        sx = p1[0] + ux * cur_dist + nx * (road.width / 2.0 + 1.2)
                        sy = p1[1] + uy * cur_dist + ny * (road.width / 2.0 + 1.2)

                        if abs(sx) < self.size / 2.0 and abs(sy) < self.size / 2.0:
                            sz = self.heightmap.get_elevation_at_meters(sx, sy)
                            items.append({
                                "name": f"streetlight_{lamp_idx}",
                                "class": "TSStatic",
                                "persistentId": str(uuid.uuid4()),
                                "__parent": "MissionGroup",
                                "position": [round(sx, 2), round(sy, 2), round(sz, 2)],
                                "rotationMatrix": [
                                    round(math.cos(yaw), 4), round(-math.sin(yaw), 4), 0.0,
                                    round(math.sin(yaw), 4), round(math.cos(yaw), 4), 0.0,
                                    0.0, 0.0, 1.0,
                                ],
                                "scale": [1.0, 1.0, 1.0],
                                "shapeName": LAMP_POST_DAE,
                                "collisionType": "Visible Mesh Final",
                            })
                            lamp_idx += 1

                        cur_dist += step

                    cur_dist -= seg_len

            # 2. Race track / High-speed road traffic barrels at sharp corners
            if road.highway_type in {"raceway", "motorway"} or road.is_bridge:
                for i in range(1, len(pts) - 1):
                    p_prev, p_cur, p_next = pts[i - 1], pts[i], pts[i + 1]
                    d1 = (p_cur[0] - p_prev[0], p_cur[1] - p_prev[1])
                    d2 = (p_next[0] - p_cur[0], p_next[1] - p_cur[1])
                    len1, len2 = math.hypot(*d1), math.hypot(*d2)
                    if len1 < 2.0 or len2 < 2.0:
                        continue

                    # Dot product to detect sharp curve
                    dot = (d1[0] * d2[0] + d1[1] * d2[1]) / (len1 * len2)
                    if dot < 0.85:  # Curve > ~30 degrees
                        # Place a cluster of 3 safety barrels on the outside of the turn
                        nx = -(d1[1] / len1)
                        ny = d1[0] / len1
                        offset_dist = (road.width / 2.0) + 1.8

                        bx = p_cur[0] + nx * offset_dist
                        by = p_cur[1] + ny * offset_dist
                        if abs(bx) < self.size / 2.0 and abs(by) < self.size / 2.0:
                            bz = self.heightmap.get_elevation_at_meters(bx, by)
                            items.append({
                                "name": f"traffic_barrel_{barrel_idx}",
                                "class": "TSStatic",
                                "persistentId": str(uuid.uuid4()),
                                "__parent": "MissionGroup",
                                "position": [round(bx, 2), round(by, 2), round(bz, 2)],
                                "scale": [1.0, 1.0, 1.0],
                                "shapeName": TRAFFIC_BARREL_DAE,
                                "collisionType": "Visible Mesh Final",
                            })
                            barrel_idx += 1

        print(f"[RoadDecorations] Placed {lamp_idx} streetlights and {barrel_idx} safety barrels/props.")
        return items
