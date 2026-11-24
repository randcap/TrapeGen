"""Generate a small IGES type-110 blue-reference fixture."""

import argparse
from pathlib import Path


def write_reference(path, lines, *, unit="mm"):
    unit_flag = {"mm": (2, "MM"), "cm": (10, "CM"), "in": (1, "IN")}
    flag, name = unit_flag[unit]

    def chunks(payload, size):
        return [payload[i:i + size] for i in range(0, len(payload), size)]

    def record(data, section, number):
        return f"{data:72}{section}{number:7}"

    global_data = (
        "1H,,1H;,8HTrapeGen,13Hreference.igs,8HTrapeGen,1H1,32,38,6,308,15,"
        f"8HTrapeGen,1.0,{flag},2H{name},1,0.0,15H20261124.000000,1.0E-7,10000.0,"
        "8HTrapeGen,8HTrapeGen,11,0,15H20261124.000000;"
    )
    start = [record("TrapeGen horizontal-reference fixture", "S", 1)]
    global_records = [record(data, "G", i) for i, data in enumerate(chunks(global_data, 72), 1)]
    directory, parameters = [], []
    for start_point, end_point in lines:
        pointer = len(directory) + 1
        payload = "110," + ",".join(f"{v:.12g}" for v in (*start_point, *end_point)) + ";"
        data_records = chunks(payload, 64)
        line1 = [110, len(parameters) + 1, 0, 0, 0, 0, 0, 0, "00000000"]
        line2 = [110, 0, 0, len(data_records), 0, "", "", "BLUE", pointer]
        directory.extend([
            record("".join(f"{value:>8}" for value in line1), "D", pointer),
            record("".join(f"{value:>8}" for value in line2), "D", pointer + 1),
        ])
        for data in data_records:
            parameters.append(record(f"{data:64}{pointer:8}", "P", len(parameters) + 1))
    end = record(f"S{len(start):7}G{len(global_records):7}D{len(directory):7}P{len(parameters):7}", "T", 1)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*start, *global_records, *directory, *parameters, end]) + "\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--y", type=float, default=87.0)
    parser.add_argument("--z", type=float, default=34.0)
    parser.add_argument("--half-width", type=float, default=35.0)
    parser.add_argument("--unit", choices=("mm", "cm", "in"), default="mm")
    args = parser.parse_args()
    write_reference(
        args.output, [((-args.half_width, args.y, args.z), (args.half_width, args.y, args.z))],
        unit=args.unit,
    )


if __name__ == "__main__":
    main()
