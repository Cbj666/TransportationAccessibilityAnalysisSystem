# frontend —— Vue 3 + 百度地图（待建）

尚未开始。计划：

- Vite + Vue 3 + TypeScript；
- 百度地图 JS API GL（底图 + 坐标转换：后端输出 WGS84，百度需要 BD-09，前端做 `BMap.Convertor` 或本地转换）；
- 图层：等时圈（15/30/45 三档）、公交/地铁站点、POI 热力；
- 交互：点选起点、时间预算滑块、换乘偏好、候选地对比；
- 数据源：`backend` 的 API（待建）或直接读 `data/output/isochrones/v1/*.geojson` 做静态演示。

## 约定

- 后端输出的 GeoJSON 一律 **WGS84**，坐标转换只在前端做一次；
- 前端不要直接读 `data/`，走 API（后期）或把 GeoJSON 拷到 `frontend/public/`（首版演示）；
- 目录保持 `src/{api,components,views,stores,utils}`。

## 目录占位

```text
frontend/
├── README.md      ← 本文件
└── src/           ← 待创建
```
