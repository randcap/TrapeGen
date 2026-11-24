"""True Y-plane sections and the analytic XY cutting profiles."""

from dataclasses import dataclass
from math import isfinite, radians, tan

import numpy as np
import trimesh
from shapely import LineString, Polygon, polygonize_full
from shapely.geometry.polygon import orient

from .config import ANGLE_RANGE, OFFSET_RANGE, GeometryError, Tolerances


@dataclass(frozen=True)
class Section:
    y_mm: float
    points: np.ndarray
    segments: np.ndarray
    contour_index: int
    contour_areas_mm2: tuple[float, ...]


@dataclass(frozen=True)
class Trapezoid:
    A: tuple[float, float]
    B: tuple[float, float]
    C: tuple[float, float]
    D: tuple[float, float]
    lower_width_mm: float
    upper_width_mm: float
    height_mm: float
    angle_deg: float
    inset_mm: float
    area_mm2: float

    @property
    def ring(self):
        return np.array([self.A, self.B, self.D, self.C])


def check_parameters(blue_y, yellow_y, offset_mm, angle_deg, margin_mm, tol):
    if not all(isfinite(v) for v in (blue_y, yellow_y, offset_mm, angle_deg, margin_mm)):
        raise GeometryError("Reference heights and parameters must be finite.")
    if not OFFSET_RANGE[0] <= offset_mm <= OFFSET_RANGE[1]:
        raise GeometryError(f"Offset must be in {OFFSET_RANGE} mm.")
    if not ANGLE_RANGE[0] <= angle_deg <= ANGLE_RANGE[1]:
        raise GeometryError(f"Angle must be in {ANGLE_RANGE} degrees.")
    if margin_mm <= 0:
        raise GeometryError("Extrusion margin must be positive.")
    y_red = yellow_y + offset_mm
    if blue_y - y_red <= tol.coordinate_mm:
        raise GeometryError("Blue reference must be above the computed red plane.")
    return y_red


def slice_mesh(mesh, y_red: float, contour_index: int | None, tol: Tolerances):
    if not mesh.bounds[0, 1] < y_red < mesh.bounds[1, 1]:
        raise GeometryError(f"Red plane Y={y_red:g} mm is outside the interior of the STL bounds.")
    segments = trimesh.intersections.mesh_plane(mesh, [0, 1, 0], [0, y_red, 0])
    if not len(segments):
        raise GeometryError(f"No section at Y={y_red:g} mm.")
    # Snap numerically equivalent segment endpoints while retaining an original
    # intersection coordinate for each group.
    xz = segments[:, :, [0, 2]].reshape(-1, 2)
    _, first, inverse = np.unique(
        np.rint(xz / tol.section_snap_mm), axis=0, return_index=True, return_inverse=True
    )
    pairs = np.unique(np.sort(inverse.reshape(-1, 2), axis=1), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    lines = [LineString(coords) for coords in xz[first][pairs]]
    polygons, cuts, dangles, invalid = polygonize_full(lines)
    if any(not geom.is_empty for geom in (cuts, dangles, invalid)):
        raise GeometryError(
            f"Section Y={y_red:g} mm has open or ambiguous edges "
            f"(cuts={len(cuts.geoms)}, dangles={len(dangles.geoms)}, invalid={len(invalid.geoms)})."
        )

    # Polygonize returns both faces on either side of a hole boundary.
    # Keep contours at even nesting depth, with their immediate holes.
    candidates = list(polygons.geoms)
    shells = [Polygon(poly.exterior) for poly in candidates]
    regions = [
        poly for i, poly in enumerate(candidates)
        if sum(shell.contains(shells[i]) for j, shell in enumerate(shells)
               if j != i and shell.area > shells[i].area) % 2 == 0
    ]
    regions.sort(key=lambda poly: (-poly.area, *poly.bounds))
    if not regions:
        raise GeometryError(f"No solid section at Y={y_red:g} mm.")
    areas = tuple(float(poly.area) for poly in regions)
    if contour_index is None and len(regions) > 1:
        raise GeometryError(
            f"Section has {len(regions)} independent contours, with areas {areas} mm². "
            "Specify contour_index (0 is the largest)."
        )
    index = 0 if contour_index is None else contour_index
    if not 0 <= index < len(regions):
        raise GeometryError(f"Section contour index must be in [0, {len(regions) - 1}].")
    coords = np.asarray(regions[index].exterior.coords)[:-1]
    points = np.column_stack((coords[:, 0], np.full(len(coords), y_red), coords[:, 1]))
    return Section(y_red, points, segments, index, areas)


def build_trapezoid(section, y_blue, angle_deg, tol):
    y_red = section.y_mm
    x_a, x_b = float(section.points[:, 0].min()), float(section.points[:, 0].max())
    y_blue = float(y_blue)
    height = y_blue - y_red
    inset = height / tan(radians(angle_deg))
    lower = x_b - x_a
    upper = lower - 2 * inset
    if lower <= tol.coordinate_mm:
        raise GeometryError("Selected section has negligible X width.")
    if upper <= tol.coordinate_mm:
        raise GeometryError(f"Trapezoid upper base is not positive ({upper:g} mm).")
    geometry = Trapezoid(
        (x_a, y_red), (x_b, y_red), (x_a + inset, y_blue), (x_b - inset, y_blue),
        lower, upper, height, angle_deg, inset, (lower + upper) * height / 2,
    )
    return geometry, checked_polygon(geometry.ring)


def checked_polygon(vertices):
    polygon = orient(Polygon(vertices), sign=1.0)
    if not polygon.is_valid or polygon.area <= 0 or not polygon.exterior.is_ccw:
        raise GeometryError("Cutting profile is not a valid positive-area polygon.")
    return polygon


def build_keep(geometry, bounds, margin):
    x_min, y_min, _ = bounds[0]
    x_max = bounds[1, 0]
    left, right, bottom = x_min - margin, x_max + margin, y_min - margin
    y = geometry.A[1]
    rectangle = [[left, bottom], [right, bottom], [right, y], [left, y]]
    polygon = checked_polygon([
        *rectangle[:3], geometry.B, geometry.D, geometry.C, geometry.A, rectangle[3]
    ])
    if not polygon.covers(Polygon(rectangle)):
        raise GeometryError("Keep profile does not cover the complete lower projection.")
    return polygon


def extrude(polygon, z_start, z_end):
    result = trimesh.creation.extrude_polygon(polygon, z_end - z_start, engine="earcut")
    result.apply_translation([0, 0, z_start])
    return result
