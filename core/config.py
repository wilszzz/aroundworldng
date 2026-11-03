"""
Configuration settings for AroundWorldNG generator.
"""

from dataclasses import dataclass, field
import os
import pathlib
import sys
from typing import Optional, Union


def get_resource_path(relative_path: Union[str, pathlib.Path]) -> pathlib.Path:
    """
    Get absolute path to resource, working across all environments:
    - PyInstaller --onefile (sys._MEIPASS)
    - PyInstaller --onedir (sys.executable parent and _internal subdir)
    - Development mode (project root relative to this file or cwd)
    """
    rel = pathlib.Path(relative_path)
    if rel.is_absolute():
        return rel

    candidates = []

    # If running inside a PyInstaller frozen executable
    if getattr(sys, "frozen", False):
        # 1. PyInstaller --onefile temporary extraction folder
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(pathlib.Path(meipass))
            candidates.append(pathlib.Path(meipass) / "_internal")

        # 2. PyInstaller --onedir mode: files reside in _internal or next to executable
        exe_dir = pathlib.Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "_internal")
        candidates.append(exe_dir)

    # 3. Development mode: project root is parent of 'core'
    try:
        project_root = pathlib.Path(__file__).resolve().parent.parent
        candidates.append(project_root)
    except Exception:
        pass
    candidates.append(pathlib.Path.cwd())

    # Search candidates for exact match or under parent subdirectories
    for base in candidates:
        target = base / rel
        if target.exists():
            return target
        for parent_cand in ["exporter", "ui"]:
            alt = base / parent_cand / rel
            if alt.exists():
                return alt

    # If not found yet, return best-effort candidate path
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return pathlib.Path(meipass) / rel
        exe_dir = pathlib.Path(sys.executable).resolve().parent
        if (exe_dir / "_internal").exists():
            return exe_dir / "_internal" / rel
        return exe_dir / rel

    project_root = pathlib.Path(__file__).resolve().parent.parent
    return project_root / rel


def get_default_beamng_mods_dir() -> Optional[pathlib.Path]:
    """Detects BeamNG.drive user mods directory if installed."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    
    # 1. Check modern post-v0.37 path: AppData/Local/BeamNG/BeamNG.drive/current/mods
    modern_mods = pathlib.Path(local_app_data) / "BeamNG" / "BeamNG.drive" / "current" / "mods"
    if modern_mods.parent.exists():
        modern_mods.mkdir(parents=True, exist_ok=True)
        return modern_mods

    # 2. Check legacy path: AppData/Local/BeamNG.drive/<version>/mods
    beamng_legacy = pathlib.Path(local_app_data) / "BeamNG.drive"
    if beamng_legacy.exists():
        version_dirs = [d for d in beamng_legacy.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()]
        if version_dirs:
            latest = sorted(version_dirs, key=lambda p: [int(x) for x in p.name.split(".") if x.isdigit()])[-1]
            mods_dir = latest / "mods"
            mods_dir.mkdir(parents=True, exist_ok=True)
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
    sat_max_res: int = 2048              # Max resolution for stitched orthophoto (2048 or 4096)
    
    # Features toggles
    generate_roads: bool = True
    generate_bridges: bool = True
    generate_forest: bool = True
    generate_buildings: bool = True
    generate_water: bool = True
    generate_ai_navgraph: bool = True
    
    # Road properties & Carving
    road_carve_smoothing: float = 2.0    # Gaussian sigma for smoothing terrain along roads
    road_exclusion_buffer: float = 0.8   # Meters around roads where buildings & trees cannot spawn
    
    # Output
    output_dir: pathlib.Path = field(default_factory=lambda: pathlib.Path("build"))
    pack_zip: bool = True
    install_to_beamng: bool = False
    
    def __post_init__(self):
        # Automatically adjust squareSize so heightmap fits size_meters
        self.square_size = self.size_meters / (self.heightmap_res - 1)
