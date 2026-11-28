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

源码位于 `src/trapegen/`。完成可编辑安装后，可在 Python 中使用 `import trapegen`，也可用 `trapegen`、`python -m trapegen` 或从项目根目录用 `python main.py` 调用命令行入口。

## 命令行

浏览器交互页面支持 STL 上传、旋转、平移、缩放、调参裁剪和下载，启动步骤见 [前端工作台](frontend/README.md)。

```bash
source .venv/bin/activate
trapegen --stl data/stl/part.stl --igs data/igs/blue.igs \
  --yellow-y 20 --unit mm --offset 7.5 --angle 53 --output output/part
```

- `--yellow-y` 是局部 Y 高度，始终以 mm 表示。蓝线只提供上底高度。可用 `--blue-y` 直接传入局部蓝线高度。
- `--unit` 声明 STL 长度单位，支持 `mm`、`cm`、`m`、`in`。IGES 单位由文件头独立确定。
- `--transform frame.json` 接受 4×4 右手刚体变换矩阵，将已换算成毫米的原始坐标变换至局部坐标，平移也以 mm 表示。局部 X 向右，Y 向上，Z 沿前后方向。未提供矩阵时使用单位变换。
- `--reference-index` 选择零起始的 IGES 边，`--contour-index` 选择有效截面外轮廓，按 XZ 面积降序排列，同面积按包围盒排序。出现多个候选时需显式指定。
- `--ab-z-range MIN MAX` 在选定的红线截面外轮廓上，将 A/B 取点限制在给定的局部 Z 范围内，单位为 mm。线段与条带边界的交点也参与取极值。默认使用整个选定轮廓。
- `--ab-x-offsets A B` 分别移动自动计算的底边端点，单位为局部毫米。负值向左，正值向右。例如 `--ab-x-offsets -5 0` 仅向左扩展 A 端。两端不能相交或重合，上底也须保持正宽度。红、蓝线高度和斜边角度按原参数计算。
- `--measure-z Z` 对导出后重新读取的 STL 进行 XY 截面验收，可重复指定多个局部 Z 位置，单位为 mm。位置须位于有效毛坯的 Z 包围盒内部。测量结果见 `validation_report.json` 中的 `exported_stl.section_measurements`。
- `--connector connector.json` 在真实上切面添加一个凸柱或盲孔。JSON 格式见下方装配特征接口。
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

可按以下命令使用窄条带选点，并回读三个前后位置的成品截面。

```bash
source .venv/bin/activate
trapegen --stl data/stl/xiong.stl --igs data/igs/xiong-blue-demo.igs \
  --unit cm --yellow-y 69 --union-overlapping-shells --ab-z-range -12 12 \
  --measure-z -20 --measure-z 0 --measure-z 20 --output output/xiong-sections
```

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

两个 Python 入口都可传入 `ab_z_range_mm=(-12, 12)` 和 `measure_z_mm=[-20, 0, 20]`。导出时自动回读指定位置，也可用 `generator.validate_export(path, result, measure_z_mm=[...])` 测量已有成品。A/B 在原三维截面上的实际取点坐标记录在 `geometry_parameters` 和 `parameters.json` 的 `a_section_xyz_mm`、`b_section_xyz_mm` 字段。

### HTTP 裁剪接口

`POST /api/clip` 的请求可选传入 `ab_z_range_mm`、`ab_x_offsets_mm`、`contour_index`、`measure_z_mm` 和 `transform`，成功时返回二进制 STL。使用相同请求体调用 `POST /api/measure-sections` 可获得 JSON，其中包含 A/B 三维坐标和回读截面尺寸，该入口要求至少一个测量位置。读取、裁剪或验收失败时返回 HTTP 422 和错误详情。

`ab_x_offsets_mm` 的格式为 `[A偏移, B偏移]`，缺省为 `[0, 0]`。Python API 也接受此参数。先完成自动截面取点和可选 Z 条带选点，再调整 A/B 的 X 坐标。`a_section_xyz_mm`、`b_section_xyz_mm` 记录自动取到的截面点，测量接口的 `a_xy_mm`、`b_xy_mm` 记录用于裁剪的实际底角。

`transform` 与 CLI 的 `--transform` 使用同一约定，传入按行排列的 4×4 右手刚体矩阵。原始 STL 坐标先按 `unit` 换算为毫米，再乘该矩阵转为加工坐标。矩阵末列前三项是毫米平移。省略该字段或传入 `null` 时使用单位矩阵。参考线高度、搜索条带和测量位置按加工坐标填写，成品 STL 会转回输入的坐标系及单位。

以下请求使用内置小熊。自定义模型可将 `model` 换成上传接口返回的标识。黄、蓝参考高度、偏移、条带和测量位置均使用局部毫米，角度单位为度。

```json
{
  "model": "xiong",
  "unit": "cm",
  "yellow": 69,
  "blue": 87,
  "offset": 7.5,
  "angle": 53,
  "union": true,
  "ab_z_range_mm": [-12, 12],
  "measure_z_mm": [-20, 0, 20]
}
```

### 装配特征接口

在 `POST /api/clip` 的现有请求中附加可选的 `connector` 对象。Python 可将同一个字典传给 `TrapezoidGenerator(..., connector=...)`、`generator.generate(connector=...)` 或 `generate_trapezoid_region(..., connector=...)`。CLI 的 `--connector` 文件仅包含该对象。省略对象时导出常规裁剪件。

```json
{
  "preset": "hexagonal_hole",
  "size_mm": 8,
  "depth_mm": 6,
  "angle_deg": 0,
  "offset_xz_mm": [0, 0]
}
```

| 形状 | 凸柱预设 | 盲孔预设 | `size_mm` 含义 |
| --- | --- | --- | --- |
| 圆形 | `circular_post` | `circular_hole` | 直径，圆周以 64 边离散 |
| 正三角形 | `triangular_post` | `triangular_hole` | 边长 |
| 正六边形 | `hexagonal_post` | `hexagonal_hole` | 边长 |
| 自定义 | `custom_post` | `custom_hole` | 旋转前轮廓包围盒的最大边长 |

- `depth_mm` 对凸柱表示向局部 +Y 的高度，对孔表示向 −Y 的盲孔深度。`angle_deg` 按局部 +Y 右手方向旋转，缺省为 0°。预设的首个顶点默认沿 +X。
- `offset_xz_mm` 以实际蓝切面最大连通材料区域的面积中心为基准，缺省为 `[0, 0]`。如果中心落在空洞中，可用偏移移到材料上。
- 自定义预设要求 `profile_xz`，内容是沿轮廓顺序排列的 3–128 个二维点，例如 `[[0,0],[2,0],[2,1],[1,2],[0,1]]`。轮廓自动闭合，允许凹多边形。源坐标是相对比例，后端先按面积中心居中、等比缩放，再应用旋转、偏移。
- `POST /api/connector-surface` 使用与裁剪相同的模型、姿态和梯形参数，返回 `blue_y_mm`、默认 `center_xz_mm` 及 `regions`。每个区域包含 `outline_xz_mm` 和 `holes_xz_mm`，环坐标省略重复的闭合点。这个接口计算实际基体切面，可供前端选择特征位置。
- `POST /api/measure-sections` 同样接受 `connector`，会按成品形状验证指定 Z 截面，其 `connector` 字段包含定位、轮廓、回读端面高度和增减体积。CLI 报告对应字段为 `exported_stl.connector`。
- 切面不存在、特征超出材料、盲孔钻穿外壳或贯通已有空腔时，后端返回 HTTP 422 与错误详情。实际配合间隙由两件各自的尺寸决定。

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
