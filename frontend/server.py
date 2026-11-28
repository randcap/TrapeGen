"""Local WebGL workspace and TrapeGen geometry API."""
import argparse
from collections import OrderedDict
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import perf_counter

from trapegen import TrapezoidGenerator
from trapegen.config import Frame, Tolerances
from trapegen.sections import normalize_ab_range

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data/stl/xiong.stl"


class Workspace:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.uploads = OrderedDict()
        self.lock = Lock()
        self.key = self.generator = None

    def upload(self, data):
        key = sha256(data).hexdigest()
        if key in self.uploads:
            self.uploads.move_to_end(key)
            return key
        path = self.directory / (key + ".stl")
        path.write_bytes(data)
        self.uploads[key] = path
        if len(self.uploads) > 8:
            _, old = self.uploads.popitem(last=False)
            old.unlink()
        return key

    def clip(self, params, *, measurements_only=False, surface_only=False):
        depths = params.get("measure_z_mm")
        if measurements_only and not depths:
            raise ValueError("measure_z_mm must contain at least one local Z position.")
        model = params["model"]
        path = SAMPLE if model == "xiong" else self.uploads.get(model)
        if path is None:
            raise ValueError("模型已过期，请重新上传")
        ab_range = normalize_ab_range(params.get("ab_z_range_mm"))
        contour_index = params.get("contour_index")
        if contour_index is not None and (type(contour_index) is not int or contour_index < 0):
            raise ValueError("contour_index must be a nonnegative integer.")
        unit = params["unit"]
        try:
            frame = Frame(unit, params.get("transform"), Tolerances())
        except OverflowError as exc:
            raise ValueError("Transform must be a finite 4×4 matrix.") from exc
        transform = tuple(tuple(row) for row in frame.world_mm_to_local.tolist())
        key = (model, unit, float(params["yellow"]), float(params["blue"]), bool(params["union"]),
               contour_index, ab_range, transform)
        if self.key != key:
            self.generator = TrapezoidGenerator(path, stl_unit=key[1], yellow_reference_y=key[2],
                                                blue_y=key[3], union_overlapping_shells=key[4],
                                                contour_index=contour_index, ab_z_range_mm=ab_range,
                                                transform=transform)
            self.key = key
        result = self.generator.generate(offset_mm=float(params["offset"]), angle_deg=float(params["angle"]),
                                         compute_assembly=False,
                                         ab_x_offsets_mm=params.get("ab_x_offsets_mm"),
                                         connector=None if surface_only else params.get("connector"))
        if surface_only:
            return self.generator.describe_connector_surface(result)
        path = self.directory / "clip.stl"
        self.generator.frame.mesh_to_stl(result.result_mesh).export(path)
        report = self.generator.validate_export(path, result, measure_z_mm=depths)
        if measurements_only:
            response = {
                "ab_z_range_mm": ab_range,
                "ab_x_offsets_mm": result.parameters["ab_x_offsets_mm"],
                "a_xy_mm": result.geometry_parameters.A,
                "b_xy_mm": result.geometry_parameters.B,
                "a_section_xyz_mm": result.geometry_parameters.a_section_xyz_mm,
                "b_section_xyz_mm": result.geometry_parameters.b_section_xyz_mm,
                "section_measurements": report["section_measurements"],
            }
            if result.connector is not None:
                response["connector"] = report["connector"]
            return response
        return path.read_bytes()


class Handler(SimpleHTTPRequestHandler):
    def reply(self, body, media, status=200, timing=None):
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        if timing is not None:
            self.send_header("Server-Timing", f"clip;dur={timing:.1f}")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/sample.stl":
            self.reply(SAMPLE.read_bytes(), "application/octet-stream")
        else:
            super().do_GET()

    def do_POST(self):
        try:
            if self.path not in ("/api/upload", "/api/clip", "/api/measure-sections", "/api/connector-surface"):
                return self.send_error(404)
            expected = "application/octet-stream" if self.path.endswith("upload") else "application/json"
            if self.headers.get_content_type() != expected:
                return self.send_error(415)
            size = int(self.headers.get("Content-Length", 0))
            limit = 128 * 1024**2 if self.path.endswith("upload") else 16384
            if not 0 < size <= limit:
                return self.send_error(413)
            body = self.rfile.read(size)
            timing = None
            with self.server.workspace.lock:
                if self.path.endswith("upload"):
                    body = json.dumps({"model": self.server.workspace.upload(body)}).encode()
                    media = "application/json"
                else:
                    started = perf_counter()
                    measurements_only = self.path == "/api/measure-sections"
                    surface_only = self.path == "/api/connector-surface"
                    result = self.server.workspace.clip(
                        json.loads(body), measurements_only=measurements_only, surface_only=surface_only
                    )
                    timing = (perf_counter() - started) * 1000
                    if measurements_only or surface_only:
                        body = json.dumps(result, allow_nan=False).encode()
                        media = "application/json"
                    else:
                        body = result
                        media = "application/octet-stream"
            self.reply(body, media, timing=timing)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            self.reply(str(exc).encode(), "text/plain; charset=utf-8", 422)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").exists():
        parser.error("请先在 frontend/ 执行 npm run build")
    with TemporaryDirectory() as temp, ThreadingHTTPServer(
        ("127.0.0.1", args.port), partial(Handler, directory=dist)
    ) as server:
        server.workspace = Workspace(temp)
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
