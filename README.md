# 武汉个性化等时圈与区位评估平台

基于 OSM 路网 + 高德公交/地铁数据，计算武汉任意起点在 **15/30/45 分钟**内
步行 + 公交 + 地铁可达的范围，统计范围内 POI 与交通设施，并支持候选地点对比。

> 课程项目 / 首版原型。不是商业级选址工具，结论以"相对比较"为主。

## 现状

| 模块 | 状态 |
|---|---|
| 数据（591 条公交、9 条地铁、47,051 km 步行路网、1.4 万 POI） | 已冻结为 v1 |
| 多模式图（102 万节点 / 217 万边） | 完成 |
| 等时圈算法（3 个试点 × 15/30/45 分钟） | 完成，已验收 |
| 后端 API（FastAPI） | 未开始 |
| 前端（Vue 3 + 百度地图） | 未开始 |
| 答辩 PPT | 未开始 |

## 目录结构

```text
.
├── backend/                 # Python 分析内核与数据流水线
│   ├── app/                 #   可被 API 复用的算法包
│   │   ├── config.py        #   全部建模参数（步速/车速/候车/换乘）
│   │   ├── paths.py         #   全项目唯一的路径定义
│   │   ├── graph.py         #   多模式图构建（scipy CSR）
│   │   └── isochrone.py     #   最短路、时间面、等值面、路径分解
│   ├── scripts/             #   数据抓取 / 清洗 / 建图 / 试点脚本
│   └── requirements.txt
├── frontend/                # Vue 3 + 百度地图（待建）
├── data/
│   ├── raw/                 # 原始下载（不入库，见 data/README.md）
│   ├── interim/             # 高德合并表
│   ├── processed/v1/        # 冻结数据集（开发只读这里）
│   ├── processed/graph/     # 图缓存（不入库，可重建）
│   └── output/              # 图片、等时圈 GeoJSON、QA 报告
├── docs/                    # 项目文档（说明书、数据报告、进展报告）
├── tools/                   # 一次性的历史脚本（不参与主流程）
├── vendor/                  # 第三方下载（QGIS 安装包等，不入库）
├── 项目进度与交接说明.md      # 交接主文档
└── AGENTS.md                # 给 AI 协作者的上下文说明
```

## 快速开始

```powershell
# 1. 环境（Windows PowerShell）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. 数据：把 data/raw/ 与 data/interim/amap_pilot/ 从共享盘拷回（见 data/README.md）
#    然后重建冻结数据集与图缓存
.\.venv\Scripts\python.exe backend\scripts\prepare_dataset.py
.\.venv\Scripts\python.exe backend\scripts\build_graph.py

# 3. 跑 3 个测试点的等时圈
.\.venv\Scripts\python.exe backend\scripts\run_pilot_isochrones.py
```

产物：

- 等时圈：`data/output/isochrones/v1/pilot_isochrones.geojson`
- 三联图：`data/output/isochrones/v1/pilot_map.png`
- 图缓存：`data/processed/graph/v1/multimodal.npz`（35 MB，加载即用，无需重建）

## 关键文档

- [项目进度与交接说明.md](项目进度与交接说明.md) —— 先读这份
- [AGENTS.md](AGENTS.md) —— 用 AI 协作者时先喂这份
- [docs/项目说明书-v3.0.md](docs/项目说明书-v3.0.md)
- [docs/数据冻结与开发就绪报告.md](docs/数据冻结与开发就绪报告.md)
- [docs/开发进展-多模式图与等时圈试点.md](docs/开发进展-多模式图与等时圈试点.md)
- [docs/design-guidelines.md](docs/design-guidelines.md) —— 做前端页面之前读
- [docs/数据字典-v1.md](docs/数据字典-v1.md)

## 已知限制

- 公交 **591/694** 条（缺 103 条：夜行线、P 字头郊区线、区间车），不能表述为"武汉全部公交"；
- 时刻是**频率级**（工作日/周末 × 发车间隔），没有逐班次 `stop_times`；
- POI 仅 1.4 万个且集中在中心城区，POI 统计只反映 OSM 覆盖度；
- 地铁站是站中心点，没有出入口数据；
- 步行路网缺人行道、天桥、地下通道细节。

## 数据来源

- 路网 / POI：OpenStreetMap（Geofabrik 湖北提取）
- 公交 / 地铁站点与线路：高德开放平台（已缓存，勿重复抓取）
- 行政边界：武汉市 1:100 万矢量边界

## 许可

仅供课程学习与教学演示使用。OSM 数据遵循 ODbL，高德数据遵循其开放平台协议。
