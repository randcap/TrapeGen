"""Blue reference import and validation in the common millimeter frame."""

from dataclasses import dataclass
from pathlib import Path
import re
from threading import Lock

import numpy as np

from .config import GeometryError


@dataclass(frozen=True)
class BlueReference:
    y_mm: float
    points: np.ndarray | None
    source: str
    index: int | None
    iges_unit_flag: int | None = None


_IGES_LOCK = Lock()
_IGES_UNITS_MM = {
    1: 25.4, 2: 1.0, 4: 304.8, 5: 1609344.0, 6: 1000.0, 7: 1e6,
    8: 0.0254, 9: 0.001, 10: 10.0, 11: 0.0000254,
}


def _choose(count, index):
    if not count:
        raise GeometryError("IGES contains no usable curve edges.")
    if index is None and count != 1:
        raise GeometryError(f"IGES contains {count} candidate edges. Supply reference_index (zero-based).")
    index = 0 if index is None else index
    if not 0 <= index < count:
        raise GeometryError(f"IGES reference index must be in [0, {count - 1}].")
    return index


def _occt_edge(path, frame, reference_index):
    try:
        from OCP.Bnd import Bnd_Box
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.IGESControl import IGESControl_Reader
        from OCP.Interface import Interface_Static
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape
        from OCP.TopoDS import TopoDS
    except ImportError as exc:
        raise GeometryError(
            "Open CASCADE is unavailable. Install the project's cadquery-ocp-novtk dependency."
        ) from exc

    # OCCT uses a process-wide transfer unit. Select mm while transferring;
    # the reader itself converts the IGES header units into that unit.
    with _IGES_LOCK:
        reader = IGESControl_Reader()
        previous = Interface_Static.CVal_s("xstep.cascade.unit")
        try:
            if not Interface_Static.SetCVal_s("xstep.cascade.unit", "MM"):
                raise GeometryError("Open CASCADE could not set the transfer unit to mm.")
            if reader.ReadFile(str(path)) != IFSelect_RetDone:
                raise GeometryError(f"Open CASCADE could not read IGES {path}.")
            unit_flag = reader.IGESModel().GlobalSection().UnitFlag()
            if unit_flag not in _IGES_UNITS_MM:
                raise GeometryError(f"IGES {path} has an unsupported or unspecified length unit ({unit_flag}).")
            if not reader.TransferRoots():
                raise GeometryError(f"Open CASCADE could not transfer IGES geometry from {path}.")
            shape = reader.OneShape()
        finally:
            if previous:
                Interface_Static.SetCVal_s("xstep.cascade.unit", previous)

    edges = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edges)
    index = _choose(edges.Extent(), reference_index)
    edge = TopoDS.Edge_s(edges.FindKey(index + 1))
    transform = gp_Trsf()
    transform.SetValues(*frame.world_mm_to_local[:3].ravel().tolist())
    edge = TopoDS.Edge_s(BRepBuilderAPI_Transform(edge, transform, True).Shape())
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(edge, box, False, False)
    xmin, ymin, _, xmax, ymax, _ = box.Get()
    curve = BRepAdaptor_Curve(edge)
    parameters = np.linspace(curve.FirstParameter(), curve.LastParameter(), 65)
    points = np.array([curve.Value(float(p)).Coord() for p in parameters])
    return index, points, (xmin, ymin, xmax, ymax), unit_flag


def _globals(text):
    """Read standard-delimiter IGES global tokens, honoring Hollerith strings."""
    tokens = []
    while text.strip():
        text = text.lstrip()
        match = re.match(r"(\d+)[hH]", text)
        if match:
            end = match.end() + int(match[1])
            tokens.append(text[match.end():end])
            text = text[end:].lstrip()
            if not text or text[0] not in ",;":
                raise ValueError("Invalid Hollerith field")
        else:
            match = re.match(r"[^,;]*", text)
            tokens.append(match[0].strip())
            text = text[match.end():]
        if not text or text[0] == ";":
            return tokens
        text = text[1:]
    raise ValueError("Missing IGES global terminator")


def _line_edge(path, frame, reference_index):
    """Restricted offline reader for plain type-110 line fixtures."""
    try:
        rows = path.read_text(encoding="ascii").splitlines()
        if not rows or any(len(row) != 80 for row in rows) or rows[-1][72] != "T":
            raise ValueError("Expected fixed 80-character IGES records")
        fields = _globals("".join(row[:72] for row in rows if row[72] == "G"))
        if fields[:2] not in ([",", ";"], ["", ""]) or float(fields[12]) != 1:
            raise ValueError("Only standard separators and unit model scale are supported")
        unit_flag = int(fields[13])
        unit_mm = _IGES_UNITS_MM[unit_flag]
        directory = [row for row in rows if row[72] == "D"]
        if len(directory) % 2:
            raise ValueError("Incomplete IGES directory entry")
        pointers = []
        for first, second in zip(directory[::2], directory[1::2]):
            if int(first[:8]) != 110 or int(second[:8]) != 110 or int(first[48:56].strip() or 0):
                raise ValueError("Expected only untransformed type-110 lines")
            pointers.append(int(first[73:]))
        index = _choose(len(pointers), reference_index)
        params = "".join(
            row[:64] for row in rows if row[72] == "P" and int(row[64:72]) == pointers[index]
        ).strip()
        if not params.endswith(";"):
            raise ValueError("Missing IGES line parameters")
        kind, *values = params[:-1].split(",")
        if int(kind) != 110 or len(values) != 6:
            raise ValueError("Expected six coordinates for the type-110 line")
        world = np.array([float(v.upper().replace("D", "E")) for v in values]).reshape(2, 3)
    except GeometryError:
        raise
    except (OSError, ValueError, KeyError, IndexError) as exc:
        raise GeometryError(f"Cannot read restricted IGES line {path}: {exc}") from exc
    points = frame.points_to_local(world * unit_mm)
    return index, points, (*points[:, :2].min(axis=0), *points[:, :2].max(axis=0)), unit_flag


def load_igs_reference(path, frame, tol, reference_index=None, *, backend="occt"):
    path = Path(path)
    if not path.is_file():
        raise GeometryError(f"IGES file does not exist: {path}")
    readers = {"occt": _occt_edge, "line": _line_edge}
    if backend not in readers:
        raise GeometryError("IGES backend must be 'occt' or 'line'.")
    try:
        index, points, (xmin, ymin, xmax, ymax), unit_flag = readers[backend](path, frame, reference_index)
    except GeometryError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise GeometryError(f"Could not extract IGES edge from {path}: {exc}") from exc
    if not np.isfinite(points).all() or not np.isfinite([xmin, ymin, xmax, ymax]).all():
        raise GeometryError(f"IGES edge {index} is not finite.")
    if ymax - ymin > tol.horizontal_mm or xmax - xmin <= tol.coordinate_mm:
        raise GeometryError(
            f"IGES edge {index} must have constant local Y and nonzero X span "
            f"(Y span {ymax - ymin:g} mm, X span {xmax - xmin:g} mm)."
        )
    return BlueReference(float(points[0, 1]), points, backend, index, unit_flag)
