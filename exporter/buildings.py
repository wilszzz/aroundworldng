"""
Procedural Architectural Building Exporter for BeamNG.drive.
Transforms OSM building footprints into rich, multi-story architectural meshes
grouped by spatial sectors into art/shapes/buildings/bld_sector_*.dae and
instantiates corresponding TSStatic entities in items.level.json.
"""

import math
import pathlib
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from core.projection import lat_lon_to_meters
from processing.heightmap import HeightmapProcessor
from exporter.building_mesh import (
    clean_ring,
    ProceduralBuildingMesh,
    write_sector_dae,
    SKIRT_DEPTH_M,
)


class BuildingExporter:
    """Translates OSM building polygons into procedural Collada sector models and BeamNG TSStatic objects."""

    def __init__(
        self,
        heightmap: HeightmapProcessor,
        level_name: str,
        origin_lat: float,
        origin_lon: float,
        output_dir: Optional[pathlib.Path] = None,
        sector_size: float = 256.0,
    ):
        self.heightmap = heightmap
        self.level_name = level_name
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.output_dir = output_dir
        self.sector_size = sector_size

    def export_buildings(
        self,
        building_polygons: List[Any],
        max_buildings: Optional[int] = None,
        output_dir: Optional[pathlib.Path] = None,
    ) -> List[Dict[str, Any]]:
        """
        Processes building polygons from OSM:
        1. Simplifies collinear vertices (clean_ring)
        2. Calculates height & floors (from tags or 2-5 floors @ 3m)
        3. Extrudes walls per floor with UV window bands (BeamNG facade atlas)
        4. Triangulates roof with architectural cornice / parapet
        5. Adds deep foundation skirt (-3.0m under lowest terrain point)
        6. Groups buildings into spatial sectors (bld_sector_*.dae)
        7. Returns TSStatic objects for items.level.json
        """
        target_dir = output_dir or self.output_dir or (pathlib.Path("levels") / self.level_name / "art" / "shapes" / "buildings")
        target_dir.mkdir(parents=True, exist_ok=True)

        # Dictionary mapping sector (sx, sy) -> ProceduralBuildingMesh and building centroid bounds
        sectors: Dict[Tuple[int, int], ProceduralBuildingMesh] = {}
        sector_bounds: Dict[Tuple[int, int], List[float]] = {}  # [min_x, min_y, min_z, max_x, max_y, max_z]

        count = 0
        for b_poly in building_polygons:
            if max_buildings is not None and count >= max_buildings:
                break
            if len(b_poly) < 3:
                continue

            # Convert lat/lon to local metric coordinates
            metric_pts = [
                lat_lon_to_meters(lat, lon, self.origin_lat, self.origin_lon)
                for lat, lon in b_poly
            ]

            # Simplify ring and ensure CCW orientation
            ring = clean_ring(metric_pts)
            if ring is None or len(ring) < 3:
                continue

            n = len(ring)
            cx = sum(p[0] for p in ring) / n
            cy = sum(p[1] for p in ring) / n

            # Query ground elevation
            z_verts = [self.heightmap.get_elevation_at_meters(p[0], p[1]) for p in ring]
            z_center = self.heightmap.get_elevation_at_meters(cx, cy)
            z_min = min(z_verts + [z_center])
            z_max = max(z_verts + [z_center])

            # Determine floors and height
            tags = getattr(b_poly, "tags", {})
            floors = None
            if "building:levels" in tags:
                try:
                    floors = max(1, min(50, int(float(tags["building:levels"]))))
                except (ValueError, TypeError):
                    pass
            elif "levels" in tags:
                try:
                    floors = max(1, min(50, int(float(tags["levels"]))))
                except (ValueError, TypeError):
                    pass
            elif "height" in tags:
                try:
                    h_val = float(str(tags["height"]).replace("m", "").strip())
                    floors = max(1, min(50, int(round(h_val / 3.0))))
                except (ValueError, TypeError):
                    pass

            seed = int(abs(hash((round(cx, 1), round(cy, 1)))))
            poly_area = 0.5 * abs(sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n)))

            b_type = str(tags.get("building", "")).lower().strip()
            is_house_type = b_type in (
                "house", "detached", "residential", "semidetached_house",
                "bungalow", "cabin", "cottage", "shed", "garage", "hut",
                "terrace", "farm", "villa"
            )
            is_highrise_type = b_type in (
                "apartments", "office", "commercial", "hotel", "hospital",
                "retail", "industrial", "warehouse", "civic", "school", "university"
            )

            if floors is None:
                if b_type in ("shed", "garage", "hut"):
                    floors = 1
                elif is_house_type:
                    floors = 1 if (seed % 3 == 0) else 2
                elif poly_area < 90.0:
                    floors = 1 if (seed % 2 == 0) else 2
                elif poly_area < 220.0:
                    floors = 2 if (seed % 3 != 0) else 1
                elif poly_area < 500.0:
                    floors = 2 + (seed % 3)  # 2, 3, or 4 floors
                else:
                    floors = 3 + (seed % 4)  # 3, 4, 5, or 6 floors

            floor_h = 3.0
            total_height = floors * floor_h

            # Skirt depth: 3.0m under lowest terrain point under building
            base_z = z_max
            z_base = z_min - SKIRT_DEPTH_M
            z_eave = base_z + total_height

            # Band styling
            band_idx = (seed >> 3) % 4
            is_house = (is_house_type or (poly_area < 260.0 and floors <= 2)) and not is_highrise_type
            z_roof_top = z_eave + (3.5 if is_house else 0.5)

            # Find spatial sector
            sx = int(math.floor(cx / self.sector_size))
            sy = int(math.floor(cy / self.sector_size))
            sec_key = (sx, sy)

            if sec_key not in sectors:
                sectors[sec_key] = ProceduralBuildingMesh()
                sector_bounds[sec_key] = [cx, cy, z_base, cx, cy, z_roof_top]
            else:
                b = sector_bounds[sec_key]
                b[0] = min(b[0], cx)
                b[1] = min(b[1], cy)
                b[2] = min(b[2], z_base)
                b[3] = max(b[3], cx)
                b[4] = max(b[4], cy)
                b[5] = max(b[5], z_roof_top)

            # Extrude building into sector mesh
            sectors[sec_key].extrude_building(
                ring=ring,
                base_z=base_z,
                z_base=z_base,
                z_eave=z_eave,
                floors=floors,
                floor_h=floor_h,
                band_idx=band_idx,
                is_house=is_house,
            )
            count += 1

        items: List[Dict[str, Any]] = []

        # Export each sector to .dae and create TSStatic object
        for (sx, sy), mesh in sectors.items():
            if len(mesh.verts) == 0:
                continue

            sec_b = sector_bounds[(sx, sy)]
            # Sector origin
            sec_cx = (sec_b[0] + sec_b[3]) / 2.0
            sec_cy = (sec_b[1] + sec_b[4]) / 2.0
            sec_cz = sec_b[2]

            dae_filename = f"bld_sector_{sx}_{sy}.dae"
            dae_path = target_dir / dae_filename

            write_sector_dae(
                output_path=dae_path,
                mesh=mesh,
                sector_origin=(sec_cx, sec_cy, sec_cz),
            )

            ts_static = {
                "name": f"bld_sector_{sx}_{sy}",
                "class": "TSStatic",
                "persistentId": str(uuid.uuid4()),
                "__parent": "MissionGroup",
                "position": [round(sec_cx, 2), round(sec_cy, 2), round(sec_cz, 2)],
                "rotationMatrix": [
                    1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0,
                ],
                "scale": [1.0, 1.0, 1.0],
                "shapeName": f"/levels/{self.level_name}/art/shapes/buildings/{dae_filename}",
                "collisionType": "Visible Mesh",
            }
            items.append(ts_static)

        print(
            f"[BuildingExporter] Successfully generated {count} procedural buildings "
            f"across {len(items)} sector DAEs with Visible Mesh collision."
        )
        return items
