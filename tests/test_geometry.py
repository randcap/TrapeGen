import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import trimesh
from manifold3d import Manifold

from trapegen import GeometryError, TrapezoidGenerator
from trapegen.mesh import from_solid


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.path = Path(self.workspace.name) / "source.stl"

    def generator(self, mesh, **kwargs):
        mesh.export(self.path)
        settings = {"yellow_reference_y": -7.5, "blue_y": 10}
        settings.update(kwargs)
        return TrapezoidGenerator(self.path, **settings)

    def test_box_analytic_and_parameter_endpoints(self):
        generator = self.generator(trimesh.creation.box([60, 50, 40]))
        for offset in (5, 7.5, 10):
            for angle in (52, 53, 55):
                with self.subTest(offset=offset, angle=angle):
                    result = generator.generate(offset_mm=offset, angle_deg=angle)
                    red = offset - 7.5
                    h = 10 - red
                    inset = h / math.tan(math.radians(angle))
                    np.testing.assert_allclose(result.trapezoid_vertices_2d, [
                        [-30, red], [30, red], [30 - inset, 10], [-30 + inset, 10],
                    ], atol=1e-9)
                    area = (60 - inset) * h
                    self.assertAlmostEqual(result.geometry_parameters.area_mm2, area)
                    self.assertAlmostEqual(result.assembly_region_mesh.volume, area * 40)
                    self.assertAlmostEqual(result.result_mesh.volume, (area + 60 * (25 + red)) * 40)
                    np.testing.assert_allclose(result.keep_mesh.bounds[:, 2], [-21, 21])
                    self.assertTrue(result.trapezoid_mesh.is_volume)
                    self.assertTrue(result.keep_mesh.is_volume)

    def test_section_cache_and_material_recovery(self):
        generator = self.generator(trimesh.creation.box([60, 50, 40]))
        baseline = generator.generate()
        angle_only = generator.generate(angle_deg=55)
        self.assertIs(baseline.section, angle_only.section)
        changed = generator.generate(offset_mm=5)
        self.assertIsNot(changed.section, baseline.section)
        restored = generator.generate()
        self.assertAlmostEqual(restored.result_mesh.volume, baseline.result_mesh.volume)

    def test_sphere_and_ellipsoid(self):
        for scale in ([1, 1, 1], [1.5, 0.8, 0.7]):
            with self.subTest(scale=scale):
                mesh = trimesh.creation.icosphere(subdivisions=4, radius=30)
                mesh.apply_scale(scale)
                result = self.generator(mesh).generate()
                self.assertAlmostEqual(result.geometry_parameters.lower_width_mm, 60 * scale[0], delta=0.15)
                self.assertLessEqual(result.result_mesh.bounds[1, 1], 10.000001)
                self.assertAlmostEqual(result.validation_report["result"]["lower_volume_difference_mm3"], 0, places=5)

    def test_asymmetric_protrusion_below_red_is_preserved(self):
        body = Manifold.cube((60, 50, 40), center=True)
        protrusion = Manifold.cube((12, 12, 15), center=True).translate((32, -10, 0))
        result = self.generator(from_solid(body + protrusion)).generate()
        self.assertAlmostEqual(result.result_mesh.bounds[1, 0], 38)
        self.assertAlmostEqual(result.validation_report["result"]["lower_volume_difference_mm3"], 0)
        self.assertAlmostEqual(result.geometry_parameters.A[0], -30)
        self.assertAlmostEqual(result.geometry_parameters.B[0], 30)

    def test_hole_remains_in_same_contour(self):
        shell = Manifold.cube((60, 50, 40), center=True)
        tunnel = Manifold.cube((8, 60, 8), center=True)
        result = self.generator(from_solid(shell - tunnel)).generate()
        self.assertEqual(result.section.contour_areas_mm2, (60 * 40 - 64,))
        self.assertTrue(result.result_mesh.is_volume)

    def test_multiple_sections_require_choice(self):
        outlier = trimesh.creation.box([10, 20, 10])
        outlier.apply_translation([75, 0, 0])
        mesh = trimesh.util.concatenate([trimesh.creation.box([60, 50, 40]), outlier])
        with self.assertRaisesRegex(GeometryError, "independent contours"):
            self.generator(mesh).generate()
        chosen = self.generator(mesh, contour_index=0).generate()
        self.assertEqual(chosen.section.contour_areas_mm2, (2400, 100))
        self.assertEqual(chosen.geometry_parameters.B[0], 30)
        self.assertEqual(chosen.result_mesh.bounds[1, 0], 80)

    def test_section_through_box_vertex_edges(self):
        box = trimesh.creation.box([60, 50, 40])
        vertices, faces = trimesh.remesh.subdivide(box.vertices, box.faces)
        divided = trimesh.Trimesh(vertices, faces)
        result = self.generator(divided).generate()
        self.assertAlmostEqual(result.geometry_parameters.lower_width_mm, 60)

    def test_empty_section_inside_bounds(self):
        lower = trimesh.creation.box([20, 10, 20])
        lower.apply_translation([0, -10, 0])
        upper = lower.copy()
        upper.apply_translation([0, 20, 0])
        with self.assertRaisesRegex(GeometryError, "No section"):
            self.generator(trimesh.util.concatenate((lower, upper))).generate()

    def test_invalid_parameters_or_geometry(self):
        generator = self.generator(trimesh.creation.box([60, 50, 40]))
        for settings in ({"offset_mm": 4.99}, {"offset_mm": 10.01}, {"angle_deg": 55.01}, {"angle_deg": 51.99}, {"margin_mm": 0}, {"offset_mm": math.nan}):
            with self.subTest(settings=settings), self.assertRaises(GeometryError):
                generator.generate(**settings)
        with self.assertRaisesRegex(GeometryError, "above"):
            self.generator(trimesh.creation.box([60, 50, 40]), blue_y=0).generate()
        with self.assertRaisesRegex(GeometryError, "above"):
            self.generator(trimesh.creation.box([60, 50, 40]), blue_y=-1).generate()
        with self.assertRaisesRegex(GeometryError, "upper base"):
            self.generator(trimesh.creation.box([4, 50, 40])).generate()
        with self.assertRaisesRegex(GeometryError, "outside"):
            self.generator(trimesh.creation.box([60, 50, 40]), yellow_reference_y=-50).generate()
        mesh = trimesh.creation.box()
        mesh.update_faces(np.arange(len(mesh.faces) - 1))
        with self.assertRaisesRegex(GeometryError, "invalid triangle mesh"):
            self.generator(mesh)

    def test_vertex_non_manifold_and_degenerate_input(self):
        box = trimesh.creation.box([10, 10, 10])
        right = box.copy()
        right.apply_translation([10, 10, 10])
        with self.assertRaisesRegex(GeometryError, "'non_manifold_vertices': 1"):
            self.generator(trimesh.util.concatenate((box, right)))
        degenerate = trimesh.Trimesh(box.vertices, [[0, 1, 1]], process=False)
        with self.assertRaisesRegex(GeometryError, "'degenerate_faces': 1"):
            self.generator(trimesh.util.concatenate((box, degenerate)))

    def test_shell_union_requires_explicit_option(self):
        left = trimesh.creation.box([60, 50, 40])
        right = left.copy()
        right.apply_translation([10, 0, 0])
        mesh = trimesh.util.concatenate((left, right))
        with self.assertRaisesRegex(GeometryError, "overlapping solid shells"):
            self.generator(mesh)
        result = self.generator(mesh, union_overlapping_shells=True).generate()
        self.assertAlmostEqual(result.geometry_parameters.lower_width_mm, 70)
        self.assertIsNotNone(result.validation_report["repair"])
