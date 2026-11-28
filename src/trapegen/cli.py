"""Command-line interface for the parametric cutting pipeline."""

import argparse
import json
from pathlib import Path

from .config import DEFAULT_ANGLE, DEFAULT_OFFSET, UNIT_TO_MM, GeometryError
from .pipeline import TrapezoidGenerator


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stl", required=True, type=Path)
    reference = parser.add_mutually_exclusive_group(required=True)
    reference.add_argument("--igs", type=Path)
    reference.add_argument("--blue-y", type=float, help="Manual blue reference Y in local mm.")
    parser.add_argument("--yellow-y", required=True, type=float, help="Yellow reference Y in local mm.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--offset", type=float, default=DEFAULT_OFFSET)
    parser.add_argument("--angle", type=float, default=DEFAULT_ANGLE)
    parser.add_argument("--margin", type=float, default=1.0)
    parser.add_argument("--unit", choices=UNIT_TO_MM, default="mm")
    parser.add_argument("--transform", type=Path, help="JSON 4x4 world-mm to local-mm rigid transform.")
    parser.add_argument("--connector", type=Path, help="JSON definition of one connector on the blue cut surface.")
    parser.add_argument("--reference-index", type=int, help="Zero-based IGES edge index.")
    parser.add_argument("--contour-index", type=int, help="Zero-based section contour, largest first.")
    parser.add_argument("--ab-z-range", type=float, nargs=2, metavar=("MIN", "MAX"),
                        help="Restrict A/B search on the selected contour to this local Z band (mm).")
    parser.add_argument("--measure-z", type=float, action="append", metavar="Z",
                        help="Validate and report an XY section of the exported STL at local Z (mm). Repeatable.")
    parser.add_argument("--iges-backend", choices=("occt", "line"), default="occt")
    parser.add_argument("--union-overlapping-shells", action="store_true",
                        help="Explicitly union overlapping positive-volume shells before processing.")
    parser.add_argument("--no-intermediate", action="store_true")
    parser.add_argument("--no-assembly", action="store_true")
    parser.add_argument("--visualize", action="store_true", help="Open the interactive parameter viewer.")
    parser.add_argument("--preview-3d", action="store_true", help="Write a headless 3D preview PNG.")
    args = parser.parse_args(argv)

    try:
        transform = json.loads(args.transform.read_text()) if args.transform else None
        connector = json.loads(args.connector.read_text()) if args.connector else None
        generator = TrapezoidGenerator(
            args.stl, args.igs, yellow_reference_y=args.yellow_y, blue_y=args.blue_y,
            transform=transform, stl_unit=args.unit, reference_index=args.reference_index,
            contour_index=args.contour_index, iges_backend=args.iges_backend,
            union_overlapping_shells=args.union_overlapping_shells,
            ab_z_range_mm=args.ab_z_range, measure_z_mm=args.measure_z, connector=connector,
        )
        result = generator.generate(
            args.output, offset_mm=args.offset, angle_deg=args.angle, margin_mm=args.margin,
            export_intermediate=not args.no_intermediate,
            compute_assembly=not args.no_assembly,
        )
        if args.preview_3d or args.visualize:
            from .visualization import save_3d_preview, show_debug

            if args.preview_3d:
                save_3d_preview(generator, result, args.output / "preview_3d.png")
    except (GeometryError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"trapegen: {exc}\n")

    report = result.validation_report["exported_stl"]
    print(f"{result.output_paths['result']} · {report['face_count']} triangles · {report['volume_mm3']:.6g} mm³")
    if args.visualize:
        try:
            show_debug(
                generator, result, output_dir=args.output,
                export_intermediate=not args.no_intermediate,
                preview_path=args.output / "preview_3d.png" if args.preview_3d else None,
            )
        except GeometryError as exc:
            parser.exit(2, f"trapegen: {exc}\n")
    return 0
