# data —— 数据目录

```text
data/
├── raw/                  原始下载，只读（不进库，~12 GB）
│   ├── hubei/            OSM 湖北提取：hubei.gpkg(225 MB)、hubei-261013.osm.pbf(53 MB)
│   ├── boundary/         武汉市_市.geojson（行政边界，EPSG:4490）
│   ├── h50/              1:25 万矢量地图（制图/校核用，不参与步行网络）
│   ├── public_transit/   公开公交/轨道线路站点数据（694 条线路的原始来源）
│   └── cptond/           中国交通数据网补充数据（~11 GB，暂未使用）
├── cache/                高德/百度 API 响应缓存（不进库，删了要重新花配额）
├── interim/              高德合并后的中间表（v1 的输入，部分入库）
│   └── amap_pilot/       591 条线路的逐线抓取结果（不进库，51 MB）
├── processed/
│   ├── v1/               ★ 冻结数据集，开发只读这里（入库，58 MB）
│   └── graph/            多模式图缓存（不进库，35 MB，可重建）
└── output/               图片、等时圈 GeoJSON、QA 报告（入库）
```

## v1 冻结数据集

详见 `processed/v1/DATA_DICTIONARY.md`。一句话：WGS84、ID 统一前缀、
边表带 `dist_route_m`（沿线）与 `dist_source`（可信度）。

## 不进库的东西怎么给组员

`data/raw/`（12 GB）和 `data/interim/amap_pilot/`、`data/cache/` 体积太大，
走共享盘/网盘/U 盘分发，**目录结构保持一致**即可。

按需要的程度分三档，别一股脑全发：

| 组员要做的事 | 需要拷什么 | 体积 |
|---|---|---:|
| 只写前端 / 只写接口 | 什么都不用拷，仓库里的 `processed/v1/` 够用 | 0 |
| 跑算法、改参数、复现等时圈 | 同上（v1 在仓库里，`build_graph.py` 6 秒重建图） | 0 |
| 重建 v1、改数据清洗逻辑 | `data/raw/` + `data/interim/amap_pilot/`（`interim/` 的合并表已在仓库） | ~12.1 GB |

### 拷完先校验

`data/raw-inputs.sha256` 已入库，覆盖重建 v1 必需的文件（19 个，0.43 GB）：

```bash
# 在 data/raw/ 目录下执行（Git Bash / WSL / macOS）
sha256sum -c ../raw-inputs.sha256
```

Windows PowerShell 逐个比对：

```powershell
Get-Content data\raw-inputs.sha256 | ForEach-Object {
  $hash, $size, $rel = $_ -split '  ', 3
  $f = Join-Path 'data\raw' $rel
  $ok = (Get-FileHash $f -Algorithm SHA256).Hash -eq $hash
  "{0}  {1}" -f $(if ($ok) { 'OK  ' } else { 'FAIL' }), $rel
}
```

校验不通过就是拷贝不完整或版本不一致，**不要开始重建**——否则
`prepare_dataset.py` 会安静地产出一份数据不对的 v1。

重新生成清单（raw 数据更新后）：

```powershell
.\.venv\Scripts\python.exe backend\scripts\make_raw_manifest.py
```

> 11 GB 的 `raw/cptond/`（中国交通数据网）不参与任何流程，清单里刻意跳过；
> 需要时再单独拷。

## 重建流程

```powershell
# 需要 data/raw/ 与 data/interim/（含 amap_pilot）就位
.\.venv\Scripts\python.exe backend\scripts\prepare_dataset.py   # → processed/v1
.\.venv\Scripts\python.exe backend\scripts\build_graph.py       # → processed/graph
```

`prepare_dataset.py` 会**清空并重写** `processed/v1`，别在里面手工改东西——
要改就改脚本，然后重跑。

## 注意

- `processed/v1/osm_walk_roads.gpkg` 是 34 MB，仓库里最大的文件；
  如果以后 GitHub 提示超限，把它挪到 Git LFS 或改由脚本按需重建。
- `cache/` 里的高德响应是**花钱抓来的**，删掉再抓会耗配额（`bus/linename` 100 次/日）。
- 所有数据坐标统一 **WGS84 (EPSG:4326)**；高德原始 GCJ-02 只保留在 `*_gcj02` 字段里。
