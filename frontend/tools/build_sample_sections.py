"""Build the exact sampled sections of the prepared xiong.stl demo."""
from hashlib import sha256
import json
from pathlib import Path

from trapegen import TrapezoidGenerator
from trapegen.config import GeometryError
from trapegen.profile import slice_mesh

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "data/stl/xiong.stl"
generator = TrapezoidGenerator(
    source, stl_unit="cm", yellow_reference_y=69, blue_y=87, union_overlapping_shells=True
)
samples = []
for step in range(740, 791):
    try:
        section = slice_mesh(generator.effective_mesh, step / 10, None, generator.tolerances)
    except GeometryError as error:
        samples.append({"message": str(error)})
    else:
        samples.append([float(section.points[:, 0].min()), float(section.points[:, 0].max())])

target = ROOT / "frontend/src/sample-sections.json"
target.write_text(json.dumps({
    "sha256": sha256(source.read_bytes()).hexdigest(),
    "unit": "cm",
    "firstTenth": 740,
    "sections": samples,
}, separators=(",", ":")) + "\n")
print(f"{target.name}: {sum(isinstance(s, list) for s in samples)} / {len(samples)} sections")
