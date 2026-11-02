"""
Heightmap generation and sampling for BeamNG.drive.
Generates 16-bit uint PNG heightmaps and calculates Torque3D terrain parameters.
"""

from dataclasses import dataclass
import pathlib
from typing import Tuple
import numpy as np
from PIL import Image


@dataclass
class TerrainSpecs:
    height_scale: float
    height_offset: float
    min_elev: float
    max_elev: float
    square_size: float
    resolution: int


class HeightmapProcessor:
    """Processes 2D elevation grids into 16-bit BeamNG-compliant heightmaps."""

    def __init__(self, elevations: np.ndarray, square_size: float = 1.0):
        """
        elevations: 2D float32 numpy array with shape (res, res)
        square_size: meters per pixel
        """
        assert elevations.shape[0] == elevations.shape[1], "Heightmap must be square"
        self.res = elevations.shape[0]
        self.square_size = square_size
        self.elevations = elevations.copy()

    def get_elevation_at_meters(self, x_meters: float, y_meters: float) -> float:
        """Samples elevation at local coordinates (meters from bottom-left corner)."""
        px = x_meters / self.square_size
        py = y_meters / self.square_size
        px = max(0.0, min(float(self.res - 1), px))
        py = max(0.0, min(float(self.res - 1), py))
        
        ix, iy = int(px), int(py)
        fx, fy = px - ix, py - iy
        ix_next = min(ix + 1, self.res - 1)
        iy_next = min(iy + 1, self.res - 1)

        # Bilinear interpolation
        h00 = self.elevations[iy, ix]
        h10 = self.elevations[iy, ix_next]
        h01 = self.elevations[iy_next, ix]
        h11 = self.elevations[iy_next, ix_next]

        h0 = h00 * (1 - fx) + h10 * fx
        h1 = h01 * (1 - fx) + h11 * fx
        return float(h0 * (1 - fy) + h1 * fy)

    def compute_specs(self) -> TerrainSpecs:
        min_elev = float(np.min(self.elevations))
        max_elev = float(np.max(self.elevations))
        # Ensure at least 10 meters vertical span
        span = max(max_elev - min_elev, 10.0)
        # 16-bit uint has range 0..65535
        height_scale = span / 65535.0
        height_offset = min_elev

        return TerrainSpecs(
            height_scale=height_scale,
            height_offset=height_offset,
            min_elev=min_elev,
            max_elev=max_elev,
            square_size=self.square_size,
            resolution=self.res,
        )

    def export_16bit_png(self, output_path: pathlib.Path) -> TerrainSpecs:
        """Exports 16-bit grayscale PNG for BeamNG."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        specs = self.compute_specs()

        normalized = (self.elevations - specs.height_offset) / specs.height_scale
        uint16_data = np.clip(normalized, 0, 65535).astype(np.uint16)

        # In BeamNG Torque3D, row 0 in image is Top, coordinate space is bottom-up
        # Pillow automatically handles uint16 array as mode I;16
        img = Image.fromarray(uint16_data)
        img.save(output_path)
        print(f"[Heightmap] Saved 16-bit heightmap ({self.res}x{self.res}) to {output_path}")
        print(f"            Elevation range: {specs.min_elev:.1f}m to {specs.max_elev:.1f}m (Scale: {specs.height_scale:.6f})")
        return specs
