"""Planar mesh sections and dimensional checks on serialized results."""

from math import isfinite

import numpy as np
import trimesh
from shapely import LineString, Polygon, box, get_parts, polygonize_full, union_all

from .config import GeometryError


def section_regions(mesh, axis, height, tol):
    """Return material polygons and raw segments at an axis-aligned section."""
    basis = np.eye(3)[axis]
    segments = trimesh.intersections.mesh_plane(mesh, basis, height * basis)
    if not len(segments):
        return [], segments

    # Snap shared endpoints while preserving a true intersection coordinate.
    planar = np.delete(segments, axis, axis=2).reshape(-1, 2)
    _, first, inverse = np.unique(
        np.rint(planar / tol.section_snap_mm), axis=0, return_index=True, return_inverse=True
    )
    pairs = np.unique(np.sort(inverse.reshape(-1, 2), axis=1), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    lines = [LineString(coords) for coords in planar[first][pairs]]
    polygons, cuts, dangles, invalid = polygonize_full(lines)
    if any(not geom.is_empty for geom in (cuts, dangles, invalid)):
        name = "XYZ"[axis]
        raise GeometryError(
            f"Section {name}={height:g} mm has open or ambiguous edges "
            f"(cuts={len(cuts.geoms)}, dangles={len(dangles.geoms)}, invalid={len(invalid.geoms)})."
        )

    # Polygonize returns both sides of each interior ring. Include material
    # regions at even nesting depth and retain each region's immediate holes.
    candidates = list(polygons.geoms)
    shells = [Polygon(poly.exterior) for poly in candidates]
    regions = [
        poly for i, poly in enumerate(candidates)
        if sum(parent.contains(shells[i]) for j, parent in enumerate(shells)
               if j != i and parent.area > shells[i].area) % 2 == 0
    ]
    regions.sort(key=lambda poly: (-poly.area, *poly.bounds))
    return regions, segments


def _finite_values(values, name):
    try:
        if isinstance(values, (str, bytes, dict)):
            raise TypeError
        values = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GeometryError(f"{name} must be a sequence of finite millimeter positions.") from exc
    if not all(isfinite(value) for value in values):
        raise GeometryError(f"{name} must be a sequence of finite millimeter positions.")
    return values


def normalize_ab_range(values):
    if values is None:
        return None
    values = _finite_values(values, "A/B Z range")
    if len(values) != 2 or values[0] >= values[1]:
        raise GeometryError("A/B Z range must be two increasing positions in local mm.")
    return values


def normalize_ab_x_offsets(values):
    if values is None:
        return (0.0, 0.0)
    offsets = _finite_values(values, "A/B X offsets")
    if len(offsets) != 2:
        raise GeometryError("A/B X offsets must contain two values in local mm.")
    return offsets


def normalize_measure_depths(values, bounds):
    if values is None:
        return ()
    depths = _finite_values(values, "Section measurement Z")
    z_min, z_max = bounds[:, 2]
    for z_mm in depths:
        if not z_min < z_mm < z_max:
            raise GeometryError(
                f"Section measurement Z={z_mm:g} mm must be inside the input depth "
                f"({z_min:g}, {z_max:g}) mm."
            )
    return tuple(dict.fromkeys(depths))


def _dimensions(shape, blue_y, slack):
    if shape.is_empty:
        return {
            "bounds_xy_mm": None, "width_mm": 0.0, "height_mm": 0.0, "area_mm2": 0.0,
            "regions": 0, "holes": 0, "blue_band_x_coverage_mm": 0.0,
        }
    xmin, ymin, xmax, ymax = shape.bounds
    band = shape.intersection(box(xmin, blue_y - slack, xmax, blue_y + slack))
    intervals = []
    for part in get_parts(band):
        if part.is_empty:
            continue
        left, _, right, _ = part.bounds
        if left < right:
            intervals.append(LineString([(left, 0), (right, 0)]))
    parts = get_parts(shape)
    return {
        "bounds_xy_mm": [[xmin, ymin], [xmax, ymax]],
        "width_mm": xmax - xmin,
        "height_mm": ymax - ymin,
        "area_mm2": shape.area,
        "regions": len(parts),
        "holes": sum(len(part.interiors) for part in parts),
        "blue_band_x_coverage_mm": union_all(intervals).length,
    }


def compare_export_sections(stock, finished, keep_polygon, blue_y, depths, tol, coordinate_slack, *, connector=None):
    """Compare serialized XY material sections with the clipped stock outlines."""
    slack = max(tol.section_snap_mm, tol.coordinate_mm + coordinate_slack)
    reports = []
    for z in depths:
        stock_regions, _ = section_regions(stock, 2, z, tol)
        result_regions, _ = section_regions(finished, 2, z, tol)
        expected = union_all(stock_regions).intersection(keep_polygon)
        # Discard contact lines and points. A mixed collection can contain a
        # MultiPolygon alongside these zero-area contacts.
        expected = union_all([
            part for part in get_parts(get_parts(expected)) if part.geom_type == "Polygon"
        ])
        if connector is not None:
            expected = connector.apply_xy_section(expected, z)
        actual = union_all(result_regions)
        missing = expected.difference(actual).area
        excess = actual.difference(expected).area
        if expected.is_empty or actual.is_empty:
            matches = expected.is_empty and actual.is_empty
        else:
            matches = expected.buffer(slack).covers(actual) and actual.buffer(slack).covers(expected)
        if not matches:
            raise GeometryError(
                f"Result section Z={z:g} mm differs from the expected material outline "
                f"(missing area {missing:.6g} mm², excess area {excess:.6g} mm²; "
                f"coordinate tolerance {slack:.6g} mm)."
            )
        reports.append({
            "z_mm": z,
            "expected": _dimensions(expected, blue_y, slack),
            "actual": _dimensions(actual, blue_y, slack),
            "missing_area_mm2": missing,
            "excess_area_mm2": excess,
            "coordinate_tolerance_mm": float(slack),
        })
    return reports
