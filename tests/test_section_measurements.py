from io import BytesIO
import json
from math import radians, tan
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np
import trimesh
from manifold3d import Manifold
from shapely import Polygon

from frontend.server import Handler, Workspace
from trapegen import GeometryError, TrapezoidGenerator, generate_trapezoid_region
from trapegen.cli import main
from trapegen.config import Frame, Tolerances
from trapegen.mesh import from_solid


def post(workspace, route, data, media="application/json"):
    class Connection:
        def __init__(self, request):
            self.request = BytesIO(request)
            self.response = BytesIO()

        def makefile(self, *_args):
            return self.request

        def sendall(self, data):
            self.response.write(data)

    class QuietHandler(Handler):
        def log_message(self, *_args):
            pass

    body = json.dumps(data).encode() if media == "application/json" else data
    headers = (f"POST {route} HTTP/1.0\r\nContent-Type: {media}\r\n"
               f"Content-Length: {len(body)}\r\n\r\n").encode()
    connection = Connection(headers + body)
    QuietHandler(connection, ("127.0.0.1", 0), SimpleNamespace(workspace=workspace))
    head, response = connection.response.getvalue().split(b"\r\n\r\n", 1)
    return int(head.split()[1]), head, response


class SectionMeasurementTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "stock.stl"

    def generator(self, **kwargs):
        settings = {"yellow_reference_y": -7.5, "blue_y": 10}
        return TrapezoidGenerator(self.source, **(settings | kwargs))

    def test_bottom_endpoints_adjust_independently_to_keep_protrusions(self):
        body = Manifold.cube((60, 50, 40), center=True)
        left_ear = Manifold.cube((12, 4, 10), center=True).translate((-32, 6, 0))
        right_ear = Manifold.cube((12, 4, 10), center=True).translate((32, 6, 0))
        from_solid(body + left_ear + right_ear).export(self.source)
        generator = self.generator(measure_z_mm=(0,))
        baseline = generator.generate(compute_assembly=False)
        left = generator.generate(
            self.root / "left", ab_x_offsets_mm=(-15, 0), export_intermediate=False, compute_assembly=False,
        )
        right = generator.generate(ab_x_offsets_mm=(0, 15), compute_assembly=False)
        self.assertIs(baseline.section, left.section)
        self.assertIs(baseline.section, right.section)
        self.assertEqual(left.geometry_parameters.A, (-45, 0))
        self.assertEqual(left.geometry_parameters.B, baseline.geometry_parameters.B)
        self.assertEqual(left.geometry_parameters.a_section_xyz_mm, baseline.geometry_parameters.a_section_xyz_mm)
        self.assertEqual(right.geometry_parameters.A, baseline.geometry_parameters.A)
        self.assertEqual(right.geometry_parameters.B, (45, 0))
        self.assertAlmostEqual(left.geometry_parameters.C[0], baseline.geometry_parameters.C[0] - 15)
        self.assertAlmostEqual(right.geometry_parameters.D[0], baseline.geometry_parameters.D[0] + 15)
        np.testing.assert_allclose(baseline.result_mesh.bounds[:, 0], [-30, 30])
        np.testing.assert_allclose(left.result_mesh.bounds[:, 0], [-38, 30])
        np.testing.assert_allclose(right.result_mesh.bounds[:, 0], [-30, 38])
        self.assertAlmostEqual(left.validation_report["result"]["lower_volume_difference_mm3"], 0)
        self.assertTrue(left.validation_report["exported_stl"]["section_measurements"])
        self.assertEqual(generator.generate(ab_x_offsets_mm=(0, 0)).geometry_parameters, baseline.geometry_parameters)
        with self.assertRaisesRegex(GeometryError, "must stay to the left"):
            generator.generate(ab_x_offsets_mm=(60, 0))
        with self.assertRaisesRegex(GeometryError, "upper base"):
            generator.generate(ab_x_offsets_mm=(50, 0))
        with self.assertRaisesRegex(GeometryError, "offsets"):
            generator.generate(ab_x_offsets_mm=(float("nan"), 0))

    def test_ab_band_interpolates_true_contour_edges_and_preserves_lower_material(self):
        outline = Polygon([(-30, -20), (30, -20), (30, 0), (50, 20), (-30, 20)])
        mesh = trimesh.creation.extrude_polygon(outline, 50, engine="earcut")
        mesh.apply_transform([[1, 0, 0, 0], [0, 0, -1, 25], [0, 1, 0, 0], [0, 0, 0, 1]])
        mesh.export(self.source)
        complete = self.generator().generate()
        limited = self.generator(ab_z_range_mm=(6, 11)).generate()
        self.assertEqual(complete.geometry_parameters.B[0], 50)
        self.assertEqual(limited.geometry_parameters.B, (41, 0))
        self.assertEqual(limited.geometry_parameters.b_section_xyz_mm, (41, 0, 11))
        self.assertEqual(limited.geometry_parameters.A[0], -30)
        self.assertEqual(limited.section_points[:, 0].max(), 50)
        self.assertEqual(limited.result_mesh.bounds[1, 0], 50)
        self.assertAlmostEqual(limited.validation_report["result"]["lower_volume_difference_mm3"], 0)
        np.testing.assert_allclose(limited.keep_mesh.bounds[:, 2], [-21, 21])

        with self.assertRaisesRegex(GeometryError, "no contour segments"):
            self.generator(ab_z_range_mm=(21, 25)).generate()
        for bounds in ((11, 6), (6, 6), (6, float("nan")), (6,), "61"):
            with self.subTest(bounds=bounds), self.assertRaises(GeometryError):
                self.generator(ab_z_range_mm=bounds)

    def test_strip_respects_explicit_contour_selection(self):
        first = trimesh.creation.box([60, 50, 40])
        second = trimesh.creation.box([20, 50, 10])
        second.apply_translation([0, 0, 30])
        trimesh.util.concatenate((first, second)).export(self.source)
        with self.assertRaisesRegex(GeometryError, "independent contours"):
            self.generator(ab_z_range_mm=(-10, 10)).generate()
        chosen = self.generator(contour_index=1, ab_z_range_mm=(26, 34)).generate(compute_assembly=False)
        self.assertEqual(chosen.geometry_parameters.lower_width_mm, 20)
        self.assertEqual(chosen.geometry_parameters.a_section_xyz_mm[1], 0)
        self.assertGreaterEqual(chosen.geometry_parameters.a_section_xyz_mm[2], 26)

    def test_readback_of_nonflat_stock_compares_sections_at_multiple_depths(self):
        mesh = trimesh.creation.box([60, 50, 40])
        top = mesh.vertices[:, 1] > 0
        mesh.vertices[top, 1] = 15 + 0.5 * mesh.vertices[top, 2]
        mesh.export(self.source)
        output = self.root / "result"
        result = generate_trapezoid_region(
            self.source, yellow_reference_y=-7.5, blue_y=10, output_dir=output,
            measure_z_mm=(-15, 12, 12), export_intermediate=False,
        )
        measurements = result.validation_report["exported_stl"]["section_measurements"]
        self.assertEqual([item["z_mm"] for item in measurements], [-15, 12])
        slope = 1 / tan(radians(53))
        for item, top in zip(measurements, (7.5, 10)):
            actual, expected = item["actual"], item["expected"]
            self.assertAlmostEqual(actual["area_mm2"], 1500 + 60 * top - slope * top**2, delta=0.001)
            self.assertAlmostEqual(actual["height_mm"], 25 + top, places=5)
            self.assertAlmostEqual(actual["width_mm"], 60, places=5)
            self.assertEqual(actual["regions"], 1)
            self.assertLess(item["missing_area_mm2"] + item["excess_area_mm2"], 0.001)
            self.assertAlmostEqual(actual["area_mm2"], expected["area_mm2"], delta=0.001)
        self.assertEqual(measurements[0]["actual"]["blue_band_x_coverage_mm"], 0)
        self.assertAlmostEqual(
            measurements[1]["actual"]["blue_band_x_coverage_mm"], 60 - 20 * slope, delta=0.001
        )
        serialized = json.loads((output / "validation_report.json").read_text())
        self.assertEqual(serialized["exported_stl"]["section_measurements"], measurements)

    def test_measurement_rejects_upper_overcut_that_passes_legacy_checks(self):
        trimesh.creation.box([60, 50, 40]).export(self.source)
        generator = self.generator()
        expected = generator.generate(compute_assembly=False)
        overcut = self.generator(blue_y=7).generate(
            self.root / "overcut", export_intermediate=False, compute_assembly=False,
        )
        path = overcut.output_paths["result"]
        self.assertNotIn("section_measurements", generator.validate_export(path, expected))
        with self.assertRaisesRegex(GeometryError, r"section Z=0.*missing area"):
            generator.validate_export(path, expected, measure_z_mm=[0])

    def test_measurement_handles_holes_and_a_rotated_centimeter_stl(self):
        stock = Manifold.cube((60, 50, 40), center=True)
        tunnel = Manifold.cube((8, 6, 60), center=True).translate((0, -10, 0))
        frame = Frame("cm", [[0, -1, 0, 10], [1, 0, 0, 2], [0, 0, 1, -5], [0, 0, 0, 1]], Tolerances())
        frame.mesh_to_stl(from_solid(stock - tunnel)).export(self.source)
        result = self.generator(
            stl_unit="cm", transform=frame.world_mm_to_local, measure_z_mm=[3],
        ).generate(self.root / "hole", export_intermediate=False)
        measured = result.validation_report["exported_stl"]["section_measurements"][0]
        self.assertEqual(measured["actual"]["holes"], 1)
        self.assertEqual(measured["expected"]["holes"], 1)
        area = 2100 - 100 / tan(radians(53)) - 48
        self.assertAlmostEqual(measured["actual"]["area_mm2"], area, delta=0.001)
        for depths in ([20], [float("inf")], ["bad"], 5):
            with self.subTest(depths=depths), self.assertRaises(GeometryError):
                self.generator(stl_unit="cm", transform=frame.world_mm_to_local, measure_z_mm=depths)

    def test_empty_depth_inside_input_bounds(self):
        first = trimesh.creation.box([60, 50, 10])
        first.apply_translation([0, 0, -10])
        second = first.copy()
        second.apply_translation([0, 0, 20])
        trimesh.util.concatenate((first, second)).export(self.source)
        result = self.generator(contour_index=0, measure_z_mm=[0]).generate(
            self.root / "result", export_intermediate=False,
        )
        measured = result.validation_report["exported_stl"]["section_measurements"][0]
        self.assertEqual(measured["actual"], measured["expected"])
        self.assertEqual(measured["actual"]["regions"], 0)

    def test_cli_and_http_backend_expose_options(self):
        trimesh.creation.box([60, 50, 40]).export(self.source)
        output = self.root / "cli"
        self.assertEqual(main([
            "--stl", str(self.source), "--yellow-y=-7.5", "--blue-y", "10",
            "--ab-z-range", "-5", "5", "--measure-z", "-8", "--measure-z", "8",
            "--output", str(output), "--no-intermediate",
        ]), 0)
        params = json.loads((output / "parameters.json").read_text())
        self.assertEqual(params["ab_z_range_mm"], [-5, 5])
        self.assertEqual(params["measure_z_mm"], [-8, 8])

        workspace = Workspace(self.root)
        status, _, response = post(workspace, "/api/upload", self.source.read_bytes(), "application/octet-stream")
        self.assertEqual(status, 200)
        command = {
            **json.loads(response),
            "unit": "mm", "yellow": -7.5, "blue": 10, "union": False, "offset": 7.5, "angle": 53,
        }
        status, headers, baseline = post(workspace, "/api/clip", command)
        self.assertEqual(status, 200)
        self.assertIn(b"Content-Type: application/octet-stream", headers)
        settings = {**command, "ab_z_range_mm": [-5, 5], "measure_z_mm": [-8, 8]}
        status, headers, response = post(workspace, "/api/measure-sections", settings)
        self.assertEqual(status, 200)
        self.assertIn(b"Content-Type: application/json", headers)
        report = json.loads(response)
        self.assertEqual([item["z_mm"] for item in report["section_measurements"]], [-8, 8])
        self.assertGreaterEqual(report["a_section_xyz_mm"][2], -5)
        self.assertLessEqual(report["a_section_xyz_mm"][2], 5)
        status, _, response = post(workspace, "/api/clip", settings)
        self.assertEqual(status, 200)
        self.assertEqual(response, baseline)
        self.assertEqual(response, (output / "result.stl").read_bytes())
        status, _, response = post(workspace, "/api/measure-sections", command)
        self.assertEqual(status, 422)
        self.assertIn(b"measure_z_mm", response)

    def test_http_transform_changes_cut_and_preserves_input_coordinates(self):
        workspace = Workspace(self.root)
        source = trimesh.creation.box([6, 5, 4]).export(file_type="stl")
        status, _, response = post(workspace, "/api/upload", source, "application/octet-stream")
        self.assertEqual(status, 200)
        command = {
            **json.loads(response),
            "unit": "cm", "yellow": -7.5, "blue": 10, "union": False, "offset": 7.5, "angle": 53,
        }
        status, _, initial_stl = post(workspace, "/api/clip", command)
        self.assertEqual(status, 200)
        initial = workspace.generator
        status, _, identity_stl = post(workspace, "/api/clip", {
            **command, "transform": np.eye(4).tolist(),
        })
        self.assertEqual(status, 200)
        self.assertEqual(identity_stl, initial_stl)
        self.assertIs(workspace.generator, initial)

        transform = [[0, -1, 0, 0], [1, 0, 0, 3], [0, 0, 1, -5], [0, 0, 0, 1]]
        rotated = {**command, "transform": transform}
        status, _, rotated_stl = post(workspace, "/api/clip", rotated)
        self.assertEqual(status, 200)
        rotated_generator = workspace.generator
        self.assertIsNot(rotated_generator, initial)
        mesh = trimesh.load_mesh(BytesIO(rotated_stl), file_type="stl")
        # Local Y = 10 * original X + 3, so the cap at Y = 10 is cut at
        # original X = 0.7 cm. Original Y and Z retain their centimetre extents.
        np.testing.assert_allclose(mesh.bounds, [[-3, -2.5, -2], [0.7, 2.5, 2]], atol=1e-6)

        status, _, measurements = post(workspace, "/api/measure-sections", {**rotated, "measure_z_mm": [-23]})
        self.assertEqual(status, 200)
        self.assertIs(workspace.generator, rotated_generator)
        report = json.loads(measurements)
        self.assertEqual(report["a_section_xyz_mm"][0], -25)
        self.assertEqual(report["section_measurements"][0]["z_mm"], -23)
        self.assertAlmostEqual(report["section_measurements"][0]["actual"]["bounds_xy_mm"][1][1], 10, places=5)

        invalid_matrices = (
            [[1, 0], [0, 1]],
            np.diag([-1, 1, 1, 1]).tolist(),
            np.diag([2, 1, 1, 1]).tolist(),
            [[1, 1, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            [[1, 0, 0, float("nan")], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            [[1, 0, 0, 10**400], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        )
        for matrix in invalid_matrices:
            with self.subTest(matrix=matrix):
                status, _, response = post(workspace, "/api/clip", {**command, "transform": matrix})
                self.assertEqual(status, 422)
                self.assertIn(b"Transform", response)
                self.assertIs(workspace.generator, rotated_generator)
        status, _, reset_stl = post(workspace, "/api/clip", {**command, "transform": None})
        self.assertEqual(status, 200)
        self.assertEqual(reset_stl, initial_stl)
        self.assertIsNot(workspace.generator, rotated_generator)

    def test_http_connector_surface_export_and_measurement(self):
        workspace = Workspace(self.root)
        source = trimesh.creation.box([60, 50, 40]).export(file_type="stl")
        status, _, response = post(workspace, "/api/upload", source, "application/octet-stream")
        self.assertEqual(status, 200)
        request = {
            **json.loads(response), "unit": "mm", "yellow": -7.5, "blue": 10, "union": False,
            "offset": 7.5, "angle": 53,
        }
        status, headers, response = post(workspace, "/api/connector-surface", request)
        self.assertEqual(status, 200)
        self.assertIn(b"Content-Type: application/json", headers)
        surface = json.loads(response)
        self.assertEqual(surface["blue_y_mm"], 10)
        np.testing.assert_allclose(surface["center_xz_mm"], [0, 0], atol=1e-9)
        self.assertEqual(len(surface["regions"]), 1)

        connector = {
            "preset": "custom_post", "size_mm": 8, "depth_mm": 6, "angle_deg": 23,
            "profile_xz": [[0, 0], [2, 0], [2, 1], [1, 2], [0, 1]],
        }
        status, headers, response = post(workspace, "/api/clip", {**request, "connector": connector})
        self.assertEqual(status, 200)
        self.assertIn(b"Content-Type: application/octet-stream", headers)
        mesh = trimesh.load_mesh(BytesIO(response), file_type="stl")
        self.assertAlmostEqual(mesh.bounds[1, 1], 16)
        status, _, response = post(workspace, "/api/measure-sections", {
            **request, "connector": connector, "measure_z_mm": [0],
        })
        self.assertEqual(status, 200)
        summary = json.loads(response)
        self.assertEqual(summary["connector"]["preset"], "custom_post")
        self.assertEqual(summary["connector"]["measured_end_y_range_mm"], [16, 16])
        self.assertEqual(summary["section_measurements"][0]["expected"]["bounds_xy_mm"][1][1], 16)
        status, _, response = post(workspace, "/api/clip", {
            **request, "connector": {**connector, "offset_xz_mm": [30, 0]},
        })
        self.assertEqual(status, 422)
        self.assertIn(b"Connector must fit inside", response)

    def test_http_bottom_offsets_match_surface_and_export(self):
        workspace = Workspace(self.root)
        source = trimesh.creation.box([60, 50, 40]).export(file_type="stl")
        status, _, response = post(workspace, "/api/upload", source, "application/octet-stream")
        self.assertEqual(status, 200)
        request = {
            **json.loads(response), "unit": "mm", "yellow": -7.5, "blue": 10, "union": False,
            "offset": 7.5, "angle": 53, "ab_x_offsets_mm": [-4, 0],
        }
        status, _, response = post(workspace, "/api/connector-surface", request)
        self.assertEqual(status, 200)
        surface = json.loads(response)
        x = [point[0] for point in surface["regions"][0]["outline_xz_mm"]]
        status, _, response = post(workspace, "/api/measure-sections", {**request, "measure_z_mm": [0]})
        self.assertEqual(status, 200)
        measured = json.loads(response)
        self.assertEqual(measured["a_xy_mm"], [-34, 0])
        self.assertEqual(measured["b_xy_mm"], [30, 0])
        self.assertEqual(measured["a_section_xyz_mm"][0], -30)
        status, _, response = post(workspace, "/api/clip", request)
        self.assertEqual(status, 200)
        mesh = trimesh.load_mesh(BytesIO(response), file_type="stl")
        top = mesh.vertices[mesh.vertices[:, 1] == 10, 0]
        np.testing.assert_allclose([top.min(), top.max()], [min(x), max(x)], atol=1e-6)
        status, _, response = post(workspace, "/api/clip", {**request, "ab_x_offsets_mm": [65, 0]})
        self.assertEqual(status, 422)
        self.assertIn(b"must stay to the left", response)
