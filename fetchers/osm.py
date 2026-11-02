"""
OpenStreetMap Data Fetcher.
Uses the official OpenStreetMap REST API (with Overpass API fallback)
to fetch roads, bridges, buildings, forests, and water bodies.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import requests

OSM_API_URL = "https://api.openstreetmap.org/api/0.6/map"
OVERPASS_SERVERS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]


@dataclass
class RoadSegment:
    osm_id: int
    highway_type: str
    nodes: List[Tuple[float, float]]  # [(lat, lon), ...]
    lanes: int = 2
    width: float = 7.0
    surface: str = "asphalt"
    is_bridge: bool = False
    is_tunnel: bool = False
    name: str = ""
    speed_limit: int = 60
    has_guardrail: bool = False
    is_lit: bool = False


@dataclass
class OSMData:
    roads: List[RoadSegment] = field(default_factory=list)
    buildings: List[List[Tuple[float, float]]] = field(default_factory=list)  # Polygons [(lat, lon), ...]
    forests: List[List[Tuple[float, float]]] = field(default_factory=list)    # Polygons [(lat, lon), ...]
    waters: List[List[Tuple[float, float]]] = field(default_factory=list)     # Polygons [(lat, lon), ...]


def estimate_road_width(highway_type: str, lanes: int, tags: Dict[str, str]) -> float:
    """Estimates realistic road width in meters based on OSM tags."""
    if "width" in tags:
        try:
            return float(tags["width"].replace("m", "").replace(",", ".").strip())
        except ValueError:
            pass

    lane_width_map = {
        "motorway": 3.75,
        "trunk": 3.75,
        "primary": 3.5,
        "secondary": 3.25,
        "tertiary": 3.0,
        "residential": 3.0,
        "unclassified": 2.75,
        "service": 2.5,
        "track": 2.5,
    }
    lw = lane_width_map.get(highway_type, 3.0)
    return lw * max(lanes, 1) + 1.0


class OSMFetcher:
    """Fetches and parses spatial vectors from OpenStreetMap."""

    def __init__(self, timeout: int = 25):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AroundWorldNG/1.0 (BeamNG Map Generator)",
        })

    def fetch_bbox_data(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
    ) -> OSMData:
        """
        Fetches all spatial features inside bounding box.
        Tries official OSM map API first, then falls back to Overpass.
        """
        print(f"[OSM] Querying map data for bbox ({min_lat:.5f}, {min_lon:.5f}) to ({max_lat:.5f}, {max_lon:.5f})...")
        
        # 1. Try official OSM API
        try:
            params = {"bbox": f"{min_lon:.6f},{min_lat:.6f},{max_lon:.6f},{max_lat:.6f}"}
            resp = self.session.get(OSM_API_URL, params=params, timeout=self.timeout)
            if resp.status_code == 200 and resp.content.startswith(b"<?xml"):
                return self._parse_osm_xml(resp.content)
            else:
                print(f"[OSM] Official API returned status {resp.status_code}, falling back...")
        except Exception as e:
            print(f"[OSM] Official API failed ({e}), falling back to Overpass...")

        # 2. Try Overpass servers fallback
        return self._fetch_overpass(min_lat, min_lon, max_lat, max_lon)

    def _parse_osm_xml(self, xml_bytes: bytes) -> OSMData:
        root = ET.fromstring(xml_bytes)
        nodes: Dict[int, Tuple[float, float]] = {}
        osm_result = OSMData()

        # Pass 1: Parse all nodes
        for el in root.findall("node"):
            nodes[int(el.attrib["id"])] = (float(el.attrib["lat"]), float(el.attrib["lon"]))

        # Pass 2: Parse ways
        for el in root.findall("way"):
            tags = {tag.attrib["k"]: tag.attrib["v"] for tag in el.findall("tag")}
            nd_refs = [int(nd.attrib["ref"]) for nd in el.findall("nd")]
            way_nodes = [nodes[ref] for ref in nd_refs if ref in nodes]
            if len(way_nodes) < 2:
                continue

            # Roads
            if "highway" in tags:
                hw_type = tags["highway"]
                if hw_type in {"footway", "path", "cycleway", "steps", "pedestrian", "corridor", "bridleway"}:
                    continue

                lanes_str = tags.get("lanes", "2")
                try:
                    lanes = int(lanes_str.split(";")[0])
                except (ValueError, IndexError):
                    lanes = 2

                width = estimate_road_width(hw_type, lanes, tags)
                surface = tags.get("surface", "asphalt")
                is_bridge = tags.get("bridge") in {"yes", "true", "1"}
                is_tunnel = tags.get("tunnel") in {"yes", "true", "1"}
                name = tags.get("name", "")

                try:
                    speed = int(tags.get("maxspeed", "60").split()[0])
                except (ValueError, IndexError):
                    speed = 60

                has_guardrail = "barrier" in tags or tags.get("guardrail") == "yes"
                is_lit = tags.get("lit") == "yes"

                road = RoadSegment(
                    osm_id=int(el.attrib["id"]),
                    highway_type=hw_type,
                    nodes=way_nodes,
                    lanes=lanes,
                    width=width,
                    surface=surface,
                    is_bridge=is_bridge,
                    is_tunnel=is_tunnel,
                    name=name,
                    speed_limit=speed,
                    has_guardrail=has_guardrail,
                    is_lit=is_lit,
                )
                osm_result.roads.append(road)

            # Buildings (must have at least 3 points)
            elif "building" in tags and len(way_nodes) >= 3:
                osm_result.buildings.append(way_nodes)

            # Forests / Woods
            elif (tags.get("landuse") == "forest" or tags.get("natural") == "wood") and len(way_nodes) >= 3:
                osm_result.forests.append(way_nodes)

            # Waters / Rivers
            elif (tags.get("natural") == "water" or tags.get("waterway") in {"river", "stream"}) and len(way_nodes) >= 2:
                osm_result.waters.append(way_nodes)

        print(
            f"[OSM] Parsed: {len(osm_result.roads)} roads, {len(osm_result.buildings)} buildings, "
            f"{len(osm_result.forests)} forest polygons, {len(osm_result.waters)} water bodies."
        )
        return osm_result

    def _fetch_overpass(self, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> OSMData:
        bbox_str = f"{min_lat:.6f},{min_lon:.6f},{max_lat:.6f},{max_lon:.6f}"
        query = f"""[out:json][timeout:{self.timeout}];
        (
          way["highway"]({bbox_str});
          way["building"]({bbox_str});
          way["landuse"="forest"]({bbox_str});
          way["natural"="wood"]({bbox_str});
          way["natural"="water"]({bbox_str});
          way["waterway"="river"]({bbox_str});
        );
        out body;
        >;
        out skel qt;"""

        for server in OVERPASS_SERVERS:
            try:
                resp = self.session.post(server, data={"data": query}, timeout=self.timeout)
                if resp.status_code == 200:
                    return self._parse_overpass_json(resp.json())
            except Exception:
                pass
        return OSMData()

    def _parse_overpass_json(self, data: Dict[str, Any]) -> OSMData:
        # Fallback parser for overpass json if needed
        nodes = {el["id"]: (el["lat"], el["lon"]) for el in data.get("elements", []) if el.get("type") == "node"}
        osm_result = OSMData()
        for way in [el for el in data.get("elements", []) if el.get("type") == "way"]:
            tags = way.get("tags", {})
            coords = [nodes[nid] for nid in way.get("nodes", []) if nid in nodes]
            if len(coords) < 2:
                continue
            if "highway" in tags:
                hw = tags["highway"]
                if hw not in {"footway", "path", "cycleway", "steps", "pedestrian"}:
                    osm_result.roads.append(
                        RoadSegment(
                            osm_id=way["id"],
                            highway_type=hw,
                            nodes=coords,
                            name=tags.get("name", ""),
                        )
                    )
            elif "building" in tags and len(coords) >= 3:
                osm_result.buildings.append(coords)
            elif (tags.get("landuse") == "forest" or tags.get("natural") == "wood") and len(coords) >= 3:
                osm_result.forests.append(coords)
            elif tags.get("natural") == "water" and len(coords) >= 3:
                osm_result.waters.append(coords)
        return osm_result
