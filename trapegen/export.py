"""Write the verified STL and diagnostic artifacts."""

from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from .config import GeometryError
from .mesh import load_stl, require_mesh


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def export_result(generator, result, output_dir, *, export_intermediate):
    output = Path(output_dir)
    stls = {"result.stl": result.result_mesh}
    if export_intermediate:
        stls.update({"trapezoid_3d.stl": result.trapezoid_mesh, "keep_volume.stl": result.keep_mesh})
        if result.assembly_region_mesh is not None:
            stls["assembly_region.stl"] = result.assembly_region_mesh
    sources = {generator.stl_path.resolve()}
    if generator.igs_path is not None:
        sources.add(generator.igs_path.resolve())

    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".trapegen-", dir=output) as staging:
        stage = Path(staging)
        for name, mesh in stls.items():
            generator.frame.mesh_to_stl(mesh).export(stage / name, file_type="stl")
        result.validation_report["exported_stl"] = generator.validate_export(stage / "result.stl", result)

        if export_intermediate:
            from .visualization import save_profile

            for name in stls.keys() - {"result.stl"}:
                mesh = load_stl(stage / name)
                mesh.apply_transform(generator.frame.stl_to_local)
                require_mesh(mesh, generator.tolerances, name, exported=True)
            np.save(stage / "section_points.npy", result.section_points)
            _write_json(stage / "trapezoid_2d.json", {
                "coordinates": "local XY in mm",
                "ring_order": ["A", "B", "D", "C"],
                **asdict(result.geometry_parameters),
            })
            save_profile(generator, result, stage / "trapezoid_2d.png")
        _write_json(stage / "parameters.json", result.parameters)
        _write_json(stage / "validation_report.json", result.validation_report)

        if any((output / file.name).resolve() in sources for file in stage.iterdir()):
            raise GeometryError("An output path would overwrite an input file.")
        result.output_paths.clear()
        for file in sorted(stage.iterdir()):
            target = output / file.name
            file.replace(target)
            key = file.stem
            if key == "trapezoid_2d":
                key += "_" + file.suffix[1:]
            result.output_paths[key] = target
