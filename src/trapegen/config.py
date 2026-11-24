"""Measurement tolerances and world-to-local coordinates."""

from dataclasses import astuple, dataclass
from math import isfinite

import numpy as np
import trimesh


class GeometryError(ValueError):
    """Input geometry or a generated solid failed a geometric check."""


UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
OFFSET_RANGE = (5.0, 10.0)
ANGLE_RANGE = (52.0, 55.0)
DEFAULT_OFFSET = 7.5
DEFAULT_ANGLE = 53.0


@dataclass(frozen=True)
class Tolerances:
    coordinate_mm: float = 1e-6
    section_snap_mm: float = 1e-7
    horizontal_mm: float = 1e-5
    degenerate_height_mm: float = 1e-9
    export_degenerate_height_mm: float = 0.0
    volume_abs_mm3: float = 1e-6
    volume_rel: float = 1e-7
    export_rel: float = 2e-6
    export_rounding_ulps: float = 4.0
    rigid: float = 1e-9

    def __post_init__(self):
        if not all(isfinite(v) and v >= 0 for v in astuple(self)) or self.section_snap_mm == 0:
            raise GeometryError("Tolerances must be finite and nonnegative, with a positive section snap.")

    def volume_error(self, volume: float, *, exported=False) -> float:
        relative = self.export_rel if exported else self.volume_rel
        return self.volume_abs_mm3 + relative * abs(volume)


class Frame:
    """Apply a rigid transform after scaling world coordinates to millimeters."""

    def __init__(self, stl_unit: str, transform, tol: Tolerances):
        if stl_unit not in UNIT_TO_MM:
            raise GeometryError(f"Unsupported STL unit {stl_unit!r}. Use {list(UNIT_TO_MM)}.")
        matrix = np.array(np.eye(4) if transform is None else transform, float)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise GeometryError("Transform must be a finite 4×4 matrix.")
        rotation = matrix[:3, :3]
        if not (
            np.allclose(matrix[3], [0, 0, 0, 1], atol=tol.rigid, rtol=0)
            and np.allclose(rotation.T @ rotation, np.eye(3), atol=tol.rigid, rtol=0)
            and np.isclose(np.linalg.det(rotation), 1, atol=tol.rigid, rtol=0)
        ):
            raise GeometryError("Transform must be a proper rigid transform with translation in mm.")
        self.stl_unit = stl_unit
        self.scale = UNIT_TO_MM[stl_unit]
        self.world_mm_to_local = matrix
        self.stl_to_local = matrix @ np.diag([self.scale, self.scale, self.scale, 1.0])
        self.local_to_stl = np.linalg.inv(self.stl_to_local)

    def points_to_local(self, world_mm):
        return trimesh.transform_points(world_mm, self.world_mm_to_local)

    def mesh_to_stl(self, mesh):
        result = mesh.copy()
        result.apply_transform(self.local_to_stl)
        return result
