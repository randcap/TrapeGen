import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import trimesh
from matplotlib.backend_bases import MouseButton, MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from examples.make_reference import write_reference
from trapegen import GeometryError, TrapezoidGenerator, generate_trapezoid_region
from trapegen.cli import main
from trapegen.config import Frame, Tolerances
from trapegen.mesh import load_stl
from trapegen.reference import load_igs_reference
from trapegen.visualization import build_debug_figure


class PipelineTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.directory = Path(workspace.name)
        self.stl = self.directory / "source.stl"
        self.igs = self.directory / "blue.igs"
        self.box = trimesh.creation.box([60, 50, 40])
        self.box.export(self.stl)

    def test_iges_selection_and_errors(self):
        frame, tolerance = Frame("mm", None, Tolerances()), Tolerances()
        lines = [((-20, 9, 10), (20, 11, 10)), ((-20, 10, 11), (20, 10, 11))]
        write_reference(self.igs, lines)
        with self.assertRaisesRegex(GeometryError, "2 candidate edges"):
            load_igs_reference(self.igs, frame, tolerance, backend="line")
        with self.assertRaisesRegex(GeometryError, "constant local Y"):
            load_igs_reference(self.igs, frame, tolerance, 0, backend="line")
        self.assertEqual(load_igs_reference(self.igs, frame, tolerance, 1, backend="line").y_mm, 10)
        with self.assertRaisesRegex(GeometryError, "reference index"):
            load_igs_reference(self.igs, frame, tolerance, 2, backend="line")
        self.igs.write_text("broken input")
        with self.assertRaisesRegex(GeometryError, "Cannot read"):
            load_igs_reference(self.igs, frame, tolerance, backend="line")
        with self.assertRaisesRegex(GeometryError, "does not exist"):
            load_igs_reference(self.directory / "missing.igs", frame, tolerance, backend="line")

    def test_rotated_scaled_iges_and_stl_round_trip(self):
        frame = Frame("cm", [[0, -1, 0, 10], [1, 0, 0, 2], [0, 0, 1, -5], [0, 0, 0, 1]], Tolerances())
        frame.mesh_to_stl(self.box).export(self.stl)
        line_local = np.array([[-25, 10, 15], [25, 10, 15]])
        world_in = trimesh.transform_points(line_local, np.linalg.inv(frame.world_mm_to_local)) / 25.4
        write_reference(self.igs, [world_in], unit="in")
        output = self.directory / "out"
        result = generate_trapezoid_region(
            self.stl, self.igs, -7.5, output, transform=frame.world_mm_to_local,
            stl_unit="cm", iges_backend="line",
        )
        self.assertAlmostEqual(result.geometry_parameters.height_mm, 10, places=6)
        self.assertEqual(set(result.output_paths), {
            "result", "assembly_region", "trapezoid_3d", "keep_volume", "parameters",
            "validation_report", "section_points", "trapezoid_2d_json", "trapezoid_2d_png",
        })
        self.assertTrue((output / "trapezoid_2d.png").read_bytes().startswith(b"\x89PNG"))
        self.assertEqual(np.load(output / "section_points.npy").shape[1], 3)
        exported = load_stl(output / "result.stl")
        self.assertTrue(exported.is_volume)
        self.assertAlmostEqual(exported.volume * 1000, result.result_mesh.volume, delta=0.05)
        decoded = json.loads((output / "parameters.json").read_text())
        self.assertEqual(decoded["stl_unit"], "cm")
        self.assertEqual(decoded["iges_length_unit_flag"], 1)
        self.assertAlmostEqual(decoded["blue_y_mm"], 10)
        self.assertTrue(result.validation_report["exported_stl"]["is_volume"])

    def test_bad_transform_and_reference_in_wrong_axes(self):
        with self.assertRaisesRegex(GeometryError, "proper rigid"):
            TrapezoidGenerator(self.stl, yellow_reference_y=0, blue_y=20, transform=np.diag([2, 1, 1, 1]))
        write_reference(self.igs, [((-25, 10, 15), (25, 10, 15))])
        rotated = [[0, -1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        with self.assertRaisesRegex(GeometryError, "constant local Y"):
            TrapezoidGenerator(self.stl, self.igs, yellow_reference_y=0, transform=rotated, iges_backend="line")

    @unittest.skipUnless(importlib.util.find_spec("OCP") is not None, "Open CASCADE dependency unavailable")
    def test_open_cascade_transfer_non_mm_and_edge_selection(self):
        write_reference(self.igs, [((-1, 1, 0), (1, 1, 0)), ((-1, 1.2, 0), (1, 1.2, 0))], unit="in")
        frame, tolerance = Frame("cm", None, Tolerances()), Tolerances()
        with self.assertRaisesRegex(GeometryError, "2 candidate edges"):
            load_igs_reference(self.igs, frame, tolerance)
        first = load_igs_reference(self.igs, frame, tolerance, 0)
        second = load_igs_reference(self.igs, frame, tolerance, 1)
        np.testing.assert_allclose(sorted([first.y_mm, second.y_mm]), [25.4, 30.48], atol=1e-6)

    def test_cli_minimal_export_and_3d_preview(self):
        output = self.directory / "minimal"
        returned = main([
            "--stl", str(self.stl), "--blue-y", "10", "--yellow-y", "-7.5", "--output",
            str(output), "--no-intermediate", "--no-assembly", "--preview-3d",
        ])
        self.assertEqual(returned, 0)
        self.assertEqual({path.name for path in output.iterdir()}, {
            "result.stl", "parameters.json", "validation_report.json", "preview_3d.png",
        })
        self.assertTrue((output / "preview_3d.png").read_bytes().startswith(b"\x89PNG"))

    def test_viewer_slider_apply_in_agg(self):
        generator = TrapezoidGenerator(self.stl, yellow_reference_y=-7.5, blue_y=10)
        result = generator.generate()
        fig = Figure(figsize=(14, 6.5))
        canvas = FigureCanvasAgg(fig)
        offset, angle, apply, front, side = build_debug_figure(fig, generator, result)
        offset.set_val(8.5)
        angle.set_val(55)
        self.assertEqual(generator._section.y_mm, 0)
        x, y = apply.ax.transAxes.transform((0.5, 0.5))
        for name in ("button_press_event", "button_release_event"):
            canvas.callbacks.process(name, MouseEvent(name, canvas, x, y, button=MouseButton.LEFT))
        self.assertEqual(generator._section.y_mm, 1)
        self.assertTrue(any(text.get_text() == "Updated" for text in fig.texts))
