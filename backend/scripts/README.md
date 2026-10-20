# scripts —— 数据流水线脚本

> 目录已迁移到 `backend/scripts/`（原来是根目录的 `scripts/`）。
> 本文档是脚本层说明；算法内核见 `../app/`，整体入口见仓库根 `README.md`。

## 运行环境

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUNBUFFERED='1'
.\.venv\Scripts\python.exe -V        # Python 3.13.3
```

所有脚本都基于 `__file__` 解析路径（`_paths.py`），**可以在任意工作目录运行**。

## 现在的主流程

```powershell
# 1. 原始数据 → 冻结数据集 data/processed/v1/（会重写该目录）
.\.venv\Scripts\python.exe backend\scripts\prepare_dataset.py

# 2. 体检原始数据（可选）
.\.venv\Scripts\python.exe backend\scripts\data_audit.py

# 3. 回读校验冻结数据集
.\.venv\Scripts\python.exe backend\scripts\verify_dataset.py

# 4. 建多模式图并缓存
.\.venv\Scripts\python.exe backend\scripts\build_graph.py

# 5. 3 个试点 × 15/30/45 分钟
.\.venv\Scripts\python.exe backend\scripts\run_pilot_isochrones.py
```

## 历史脚本（已跑完，勿重复执行）

高德抓取会消耗每日配额，**已有缓存时不要重跑**：

| 脚本 | 作用 | 说明 |
|---|---|---|
| `fetch_amap_line_pilot.py` | 单条线路试点抓取 | `place/text` → `stopid` → `lineid` |
| `fetch_amap_all_lines.py` | 全量 694 条线路抓取 | 支持 `--problems` / `--only` / `--offset` 断点重跑 |
| `fetch_amap_metro.py` | 9 条地铁线抓取 | 用 `bus/linename`，一天 100 次上限 |
| `merge_amap_bus.py` | 公交合并：站点聚类为 `station_key`、生成边与吸附 | |
| `extract_amap_shapes.py` | 从 `raw_*.json` 的 `polyline` 提取线路几何 | |
| `snap_metro_stations.py` | 地铁站点吸附到 OSM 道路 | |
| `pilot_line.py` / `baidu_place.py` | 早期百度方案（已放弃） | 见 `docs/试点结果-百度站点定位与OSM叠合.md` |

配额现状：`place/text` 5000/日、`bus/stopid` 10000/日、`bus/lineid` 5000/日、
`bus/linename` 100/日。缓存目录 `data/cache/amap_pilot/`（68 MB）**不要删**。

## 密钥

脚本按以下顺序读取密钥：`.env` → `.env.txt` → `AK.txt`，只使用第一个存在的文件。
Key 不写进代码、截图或 Git。

## 输出位置

| 路径 | 内容 |
|---|---|
| `data/processed/v1/` | 冻结数据集（开发用） |
| `data/processed/graph/` | 图缓存（可重建） |
| `data/output/` | 图片、等时圈 GeoJSON、QA 报告 |
| `data/interim/` | 高德合并中间表 |
