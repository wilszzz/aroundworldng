"""
Configuration settings for AroundWorldNG generator.
"""

from dataclasses import dataclass, field
import os
import pathlib
from typing import Optional


def get_default_beamng_mods_dir() -> Optional[pathlib.Path]:
    """Detects BeamNG.drive user mods directory if installed."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    
    beamng_root = pathlib.Path(local_app_data) / "BeamNG.drive"
    if not beamng_root.exists():
        return None
    
    # Check for version folders like 0.33, 0.34, 0.35, etc.
    version_dirs = [d for d in beamng_root.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()]
    if version_dirs:
        # Pick the latest version
        latest = sorted(version_dirs, key=lambda p: [int(x) for x in p.name.split(".") if x.isdigit()])[-1]
        mods_dir = latest / "mods"
        mods_dir.mkdir(exist_ok=True)
        return mods_dir
    
    return None


@dataclass
class MapConfig:
    """Parameters for generating a specific BeamNG level."""
    # Identification
    level_name: str = "custom_yandex_map"
    title: str = "Custom Real-World Map"
    description: str = "Generated with AroundWorldNG from Yandex Maps and OSM"
    author: str = "AroundWorldNG"
    
    # Bounding Box / Area
    center_lat: float = 55.751244
    center_lon: float = 37.618423
    size_meters: float = 2048.0          # Width and height of the map area in meters
    
    # Terrain specs
    # Heightmap resolution must be (2^n + 1): 1025, 2049, 4097
    heightmap_res: int = 2049
    square_size: float = 1.0             # Meters per heightmap pixel (size_meters = (res - 1) * square_size)
    max_height_meters: float = 600.0     # Maximum vertical span supported in 16-bit heightmap
    
    # Satellite Imagery (Yandex)
    sat_zoom: int = 18                   # Zoom level for satellite imagery tiles (17-19)
    save_orthophoto: bool = True
    
    # Features toggles
    generate_roads: bool = True
    generate_bridges: bool = True
    generate_forest: bool = True
    generate_buildings: bool = True
    generate_water: bool = True
    generate_ai_navgraph: bool = True
    
    # Road properties & Carving
    road_carve_smoothing: float = 2.0    # Gaussian sigma for smoothing terrain along roads
    road_exclusion_buffer: float = 4.0   # Meters around roads where buildings & trees cannot spawn
    
    # Output
    output_dir: pathlib.Path = field(default_factory=lambda: pathlib.Path("build"))
    pack_zip: bool = True
    install_to_beamng: bool = False
    
    def __post_init__(self):
        # Automatically adjust squareSize so heightmap fits size_meters
        self.square_size = self.size_meters / (self.heightmap_res - 1)
