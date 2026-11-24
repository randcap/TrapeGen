# TrapeGen

依据蓝色 IGES 参考线和给定黄线，在闭合 STL 上生成梯形装配区。最终结果来自原始实体与完整保留实体的布尔交集，保留红线以下的全部材料。

## 安装与测试

在项目根目录执行以下命令。示例使用 Python 3.10，依赖统一配置在 `setup.py`。CAD 读取使用 Open CASCADE 的 `cadquery-ocp-novtk` Python 绑定。

```bash
uv venv --python 3.10   # 已有 .venv 时跳过
source .venv/bin/activate
uv pip install -e .
python -m unittest discover -s tests -v
```

需要与平台和 Python 版本匹配的 OCP wheel。可离线取得核心几何依赖的环境也能使用手动蓝线和受限直线读取器。

## 命令行

```bash
source .venv/bin/activate
trapegen --stl data/stl/part.stl --igs data/igs/blue.igs \
  --yellow-y 20 --unit mm --offset 7.5 --angle 53 --output output/part
```

- `--yellow-y` 是局部 Y 高度，始终以 mm 表示。蓝线只提供上底高度。可用 `--blue-y` 直接传入局部蓝线高度。
- `--unit` 声明 STL 长度单位，支持 `mm`、`cm`、`m`、`in`。IGES 单位由文件头独立确定。
- `--transform frame.json` 接受 4×4 右手刚体变换矩阵，将已换算成毫米的原始坐标变换至局部坐标，平移也以 mm 表示。局部 X 向右，Y 向上，Z 沿前后方向。未提供矩阵时使用单位变换。
- `--reference-index` 选择零起始的 IGES 边，`--contour-index` 选择有效截面外轮廓，按 XZ 面积降序排列，同面积按包围盒排序。出现多个候选时需显式指定。
- `--preview-3d` 生成静态三维预览。使用 `--visualize` 时需要可用的 Matplotlib 交互后端和桌面显示。窗口支持鼠标旋转、正视和侧视按钮，以及 `Offset`、`Angle` 滑块。点击 `Apply` 重算并写入指定输出目录。
- `--no-intermediate` 只写最终 STL 和参数、验收 JSON。添加 `--no-assembly` 可省去独立装配区域的布尔交集。
- `--iges-backend line` 读取测试用的 ASCII IGES Type 110 直线，要求标准分隔符、单位模型比例且边无 IGES 实体变换。正式 IGES 默认使用 Open CASCADE。
- `--union-overlapping-shells` 允许先合并相交的正体积外壳，具体操作记录到验收报告。默认遇到此类输入会报错。

### 小熊样件

```bash
source .venv/bin/activate
python examples/make_reference.py data/igs/xiong-blue-demo.igs
trapegen --stl data/stl/xiong.stl --igs data/igs/xiong-blue-demo.igs \
  --iges-backend line --unit cm --yellow-y 69 --union-overlapping-shells \
  --preview-3d --output output/xiong
```

样件演示按厘米解释原始 STL 坐标。黄线取两眼中心附近的 Y = 69 mm，红线位于 Y = 76.5 mm，临时蓝线位于 Y = 87 mm。该 STL 有 19 个相互重叠的外壳，演示显式执行外壳并集。原始输入文件保留。

## Python API

```python
from trapegen import TrapezoidGenerator, generate_trapezoid_region

result = generate_trapezoid_region(
    "data/stl/part.stl",
    "data/igs/blue.igs",
    yellow_reference_y=20.0,
    output_dir="output/part",
)
print(result.geometry_parameters.A, result.output_paths["result"])

generator = TrapezoidGenerator(
    "data/stl/part.stl", "data/igs/blue.igs", yellow_reference_y=20.0,
)
first = generator.generate(offset_mm=7.5, angle_deg=53)
second = generator.generate(offset_mm=7.5, angle_deg=55)
assert first.section is second.section
```

生成器缓存原始网格、IGES 参考线、变换、包围盒和最近的截面。调角度时复用截面，调偏移时重切截面。每次布尔交集都使用同一个经过输入验证的实体。通过 `Tolerances` 可覆盖集中定义的数值阈值。

## 输出文件

| 文件 | 内容 |
| --- | --- |
| `result.stl` | 最终部件，原始 STL 坐标系和单位 |
| `trapezoid_3d.stl` | 贯穿梯形实体，原始 STL 坐标系和单位 |
| `assembly_region.stl` | 贯穿梯形和原部件的实体交集，原始 STL 坐标系和单位 |
| `keep_volume.stl` | 下方保留区域与梯形构成的裁剪实体，原始 STL 坐标系和单位 |
| `section_points.npy` | 所选外轮廓的截面点，局部 XYZ 毫米 |
| `trapezoid_2d.json`、`trapezoid_2d.png` | 局部 XY 顶点、尺寸、投影及单独展示的真实 XZ 截面 |
| `parameters.json`、`validation_report.json` | 输入参数、坐标和单位、体积、网格检查结果及判定阈值 |
| `preview_3d.png` | 裁剪几何和最终部件的正视、侧视预览 |

内存中的所有结果网格使用局部毫米。导出 STL 默认转换到原始坐标系和单位，并在写出后重新加载最终 STL 做验收。仅可视化使用轻量网格绘制三维视图。

[算法说明](docs/algorithm.md) · [Mermaid 流程图](docs/flowchart.md) · [验收报告](docs/validation.md)
