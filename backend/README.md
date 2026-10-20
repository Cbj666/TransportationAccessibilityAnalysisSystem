# backend —— 分析内核与数据流水线

```text
app/                     Python 包，可被未来 API 直接 import
  config.py              Params：全部建模参数（唯一的"魔法数字"来源）
  paths.py               全项目路径定义（不要在别处硬编码路径）
  graph.py               多模式图：路网 + 公交 + 地铁 → scipy CSR
  isochrone.py           最短路 / 时间面 / 等值面 / POI 统计 / 路径分解
scripts/                 命令行脚本（可在任意工作目录运行）
  _paths.py              脚本共享路径 + 自动把 backend/ 加进 sys.path
  prepare_dataset.py     原始数据 → data/processed/v1（冻结数据集）
  data_audit.py          原始数据体检 → data/output/data_audit.json
  verify_dataset.py      回读冻结数据集逐项校验
  plot_dataset_overview.py  路网 + 站点 + POI 总览图
  build_graph.py         建图并缓存到 data/processed/graph/v1/
  run_pilot_isochrones.py   3 个试点 × 15/30/45 分钟 → GeoJSON + 三联图
  fetch_*.py             高德抓取（已缓存，勿重跑）
  merge_amap_bus.py      公交合并、站点聚类、边上表
  extract_amap_shapes.py 从原始 JSON 提取线路几何
  snap_metro_stations.py 地铁站点吸附
  geo_utils.py           GCJ-02 → WGS84、haversine
requirements.txt
```

## 常用命令

```powershell
$env:PYTHONIOENCODING='utf-8'

.\.venv\Scripts\python.exe backend\scripts\build_graph.py
.\.venv\Scripts\python.exe backend\scripts\run_pilot_isochrones.py
.\.venv\Scripts\python.exe backend\scripts\verify_dataset.py
```

## 图的结构

```text
walk 顶点  <-> walk 顶点     长度 / 1.2 m/s
walk 顶点  <-> 站点           接驳距离 / 1.2 m/s
站点        -> 站台           候车（公交 480 s，地铁按线路 interval/2）
站台(a)     -> 站台(b)        乘车（沿线里程 / 速度 + 停站）
站台        -> 站点           0
```

站点与站台分离后，**换乘时间 = 下车（0）+ 再等一次车**，不需要额外惩罚项。

## 规模与性能

- 节点 1,015,242 / 有向边 2,174,254；
- 建图 ~6 s（读 47,051 km 步行路网 + 27,837 个站台）；
- 单次单源最短路 ~1 s；一次等时圈（3 档 + 时间面 + 出图）~2 s；
- 图缓存 35 MB，加载 ~1 s。

## 改参数

`app/config.py` 的 `Params` 是 frozen dataclass：

```python
from app.config import Params
from app.graph import build
g = build(Params(walk_speed_mps=1.35, bus_wait_s=300))
```

**改参数必须重建图**（权重写在边上），当前缓存不区分参数，重建后请覆盖缓存。
