"""Assembly features on the horizontal blue cut surface in local millimeters."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite, pi, sin

import numpy as np
from shapely import Polygon, area, box, get_parts, intersection, polygons, union_all
from shapely.affinity import rotate, scale, translate

from .config import GeometryError
from .mesh import checked_solid, from_solid, require_mesh, to_solid
from .profile import extrude
from .sections import section_regions


_SHAPES = {"circular": 64, "triangular": 3, "hexagonal": 6, "custom": 0}
_MAX_PROFILE_POINTS = 128
_XY_EXTRUSION_TO_XZY = [
    [1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1],
]


def _number(value, field):
    try:
        if isinstance(value, bool):
            raise TypeError
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GeometryError(f"Connector {field} must be finite.") from exc
    if not isfinite(number):
        raise GeometryError(f"Connector {field} must be finite.")
    return number


def _pair(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise GeometryError(f"Connector {field} must be an [X, Z] pair.")
    return tuple(_number(v, field) for v in value)


def _custom_polygon(vertices):
    if not isinstance(vertices, (list, tuple)) or not 3 <= len(vertices) <= _MAX_PROFILE_POINTS:
        raise GeometryError(f"Custom connector requires 3–{_MAX_PROFILE_POINTS} profile_xz vertices.")
    coords = np.asarray([_pair(point, "profile_xz vertex") for point in vertices])
    if np.array_equal(coords[0], coords[-1]):
        coords = coords[:-1]
    span = np.max(np.abs(coords))
    if len(coords) < 3 or span == 0 or len(np.unique(coords, axis=0)) != len(coords):
        raise GeometryError("Custom connector profile must have at least three distinct vertices.")
    polygon = Polygon(coords / span)
    if not polygon.is_valid or not polygon.area > 0:
        raise GeometryError("Custom connector profile must be a simple polygon with positive area.")
    center = polygon.centroid
    min_x, min_z, max_x, max_z = polygon.bounds
    extent = max(max_x - min_x, max_z - min_z)
    return scale(translate(polygon, -center.x, -center.y), 1 / extent, 1 / extent, origin=(0, 0))


@dataclass(frozen=True)
class ConnectorSpec:
    preset: str
    size_mm: float
    depth_mm: float
    angle_deg: float
    offset_xz_mm: tuple[float, float]
    profile_xz: tuple[tuple[float, float], ...] | None

    @property
    def is_post(self):
        return self.preset.endswith("_post")

    def polygon(self):
        shape, _ = self.preset.split("_")
        sides = _SHAPES[shape]
        if shape == "custom":
            polygon = _custom_polygon(self.profile_xz)
        else:
            angles = np.arange(sides) * (2 * pi / sides)
            radius = 0.5 if shape == "circular" else 1 / (2 * sin(pi / sides))
            polygon = Polygon(radius * np.column_stack((np.cos(angles), np.sin(angles))))
        polygon = scale(polygon, self.size_mm, self.size_mm, origin=(0, 0))
        return rotate(polygon, -self.angle_deg, origin=(0, 0))


def parse_connector(options):
    if options is None:
        return None
    if not isinstance(options, Mapping):
        raise GeometryError("Connector must be an object.")
    fields = {"preset", "size_mm", "depth_mm", "angle_deg", "offset_xz_mm", "profile_xz"}
    unknown = options.keys() - fields
    if unknown:
        raise GeometryError(f"Unsupported connector fields: {', '.join(sorted(map(str, unknown)))}.")
    preset = options.get("preset")
    if not isinstance(preset, str) or preset not in {
        f"{shape}_{kind}" for shape in _SHAPES for kind in ("post", "hole")
    }:
        raise GeometryError("Connector preset must be a circular, triangular, hexagonal or custom post/hole.")
    size = _number(options.get("size_mm"), "size_mm")
    depth = _number(options.get("depth_mm"), "depth_mm")
    if min(size, depth) <= 0:
        raise GeometryError("Connector size_mm and depth_mm must be positive.")
    offset = _pair(options.get("offset_xz_mm", [0, 0]), "offset_xz_mm")
    angle = _number(options.get("angle_deg", 0), "angle_deg") % 360
    vertices = options.get("profile_xz")
    if preset.startswith("custom_"):
        _custom_polygon(vertices)
        # Preserve the supplied numbers for parameters.json and replay.
        vertices = tuple(_pair(point, "profile_xz vertex") for point in vertices)
    elif vertices is not None:
        raise GeometryError("profile_xz is only accepted for a custom connector.")
    return ConnectorSpec(preset, size, depth, angle, offset, vertices)


def _horizontal_triangles(mesh, y_mm, slack):
    triangles = mesh.triangles
    mask = (mesh.face_normals[:, 1] > 0) & np.all(np.abs(triangles[:, :, 1] - y_mm) <= slack, axis=1)
    return triangles[mask]


def connector_surface(mesh, blue_y, tol):
    triangles = _horizontal_triangles(mesh, blue_y, tol.coordinate_mm)
    footprint = union_all(polygons(triangles[:, :, [0, 2]]))
    regions = [part for part in get_parts(footprint) if part.geom_type == "Polygon" and part.area > 0]
    if not regions:
        raise GeometryError("No horizontal cut surface at the blue height for a connector.")
    return sorted(regions, key=lambda part: (-part.area, part.bounds))


def describe_surface(mesh, blue_y, tol):
    regions = connector_surface(mesh, blue_y, tol)
    center = regions[0].centroid
    return {
        "blue_y_mm": blue_y,
        "center_xz_mm": [center.x, center.y],
        "regions": [
            {
                "outline_xz_mm": list(region.exterior.coords)[:-1],
                "holes_xz_mm": [list(ring.coords)[:-1] for ring in region.interiors],
            }
            for region in regions
        ],
    }


def _prism(profile, y_min, y_max):
    # Extrude a CCW profile into +Y using a proper rotation. Reflecting the
    # planar Z coordinate before extrusion keeps the world XZ profile unchanged.
    reflected = scale(profile, 1, -1, origin=(0, 0))
    mesh = extrude(reflected, y_min, y_max)
    mesh.apply_transform(_XY_EXTRUSION_TO_XZY)
    return to_solid(mesh, "Connector prism")


@dataclass(frozen=True)
class AppliedConnector:
    spec: ConnectorSpec
    profile: Polygon
    center_xz_mm: tuple[float, float]
    blue_y_mm: float

    @property
    def end_y_mm(self):
        direction = 1 if self.spec.is_post else -1
        return self.blue_y_mm + direction * self.spec.depth_mm

    def describe(self):
        return {
            "preset": self.spec.preset,
            "center_xz_mm": self.center_xz_mm,
            "profile_xz_mm": list(self.profile.exterior.coords)[:-1],
            "area_mm2": self.profile.area,
            "start_y_mm": self.blue_y_mm,
            "end_y_mm": self.end_y_mm,
        }

    def apply_xy_section(self, stock_section, z_mm):
        _, min_z, _, max_z = self.profile.bounds
        if not min_z <= z_mm < max_z:
            return stock_section
        # Use the +Z side of a coplanar edge, matching the mesh section rule.
        points = np.asarray(self.profile.exterior.coords)
        start, end = points[:-1], points[1:]
        cross = (start[:, 1] > z_mm) != (end[:, 1] > z_mm)
        start, end = start[cross], end[cross]
        x = start[:, 0] + (end[:, 0] - start[:, 0]) * (z_mm - start[:, 1]) / (end[:, 1] - start[:, 1])
        y_min, y_max = sorted((self.blue_y_mm, self.end_y_mm))
        feature = union_all([
            box(left, y_min, right, y_max) for left, right in np.sort(x).reshape(-1, 2) if right > left
        ])
        return stock_section.union(feature) if self.spec.is_post else stock_section.difference(feature)


def apply_connector(spec, base, base_mesh, blue_y, tol):
    regions = connector_surface(base_mesh, blue_y, tol)
    anchor = regions[0].centroid
    center = (anchor.x + spec.offset_xz_mm[0], anchor.y + spec.offset_xz_mm[1])
    footprint = union_all(regions)
    x_min, z_min, x_max, z_max = footprint.bounds
    # Bound obviously oversized input before passing it into the geometry kernel.
    if spec.size_mm > 2 * max(x_max - x_min, z_max - z_min) or not all(map(isfinite, center)):
        raise GeometryError("Connector footprint exceeds the blue cut surface.")
    profile = translate(spec.polygon(), *center)
    overlap = 8 * max(tol.coordinate_mm, base.get_tolerance())
    if spec.depth_mm <= overlap:
        raise GeometryError("Connector depth is below the solid geometry resolution.")
    if not footprint.buffer(-overlap).covers(profile):
        raise GeometryError("Connector must fit inside the blue cut surface.")
    feature = AppliedConnector(spec, profile, center, blue_y)
    end = feature.end_y_mm
    if not isfinite(end) or abs(end) > np.finfo(np.float32).max:
        raise GeometryError("Connector endpoint exceeds the supported STL coordinate range.")
    if end <= base_mesh.bounds[0, 1]:
        raise GeometryError("Connector hole would break through the part.")

    support_y = blue_y - overlap if spec.is_post else end - overlap
    support = _prism(profile.buffer(overlap, join_style="mitre"), support_y, blue_y)
    missing = checked_solid(support - base, "Connector support", allow_empty=True)
    if missing.volume() > tol.volume_abs_mm3:
        raise GeometryError("Connector would break through the part or lacks solid support.")
    tool = (
        _prism(profile, blue_y - overlap, end) if spec.is_post
        else _prism(profile, end, blue_y + overlap)
    )
    finished = checked_solid(base + tool if spec.is_post else base - tool, "Connector boolean")
    return feature, from_solid(finished)


def validate_connector(mesh, base_mesh, feature, tol, *, exported=False, coordinate_slack=0.0):
    report = require_mesh(mesh, tol, "Connector result", exported=exported)
    sign = 1 if feature.spec.is_post else -1
    expected_change = sign * feature.profile.area * feature.spec.depth_mm
    actual_change = report["volume_mm3"] - base_mesh.volume
    # Subtracting two volumes includes the binary STL precision of the full body.
    volume_limit = tol.volume_error(base_mesh.volume if exported else expected_change, exported=exported)
    if abs(actual_change - expected_change) > volume_limit:
        raise GeometryError("Connector material change differs from the requested prism volume.")
    if report["connected_components"] != base_mesh.body_count:
        raise GeometryError("Connector changed the number of connected components.")
    slack = max(tol.section_snap_mm, tol.coordinate_mm + coordinate_slack)
    bounds = base_mesh.bounds.copy()
    if feature.spec.is_post:
        bounds[1, 1] = feature.end_y_mm
    if not np.allclose(mesh.bounds, bounds, atol=slack, rtol=0):
        raise GeometryError("Connector result bounds differ from the requested geometry.")
    triangles = _horizontal_triangles(mesh, feature.end_y_mm, slack)
    end_patches = intersection(polygons(triangles[:, :, [0, 2]]), feature.profile.buffer(slack))
    if not union_all(end_patches).buffer(slack).covers(feature.profile):
        raise GeometryError("Connector tip or hole floor is missing at the requested depth.")
    heights = triangles[area(end_patches) > 0, :, 1]

    mid_y = (feature.blue_y_mm + feature.end_y_mm) / 2
    actual_mid = union_all(section_regions(mesh, 1, mid_y, tol)[0])
    expected_mid = feature.profile
    if not feature.spec.is_post:
        base_mid = union_all(section_regions(base_mesh, 1, mid_y, tol)[0])
        expected_mid = base_mid.difference(feature.profile)
    if not (actual_mid.buffer(slack).covers(expected_mid) and expected_mid.buffer(slack).covers(actual_mid)):
        raise GeometryError("Connector cross section differs from the requested profile.")
    report["connector"] = {
        **feature.describe(),
        "measured_end_y_range_mm": [float(heights.min()), float(heights.max())],
        "expected_volume_change_mm3": expected_change,
        "actual_volume_change_mm3": float(actual_change),
        "volume_tolerance_mm3": float(volume_limit),
        "coordinate_tolerance_mm": float(slack),
    }
    return report
