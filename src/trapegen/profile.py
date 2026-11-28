"""True Y-plane sections and the analytic XY cutting profiles."""

from dataclasses import dataclass
from math import isfinite, radians, tan

import numpy as np
import trimesh
from shapely import LinearRing, Polygon, box, get_parts
from shapely.geometry.polygon import orient

from .config import ANGLE_RANGE, OFFSET_RANGE, GeometryError, Tolerances
from .sections import section_regions


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
    a_section_xyz_mm: tuple[float, float, float]
    b_section_xyz_mm: tuple[float, float, float]

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
    regions, segments = section_regions(mesh, 1, y_red, tol)
    if not len(segments):
        raise GeometryError(f"No section at Y={y_red:g} mm.")
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


def _ab_extrema(section, ab_z_range_mm):
    points = section.points[:, [0, 2]]
    if ab_z_range_mm is not None:
        z_min, z_max = ab_z_range_mm
        contour = LinearRing(points)
        x_min, _, x_max, _ = contour.bounds
        clipped = contour.intersection(box(x_min, z_min, x_max, z_max))
        lines = [
            np.asarray(line.coords) for line in get_parts(clipped)
            if line.geom_type in ("LineString", "LinearRing") and line.length > 0
        ]
        if not lines:
            raise GeometryError(
                f"A/B Z range [{z_min:g}, {z_max:g}] mm contains no contour segments "
                f"at Y={section.y_mm:g} mm."
            )
        points = np.concatenate(lines)
    left = points[np.argmin(points[:, 0])]
    right = points[np.argmax(points[:, 0])]
    return tuple((float(x), section.y_mm, float(z)) for x, z in (left, right))


def build_trapezoid(section, y_blue, angle_deg, tol, *, ab_z_range_mm=None):
    y_red = section.y_mm
    a, b = _ab_extrema(section, ab_z_range_mm)
    x_a, x_b = a[0], b[0]
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
        lower, upper, height, angle_deg, inset, (lower + upper) * height / 2, a, b,
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
