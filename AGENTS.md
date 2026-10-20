# AGENTS.md — AI 协作者上下文

给接手本仓库的 AI Agent（以及人）看的说明。**改代码前先读完这份**，
它比 README 更具体：哪里是入口、数据长什么样、哪些坑已经踩过。

最后更新：2026-10-20

---

## 1. 项目是什么

武汉单城的**个性化等时圈与区位评估**原型：给定一个起点坐标和时间预算
（15/30/45 分钟），算出步行 + 公交 + 地铁可达范围，统计范围里的 POI 和交通设施。

技术栈：Python 3.13 + pandas/geopandas/shapely/pyogrio + scipy 稀疏图；
前端计划 Vue 3 + 百度地图（未开始）。

**当前状态**：数据冻结 v1 → 多模式图 → 等时圈算法，三步已完成并验收。
后端 API 与前端尚未开始。

---

## 2. 环境与命令

```powershell
# 项目内虚拟环境（唯一支持的运行方式）
.\.venv\Scripts\python.exe -V     # Python 3.13.3
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUNBUFFERED='1'
```

所有脚本都可以**在任意工作目录**下运行（路径解析基于 `__file__`）：

```powershell
# 建图（首次约 6 秒；之后读缓存）
.\.venv\Scripts\python.exe backend\scripts\build_graph.py

# 3 个试点 × 15/30/45 分钟
.\.venv\Scripts\python.exe backend\scripts\run_pilot_isochrones.py

# 重建冻结数据集（会清空并重写 data/processed/v1）
.\.venv\Scripts\python.exe backend\scripts\prepare_dataset.py

# 回读校验
.\.venv\Scripts\python.exe backend\scripts\verify_dataset.py
.\.venv\Scripts\python.exe backend\scripts\data_audit.py
```

---

## 3. 仓库地图

| 路径 | 作用 | 入库 |
|---|---|---|
| `backend/app/config.py` | **全部建模参数**（步速、车速、候车、换乘） | ✅ |
| `backend/app/paths.py` | 全项目唯一的路径定义 | ✅ |
| `backend/app/graph.py` | 多模式图构建 + 缓存读写 + `Graph` 类 | ✅ |
| `backend/app/isochrone.py` | 最短路、时间面、等值面、POI 统计、路径分解 | ✅ |
| `backend/scripts/prepare_dataset.py` | 原始数据 → 冻结数据集 v1 | ✅ |
| `backend/scripts/build_graph.py` | 建图并缓存 | ✅ |
| `backend/scripts/run_pilot_isochrones.py` | 3 个试点出 GeoJSON + 三联图 | ✅ |
| `backend/scripts/_paths.py` | 脚本共享路径（`from _paths import ...`） | ✅ |
| `backend/scripts/fetch_*.py` | 高德抓取（**已缓存，勿重跑**） | ✅ |
| `backend/scripts/merge_*.py` / `snap_*.py` / `extract_*.py` | 合并、吸附、提取线路几何 | ✅ |
| `data/processed/v1/` | **冻结数据集，开发只读这里** | ✅ |
| `data/processed/graph/` | 图缓存（npz，35 MB，可重建） | ❌ |
| `data/raw/` | 原始下载（12 GB：OSM、CPTOND、1:25 万、公开公交数据） | ❌ |
| `data/cache/` | 高德 API 响应缓存（68 MB，删了要重新耗配额） | ❌ |
| `data/output/` | 图片、等时圈 GeoJSON、QA 报告 | ✅ |
| `docs/` | 说明书、数据报告、进展报告 | ✅ |
| `tools/` | 一次性历史脚本（路径已失效，别当主流程） | ✅ |
| `vendor/` | QGIS 安装包等第三方下载 | ❌ |

---

## 4. 数据契约（v1）

字段级说明见 `docs/数据字典-v1.md`，这里只列最容易搞错的：

| 事实 | 说明 |
|---|---|
| CRS | 全部 **EPSG:4326**；长度字段单位米（计算用 EPSG:32650） |
| 节点 ID | 公交 `B-<station_key>`，地铁 `M-<station_id>`，站台 `P-<bus\|metro>-<line_id>-<seq>` |
| `stops_bus.csv` | 7,823 行，主键 `node_id`；`station_id` **会重复**（1 个高德 ID 拆成多个空间站） |
| `edges_*.csv` | 有向边；`distance_m` 是**直线**距离，`dist_route_m` 才是沿线里程 |
| `dist_source` | `shape`（可信）/ `crowfly`（92 条公交边几何异常，用直线 × 1.2） |
| `metro_schedule.csv` | 发车间隔（秒），没有逐班次时刻表 |
| `osm_walk_roads.gpkg` | 层 `walk_roads`，91,203 段 / 47,051 km，`in_boundary` 标记城内/缓冲带 |
| `poi.gpkg` | 层 `poi_points`（全部转点，计数用它）、`poi_areas`（原始面，仅展示） |
| 站点坐标 | `lng/lat` 是 WGS84；`snap_lng/snap_lat` 是吸附到路网后的位置；`*_gcj02` 只用于回溯 |

**开发只读 `data/processed/v1/`。** `data/interim/` 是上游中间表，字段更乱，不要在新代码里引用。

---

## 5. 代码入口

```python
from app.graph import load_or_build, Graph, BUS_STOP, METRO_STOP, WALK
from app.isochrone import nearest_walk_node, travel_times, time_surface, \
                          surface_polygons, poi_stats, explain_path, reachable_stops

g = load_or_build(cache=True)              # 1,015,242 节点 / 2,174,254 边
node, snap_m = nearest_walk_node(g, 114.3546, 30.5342)
dist, pred = travel_times(g, node, predecessors=True)   # 秒，inf 表示不可达
X, Y, Z = time_surface(g, dist, bbox, res_m=100)        # 连续时间面
polys = surface_polygons(X, Y, Z, [900, 1800, 2700], boundary)  # 自动嵌套
stats = poi_stats(polys[900.0])                         # 范围内 POI 分类计数
legs = explain_path(g, node, target, pred)              # 逐段：步行/候车/乘车/换乘
```

图的结构（改算法前必须理解）：

```text
walk 顶点  <-> walk 顶点     length / 1.2 m/s
walk 顶点  <-> 站点          接驳距离 / 1.2 m/s
站点        -> 站台          候车时间（公交 480 s；地铁按线路 interval/2）
站台(a)     -> 站台(b)       乘车时间 = dist_route / 速度 + 停站
站台        -> 站点          0
```

**换乘成本就是这个结构自然产生的**：下车免费，再上车要再等一次车。
不要额外加"换乘惩罚"，否则会重复计算。

---

## 6. 建模参数

全部在 `backend/app/config.py` 的 `Params`（frozen dataclass），改默认值就改这里：

| 参数 | 默认 | 含义 |
|---|---:|---|
| `walk_speed_mps` | 1.2 | 步行 4.3 km/h |
| `bus_speed_mps` | 4.5 | 公交 16.2 km/h（含信号） |
| `bus_dwell_s` | 25 | 每站停靠 |
| `bus_wait_s` | 480 | 公交候车（无时刻表，全局近似） |
| `metro_speed_mps` | 9.5 | 地铁 34.2 km/h |
| `metro_dwell_s` | 35 | |
| `metro_wait_fallback_s` | 240 | 线路无 schedule 时的兜底 |
| `walk_access_max_m` | 800 | 站点离路网超过此值不接入 |

要支持"用户自选速度/换乘偏好"，构造 `Params(...)` 传给 `build()` 即可，
但**换参数后必须重建图**（权重在边上），缓存路径按参数区分是 TODO。

---

## 7. 常见任务

- **加一个试点 / 换起点**：改 `backend/scripts/run_pilot_isochrones.py` 里的 `TEST_POINTS`。
- **改等时圈形状**：调 `time_surface(res_m=)` 与 `surface_polygons(smooth_m=, min_component_m2=)`。
- **换城市**：`prepare_dataset.py` 的 `WALKABLE`/`CRS_METRIC`/边界路径要改，其余逻辑通用。
- **接后端 API**：直接 `from app...` 复用，图用 `load_or_build()` 常驻内存，单次请求 1–2 秒。

---

## 8. 已知坑 / 不要做的事

1. **不要重新抓高德数据**。`data/cache/` 和 `data/interim/amap_pilot/` 已有缓存，重跑会烧配额
   （`bus/linename` 只有 100 次/日）。
2. **不要硬编码路径**。新脚本必须 `from _paths import ...`（scripts）或
   `from .paths import ...`（app），否则换机器就崩。
3. **不要用 `distance_m` 算时间**，用 `dist_route_m`。
4. **不要把 `.env` 提交**（已在 .gitignore）。
5. **不要删除 `snap_quality=low` 的站点**，它们是远城区网络的一部分。
6. **不要把 591 条线路说成"武汉全部公交"**，缺 103 条。
7. **POI 只有 1.4 万个**，不要用它论证真实商业密度。
8. `tools/` 里的脚本是历史遗留，路径假设已变，**不要当参考实现**。
9. 中文文件名在 PowerShell 里容易乱码，读写文本请用 Python + `encoding="utf-8"`。

---

## 9. 改完怎么自检

```powershell
.\.venv\Scripts\python.exe backend\scripts\verify_dataset.py   # 数据仍自洽
.\.venv\Scripts\python.exe backend\scripts\run_pilot_isochrones.py
# 看三个点是否 nested 15<30<45 = True，面积量级是否合理（15 min ≈ 2–3 km²）
```

如果改了 `prepare_dataset.py`，跑完后 `git status` 应该只有
`data/processed/v1/*` 与 `manifest.json` 变化；**否则说明有隐藏的路径/随机性**。

---

## 10. 文档索引

| 文档 | 读它的场景 |
|---|---|
| `项目进度与交接说明.md` | 想知道全项目到哪一步了 |
| `docs/项目说明书-v3.0.md` | 答辩口径、功能边界 |
| `docs/数据冻结与开发就绪报告.md` | 数据怎么来的、校验结论 |
| `docs/开发进展-多模式图与等时圈试点.md` | 算法怎么实现的、参数、试点结果 |
| `docs/数据字典-v1.md` | 每个字段的含义 |
| `README.md` | 新成员第一次进门 |

**改结构时同步更新这份 AGENTS.md 与 `项目进度与交接说明.md` 的路径表。**
