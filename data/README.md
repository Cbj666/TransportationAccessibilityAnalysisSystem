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
走共享盘/网盘分发，目录结构保持一致即可。

推荐分发方式（任选其一）：

1. **网盘**：打包 `data/raw` + `data/cache` + `data/interim/amap_pilot` 一次发全；
2. **GitHub Release**：打成分卷压缩包（每个 < 2 GB），放在仓库的 Release 里；
3. **只给 v1**：如果组员只写前端/后端接口、不重建数据，只要 `data/processed/v1/` 就够，
   这个目录在仓库里。

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
