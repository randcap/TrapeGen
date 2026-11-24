"""STL topology, Manifold solids, and mesh verification."""

from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Error, Manifold, Mesh64, OpType

from .config import GeometryError, Tolerances


def load_stl(path) -> trimesh.Trimesh:
    """Load STL and weld exactly coincident vertices, preserving all triangles."""
    path = Path(path)
    try:
        mesh = trimesh.load_mesh(path, file_type="stl", process=False)
        if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
            raise GeometryError(f"STL has no triangles: {path}")
    except (OSError, ValueError) as exc:
        raise GeometryError(f"Cannot read STL {path}: {exc}") from exc
    if not np.isfinite(mesh.vertices).all():
        raise GeometryError(f"STL contains nonfinite coordinates: {path}")
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    return trimesh.Trimesh(vertices, inverse[mesh.faces], process=False)


def mesh_report(mesh, tol: Tolerances, *, exported=False) -> dict:
    counts = np.bincount(mesh.edges_unique_inverse)
    height = tol.export_degenerate_height_mm if exported else tol.degenerate_height_mm
    degenerate = np.count_nonzero(mesh.area_faces == 0)
    if height:
        degenerate = np.count_nonzero(~mesh.nondegenerate_faces(height=height))
    face_components = trimesh.graph.connected_component_labels(
        mesh.face_adjacency, node_count=len(mesh.faces)
    )
    # Connect corners at the same vertex across each shared edge.
    adjacent_faces = np.repeat(mesh.face_adjacency, 2, axis=0)
    edge_vertices = mesh.face_adjacency_edges.reshape(-1, 1, 1)
    corners = 3 * adjacent_faces + (mesh.faces[adjacent_faces] == edge_vertices).argmax(axis=2)
    corner_fans = trimesh.graph.connected_component_labels(
        corners, node_count=len(mesh.faces) * 3
    )
    vertex_fans = np.unique(np.column_stack((mesh.faces.ravel(), corner_fans)), axis=0)
    non_manifold_vertices = np.count_nonzero(np.bincount(vertex_fans[:, 0]) > 1)
    return {
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        "is_volume": bool(mesh.is_volume),
        "volume_mm3": float(mesh.volume),
        "face_count": len(mesh.faces),
        "connected_components": len(np.unique(face_components)),
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "non_manifold_edges": int(np.count_nonzero(counts > 2)),
        "non_manifold_vertices": int(non_manifold_vertices),
        "degenerate_faces": int(degenerate),
    }


def require_mesh(mesh, tol, label, *, exported=False):
    if not len(mesh.faces):
        raise GeometryError(f"{label}: empty solid.")
    report = mesh_report(mesh, tol, exported=exported)
    if not all(report[key] for key in ("is_watertight", "is_winding_consistent", "is_volume")) or any(
        report[key] for key in (
            "boundary_edges", "non_manifold_edges", "degenerate_faces",
            "non_manifold_vertices",
        )
    ):
        raise GeometryError(f"{label}: invalid triangle mesh: {report}")
    return report


def to_solid(mesh, label):
    solid = Manifold(Mesh64(
        np.require(mesh.vertices, dtype=np.float64, requirements=["C", "W"]),
        np.require(mesh.faces, dtype=np.uint64, requirements=["C", "W"]),
    ))
    return checked_solid(solid, label)


def checked_solid(solid, label, *, allow_empty=False):
    if solid.status() != Error.NoError or (solid.is_empty() and not allow_empty):
        raise GeometryError(f"{label}: Manifold returned {solid.status()} or an empty solid.")
    return solid


def from_solid(solid):
    data = solid.to_mesh64()
    return trimesh.Trimesh(data.vert_properties[:, :3], data.tri_verts, process=False)


def prepare_solid(mesh, tol, *, union_overlapping_shells):
    original_report = require_mesh(mesh, tol, "Input STL")
    solid = to_solid(mesh, "Input STL")
    shells = solid.decompose()
    report = {"input": original_report, "shell_overlap": "single shell", "repair": None}
    if len(shells) == 1:
        return mesh, solid, report

    volumes = [shell.volume() for shell in shells]
    if all(volume > 0 for volume in volumes):
        merged = checked_solid(Manifold.batch_boolean(shells, OpType.Add), "Shell union")
        overlap = sum(volumes) - merged.volume()
        report["shell_overlap_mm3"] = overlap
        if overlap > tol.volume_error(sum(volumes)):
            if not union_overlapping_shells:
                raise GeometryError(
                    f"Input has overlapping solid shells ({overlap:.6g} mm³ excess summed "
                    "volume). Supply an already unified mesh or explicitly enable shell union."
                )
            mesh, solid = from_solid(merged), merged
            report["repair"] = "union of overlapping positive-volume shells"
            report["effective_input"] = require_mesh(mesh, tol, "Unified input")
        report["shell_overlap"] = "positive-shell union volume comparison"
    else:
        if union_overlapping_shells:
            raise GeometryError("Shell union requires positive-volume shells. Input has cavity shells.")
        report["shell_overlap"] = "mixed orientation; independent overlap test unavailable"
    return mesh, solid, report


def intersect(solid, volume_mesh, label):
    volume_solid = to_solid(volume_mesh, f"{label} cutter")
    return checked_solid(solid ^ volume_solid, label)


def validate_result(original, final, mesh, geometry, tol, *, exported=False, coordinate_slack=0.0):
    report = require_mesh(mesh, tol, "Result STL", exported=exported)
    y_red, y_blue = geometry.A[1], geometry.C[1]
    x_left, x_right = geometry.A[0], geometry.B[0]
    slack = tol.coordinate_mm + coordinate_slack
    slope = geometry.inset_mm / geometry.height_mm

    x, y = mesh.vertices[:, :2].T
    # Intersect each result triangle with the upper half-space before checking
    # its convex XY constraints. Vertices in that piece include red-plane edges.
    segments, faces = trimesh.intersections.mesh_plane(
        mesh, [0, 1, 0], [0, y_red, 0], return_faces=True
    )
    selected = y > y_red + slack
    upper_x, upper_y = x[selected], y[selected]
    if len(segments):
        # Red-plane segments are only a side constraint where a face continues
        # above red. The lower shelf is allowed to extend beyond A and B.
        crossing = np.max(mesh.triangles[faces, :, 1], axis=1) > y_red + slack
        points = segments[crossing].reshape(-1, 3)
        upper_x = np.concatenate((upper_x, points[:, 0]))
        upper_y = np.concatenate((upper_y, points[:, 1]))
    low_violation = np.max(x_left + (upper_y - y_red) * slope - upper_x, initial=0)
    high_violation = np.max(upper_x - (x_right - (upper_y - y_red) * slope), initial=0)
    cap_violation = max(0.0, float(y.max() - y_blue))

    reference_lower = original.trim_by_plane((0, -1, 0), -y_red)
    actual_lower = final.trim_by_plane((0, -1, 0), -y_red)
    lower_volume = reference_lower.volume()
    lower_delta = abs(actual_lower.volume() - lower_volume)
    volume_limit = tol.volume_error(original.volume(), exported=exported)
    if cap_violation > slack or max(low_violation, high_violation) > slack:
        raise GeometryError("Result exceeds the blue height or crosses a trapezoid side.")
    if lower_delta > tol.volume_error(lower_volume, exported=exported):
        raise GeometryError(f"Lower material differs by {lower_delta:.6g} mm³.")
    if not 0 < report["volume_mm3"] <= original.volume() + volume_limit:
        raise GeometryError("Result volume is nonpositive or exceeds the input volume.")

    report.update(
        manifold_status=str(final.status()),
        max_blue_violation_mm=cap_violation,
        max_trapezoid_side_violation_mm=float(max(low_violation, high_violation)),
        input_volume_mm3=original.volume(),
        original_lower_volume_mm3=lower_volume,
        result_lower_volume_mm3=actual_lower.volume(),
        lower_volume_difference_mm3=lower_delta,
        coordinate_tolerance_mm=slack,
        volume_tolerance_mm3=volume_limit,
        lower_volume_tolerance_mm3=tol.volume_error(lower_volume, exported=exported),
        self_intersection={
            "status": "not independently tested",
            "evidence": "Manifold solid accepted; this is a topological check, not a triangle intersection audit",
        },
    )
    return report
