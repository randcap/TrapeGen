"""Prepared input reuse, cutting pipeline and coordinate-aware export."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from numbers import Integral
from pathlib import Path

import numpy as np
import trimesh
from shapely import Polygon

from .config import DEFAULT_ANGLE, DEFAULT_OFFSET, Frame, GeometryError, Tolerances
from .connector import AppliedConnector, apply_connector, describe_surface, parse_connector, validate_connector
from .mesh import from_solid, intersect, load_stl, prepare_solid, require_mesh, to_solid, validate_result
from .profile import Section, Trapezoid, build_keep, build_trapezoid, check_parameters, extrude, slice_mesh
from .sections import compare_export_sections, normalize_ab_range, normalize_measure_depths


@dataclass
class GenerationResult:
    """In-memory meshes and geometry use local millimeters."""

    original_mesh: trimesh.Trimesh
    effective_input_mesh: trimesh.Trimesh
    section: Section
    trapezoid_polygon: Polygon
    trapezoid_mesh: trimesh.Trimesh
    assembly_region_mesh: trimesh.Trimesh | None
    keep_polygon: Polygon
    keep_mesh: trimesh.Trimesh
    result_mesh: trimesh.Trimesh
    geometry_parameters: Trapezoid
    validation_report: dict
    output_paths: dict[str, Path]
    parameters: dict
    connector: AppliedConnector | None = None
    base_result_mesh: trimesh.Trimesh | None = None

    @property
    def section_points(self):
        return self.section.points

    @property
    def trapezoid_vertices_2d(self):
        return self.geometry_parameters.ring


class TrapezoidGenerator:
    """Prepare reusable geometry. Each generation clips the same input solid."""

    def __init__(
        self, stl_path, igs_path=None, *, yellow_reference_y, blue_y=None,
        transform=None, stl_unit="mm", reference_index=None, contour_index=None,
        iges_backend="occt", union_overlapping_shells=False, tolerances=None,
        ab_z_range_mm=None, measure_z_mm=None, connector=None,
    ):
        from .reference import BlueReference, load_igs_reference

        if (igs_path is None) == (blue_y is None):
            raise GeometryError("Provide exactly one of igs_path or manual blue_y.")
        if igs_path is None and reference_index is not None:
            raise GeometryError("reference_index requires an IGES file.")
        for name, index in (("reference_index", reference_index), ("contour_index", contour_index)):
            if index is not None and (not isinstance(index, Integral) or index < 0):
                raise GeometryError(f"{name} must be a nonnegative integer.")
        self.tolerances = tolerances if tolerances is not None else Tolerances()
        self.frame = Frame(stl_unit, transform, self.tolerances)
        self.yellow_y = float(yellow_reference_y)
        self.contour_index = int(contour_index) if contour_index is not None else None
        self.ab_z_range_mm = normalize_ab_range(ab_z_range_mm)
        self.connector = parse_connector(connector)
        self.stl_path = Path(stl_path)
        self.igs_path = Path(igs_path) if igs_path is not None else None
        self.original_mesh = load_stl(stl_path)
        self.original_mesh.apply_transform(self.frame.stl_to_local)
        self.effective_mesh, self._input_solid, self._input_report = prepare_solid(
            self.original_mesh, self.tolerances, union_overlapping_shells=union_overlapping_shells
        )
        self.bounds = self.effective_mesh.bounds.copy()
        self.measure_z_mm = normalize_measure_depths(measure_z_mm, self.bounds)
        if self.igs_path is None:
            self.blue = BlueReference(float(blue_y), None, "manual local height", None)
        else:
            self.blue = load_igs_reference(
                self.igs_path, self.frame, self.tolerances,
                int(reference_index) if reference_index is not None else None, backend=iges_backend
            )
        self._section = None

    def generate(
        self, output_dir=None, *, offset_mm=DEFAULT_OFFSET, angle_deg=DEFAULT_ANGLE,
        margin_mm=1.0, export_intermediate=True, compute_assembly=True, visualize=False, connector=None,
    ):
        spec = self.connector if connector is None else parse_connector(connector)
        offset_mm, angle_deg, margin_mm = map(float, (offset_mm, angle_deg, margin_mm))
        tol = self.tolerances
        y_red = check_parameters(self.blue.y_mm, self.yellow_y, offset_mm, angle_deg, margin_mm, tol)
        section = self._section
        if section is None or section.y_mm != y_red:
            section = slice_mesh(self.effective_mesh, y_red, self.contour_index, tol)
            self._section = section
        geometry, profile = build_trapezoid(
            section, self.blue.y_mm, angle_deg, tol, ab_z_range_mm=self.ab_z_range_mm
        )
        keep_profile = build_keep(geometry, self.bounds, margin_mm)
        z_start = float(self.bounds[0, 2] - margin_mm)
        z_end = float(self.bounds[1, 2] + margin_mm)
        trapezoid_mesh = extrude(profile, z_start, z_end)
        keep_mesh = extrude(keep_profile, z_start, z_end)
        solid = intersect(self._input_solid, keep_mesh, "Final intersection")
        result_mesh = from_solid(solid)
        validation = {
            **deepcopy(self._input_report),
            "tolerances": asdict(tol),
            "result": validate_result(self._input_solid, solid, result_mesh, geometry, tol),
        }

        assembly = None
        if compute_assembly:
            assembly = from_solid(intersect(self._input_solid, trapezoid_mesh, "Assembly intersection"))
            assembly_report = require_mesh(assembly, tol, "Assembly")
            upper_volume = solid.volume() - validation["result"]["result_lower_volume_mm3"]
            delta = abs(assembly_report["volume_mm3"] - upper_volume)
            limit = tol.volume_error(upper_volume)
            if delta > limit:
                raise GeometryError(f"Assembly and upper result volumes differ by {delta:.6g} mm³.")
            validation["assembly"] = {
                **assembly_report,
                "upper_result_volume_mm3": upper_volume,
                "volume_difference_mm3": delta,
                "volume_tolerance_mm3": limit,
            }
        result = GenerationResult(
            self.original_mesh, self.effective_mesh, section, profile, trapezoid_mesh, assembly,
            keep_profile, keep_mesh, result_mesh, geometry, validation, {},
            {
                "stl_path": str(self.stl_path),
                "igs_path": str(self.igs_path) if self.igs_path is not None else None,
                "stl_unit": self.frame.stl_unit,
                "world_mm_to_local_mm": self.frame.world_mm_to_local.tolist(),
                "local_coordinates": "right-handed X left-right, Y up, Z extrusion; mm",
                "stl_output_coordinates": "original input coordinate frame and unit",
                "section_output_coordinates": "local XYZ in mm",
                "profile_output_coordinates": "local XY in mm",
                "blue_y_mm": self.blue.y_mm,
                "blue_reference_source": self.blue.source,
                "blue_reference_index": self.blue.index,
                "iges_length_unit_flag": self.blue.iges_unit_flag,
                "blue_reference_points_local_mm": (
                    self.blue.points.tolist() if self.blue.points is not None else None
                ),
                "red_y_mm": y_red,
                "yellow_y_mm": self.yellow_y,
                "offset_mm": offset_mm,
                "angle_deg": angle_deg,
                "margin_mm": margin_mm,
                "z_range_local_mm": [z_start, z_end],
                "section_contour_index": section.contour_index,
                "section_areas_mm2": section.contour_areas_mm2,
                "ab_z_range_mm": self.ab_z_range_mm,
                "a_section_xyz_mm": geometry.a_section_xyz_mm,
                "b_section_xyz_mm": geometry.b_section_xyz_mm,
                "measure_z_mm": self.measure_z_mm,
            },
        )
        if spec is not None:
            feature, finished_mesh = apply_connector(spec, solid, result_mesh, self.blue.y_mm, tol)
            result.connector = feature
            result.base_result_mesh = result_mesh
            result.result_mesh = finished_mesh
            validation["base_result"] = validation["result"]
            validation["result"] = validate_connector(finished_mesh, result_mesh, feature, tol)
            result.parameters["connector"] = asdict(spec)
        if output_dir is not None:
            self.export(result, output_dir, export_intermediate=export_intermediate)
        if visualize:
            from .visualization import show_debug

            show_debug(self, result, output_dir=output_dir, export_intermediate=export_intermediate)
        return result

    def describe_connector_surface(self, result):
        """Return the blue cut footprint before adding or removing the feature."""
        mesh = result.base_result_mesh if result.connector is not None else result.result_mesh
        return describe_surface(mesh, result.geometry_parameters.C[1], self.tolerances)

    def export(self, result, output_dir, *, export_intermediate=True):
        from .export import export_result

        export_result(self, result, output_dir, export_intermediate=export_intermediate)

    def validate_export(self, path, result, *, measure_z_mm=None):
        """Validate serialized STL, optionally comparing XY sections at local Z positions."""
        depths = self.measure_z_mm if measure_z_mm is None else normalize_measure_depths(
            measure_z_mm, self.bounds
        )
        mesh = load_stl(path)
        world_max_mm = np.max(np.abs(mesh.vertices)) * self.frame.scale
        slack = self.tolerances.export_rounding_ulps * np.finfo(np.float32).eps * world_max_mm
        mesh.apply_transform(self.frame.stl_to_local)
        solid = to_solid(mesh, "STL round trip")
        if result.connector is None:
            report = validate_result(
                self._input_solid, solid, mesh,
                result.geometry_parameters, self.tolerances, exported=True, coordinate_slack=slack,
            )
        else:
            report = validate_connector(
                mesh, result.base_result_mesh, result.connector, self.tolerances,
                exported=True, coordinate_slack=slack,
            )
            report["manifold_status"] = str(solid.status())
        if depths:
            report["section_measurements"] = compare_export_sections(
                self.effective_mesh, mesh, result.keep_polygon, result.geometry_parameters.C[1],
                depths, self.tolerances, slack, connector=result.connector,
            )
        return report


def generate_trapezoid_region(
    stl_path, igs_path=None, yellow_reference_y=None, output_dir=None, *,
    offset_mm=DEFAULT_OFFSET, angle_deg=DEFAULT_ANGLE, margin_mm=1.0, transform=None,
    stl_unit="mm", export_intermediate=True, visualize=False, blue_y=None,
    reference_index=None, contour_index=None, iges_backend="occt",
    union_overlapping_shells=False, tolerances=None, compute_assembly=True,
    ab_z_range_mm=None, measure_z_mm=None, connector=None,
):
    """One-shot API. Use TrapezoidGenerator when iterating on the same inputs."""
    if yellow_reference_y is None:
        raise GeometryError("yellow_reference_y is required in local mm.")
    generator = TrapezoidGenerator(
        stl_path, igs_path, yellow_reference_y=yellow_reference_y, blue_y=blue_y,
        transform=transform, stl_unit=stl_unit, reference_index=reference_index,
        contour_index=contour_index, iges_backend=iges_backend,
        union_overlapping_shells=union_overlapping_shells, tolerances=tolerances,
        ab_z_range_mm=ab_z_range_mm, measure_z_mm=measure_z_mm, connector=connector,
    )
    return generator.generate(
        output_dir, offset_mm=offset_mm, angle_deg=angle_deg, margin_mm=margin_mm,
        export_intermediate=export_intermediate, visualize=visualize, compute_assembly=compute_assembly,
    )
