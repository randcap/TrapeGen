import json
from math import pi, sin, sqrt
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import trimesh
from manifold3d import Manifold

from trapegen import GeometryError, TrapezoidGenerator
from trapegen.cli import main
from trapegen.config import Frame, Tolerances
from trapegen.mesh import from_solid, load_stl


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "stock.stl"
        self.stock = trimesh.creation.box([60, 50, 40])
        self.stock.export(self.source)

    def generator(self, **kwargs):
        return TrapezoidGenerator(
            self.source, **({"yellow_reference_y": -7.5, "blue_y": 10} | kwargs)
        )

    def test_presets_and_custom_round_trip(self):
        profiles = {
            "circular": ({}, 64 * 4**2 * sin(2 * pi / 64) / 2),
            "triangular": ({}, 8**2 * sqrt(3) / 4),
            "hexagonal": ({}, 6 * 8**2 * sqrt(3) / 4),
            "custom": ({"profile_xz": [[0, 0], [2, 0], [2, 2], [1, 1], [0, 2]]}, 48),
        }
        generator = self.generator(measure_z_mm=[-12, 0, 2])
        base = generator.generate(compute_assembly=False)
        surface = generator.describe_connector_surface(base)
        self.assertEqual(surface["blue_y_mm"], 10)
        np.testing.assert_allclose(surface["center_xz_mm"], [0, 0], atol=1e-9)
        for shape, (custom, area) in profiles.items():
            for kind, sign in (("post", 1), ("hole", -1)):
                preset = f"{shape}_{kind}"
                with self.subTest(preset=preset):
                    result = generator.generate(
                        self.root / preset,
                        connector={"preset": preset, "size_mm": 8, "depth_mm": 6, "angle_deg": 17, **custom},
                        export_intermediate=False,
                    )
                    final = result.validation_report["exported_stl"]
                    report = final["connector"]
                    self.assertTrue(final["is_volume"])
                    self.assertEqual(final["connected_components"], 1)
                    self.assertAlmostEqual(report["area_mm2"], area, delta=1e-6)
                    self.assertAlmostEqual(report["actual_volume_change_mm3"], sign * area * 6, delta=0.002)
                    self.assertEqual(report["start_y_mm"], 10)
                    np.testing.assert_allclose(report["measured_end_y_range_mm"], [10 + sign * 6] * 2, atol=1e-6)
                    self.assertEqual(len(final["section_measurements"]), 3)
                    self.assertEqual(result.validation_report["base_result"]["max_blue_violation_mm"], 0)
        restored = generator.generate(compute_assembly=False)
        self.assertIsNone(restored.connector)
        self.assertAlmostEqual(restored.result_mesh.volume, base.result_mesh.volume)

    def test_input_and_breakthrough_errors(self):
        generator = self.generator()
        spec = {"preset": "circular_hole", "size_mm": 8, "depth_mm": 6}
        cases = [
            ({**spec, "offset_xz_mm": [29, 0]}, "fit inside"),
            ({**spec, "size_mm": 100}, "cut surface"),
            ({**spec, "depth_mm": 50}, "break through"),
            ({**spec, "size_mm": float("inf")}, "finite"),
            ({**spec, "preset": []}, "preset"),
            ({**spec, "angle_deg": "bad"}, "finite"),
            ({**spec, "depth_mm": 0}, "positive"),
            ({**spec, "preset": "custom_hole", "profile_xz": [[0, 0], [1, 1], [0, 1], [1, 0]]},
             "simple polygon"),
        ]
        for settings, error in cases:
            with self.subTest(settings=settings), self.assertRaisesRegex(GeometryError, error):
                generator.generate(connector=settings)

        with self.assertRaisesRegex(GeometryError, "No horizontal cut surface"):
            self.generator(blue_y=28).generate(connector=spec)

        stock = Manifold.cube((60, 50, 40), center=True)
        pocket = Manifold.cube((12, 4, 12), center=True).translate((0, 0, 0))
        from_solid(stock - pocket).export(self.source)
        cavity = self.generator()
        with self.assertRaisesRegex(GeometryError, "break through"):
            cavity.generate(connector={**spec, "depth_mm": 15})

    def test_surface_has_void_and_accepts_an_offset_center(self):
        stock = Manifold.cube((60, 50, 40), center=True)
        tunnel = Manifold.cube((8, 70, 8), center=True)
        from_solid(stock - tunnel).export(self.source)
        generator = self.generator()
        result = generator.generate()
        surface = generator.describe_connector_surface(result)
        self.assertEqual(len(surface["regions"][0]["holes_xz_mm"]), 1)
        spec = {"preset": "circular_post", "size_mm": 6, "depth_mm": 5}
        with self.assertRaisesRegex(GeometryError, "fit inside"):
            generator.generate(connector=spec)
        result = generator.generate(connector={**spec, "offset_xz_mm": [11, 0]})
        np.testing.assert_allclose(result.connector.center_xz_mm, [11, 0], atol=1e-9)

    def test_connector_cli_retains_input_pose_and_units(self):
        frame = Frame("cm", [[0, -1, 0, 10], [1, 0, 0, 2], [0, 0, 1, -5], [0, 0, 0, 1]], Tolerances())
        frame.mesh_to_stl(self.stock).export(self.source)
        frame_path = self.root / "frame.json"
        frame_path.write_text(json.dumps(frame.world_mm_to_local.tolist()))
        settings = self.root / "connector.json"
        settings.write_text(json.dumps({"preset": "triangular_post", "size_mm": 8, "depth_mm": 6}))
        output = self.root / "out"
        status = main([
            "--stl", str(self.source), "--unit", "cm", "--transform", str(frame_path),
            "--yellow-y=-7.5", "--blue-y", "10", "--connector", str(settings),
            "--no-intermediate", "--output", str(output),
        ])
        self.assertEqual(status, 0)
        mesh = load_stl(output / "result.stl")
        # The new local Y=16 cap maps back to raw X=(16-2)/10 cm.
        self.assertAlmostEqual(mesh.bounds[1, 0], 1.4, places=6)
        mesh.apply_transform(frame.stl_to_local)
        self.assertAlmostEqual(mesh.bounds[1, 1], 16, places=5)
