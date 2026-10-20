from pathlib import Path
import json
import sys

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[2]  # project root
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo_utils import gcj02_to_wgs84
from pilot_line import load_roads

RAW = ROOT / "data" / "interim" / "amap_pilot"
INTERIM = ROOT / "data" / "interim"
OUTPUT = ROOT / "data" / "output"

records = []
shapes = []
empty = 0
for path in sorted(RAW.glob("raw_*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    label = payload.get("label", "")
    for direction in payload.get("directions", []):
        raw = str(direction.get("polyline", "") or "")
        coords = []
        for pair in raw.split(";"):
            if "," not in pair:
                continue
            try:
                lng, lat = (float(v) for v in pair.split(",", 1))
            except ValueError:
                continue
            coords.append(gcj02_to_wgs84(lng, lat))
        if len(coords) < 2:
            empty += 1
            continue
        shapes.append(
            {
                "label": label,
                "line_id": str(direction.get("id", "")),
                "line_name": str(direction.get("name", "")),
                "start_stop": str(direction.get("start_stop", "")),
                "end_stop": str(direction.get("end_stop", "")),
                "distance_km": direction.get("distance", ""),
                "loop": direction.get("loop", ""),
                "point_count": len(coords),
                "geometry": LineString(coords),
            }
        )
        records.append(
            {
                "label": label,
                "line_id": str(direction.get("id", "")),
                "line_name": str(direction.get("name", "")),
                "start_stop": str(direction.get("start_stop", "")),
                "end_stop": str(direction.get("end_stop", "")),
                "distance_km": direction.get("distance", ""),
                "loop": direction.get("loop", ""),
                "point_count": len(coords),
            }
        )

gdf = gpd.GeoDataFrame(shapes, geometry="geometry", crs=4326)
gdf["geometry"] = gdf.geometry.simplify(0.00005, preserve_topology=True)
gdf.to_file(INTERIM / "amap_bus_routes.geojson", driver="GeoJSON")
pd.DataFrame(records).to_csv(INTERIM / "amap_bus_route_shapes.csv", index=False, encoding="utf-8-sig")

boundary = gpd.read_file(BOUNDARY).to_crs(4326)
minx, miny, maxx, maxy = boundary.total_bounds
roads = load_roads((minx - 0.05, miny - 0.05, maxx + 0.05, maxy + 0.05)).to_crs(4326)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(figsize=(14, 14), dpi=180)
roads.plot(ax=ax, color="#e9ecef", linewidth=0.2, zorder=1)
gdf.plot(ax=ax, color="#f08c00", linewidth=0.55, alpha=0.65, zorder=2)
boundary.boundary.plot(ax=ax, color="#c92a2a", linewidth=1.2, zorder=3)
ax.set_xlim(minx, maxx)
ax.set_ylim(miny, maxy)
ax.set_aspect(1 / 0.86)
ax.set_title("武汉公交线路实际走向与 OSM 路网", fontsize=16)
ax.set_xlabel("经度")
ax.set_ylabel("纬度")
ax.grid(True, linestyle=":", alpha=0.25)
fig.tight_layout()
fig.savefig(OUTPUT / "amap_bus_routes_overview.png")
plt.close(fig)

qa = {
    "route_shapes": len(gdf),
    "empty_polyline_directions": empty,
    "total_points": int(sum(records[i]["point_count"] for i in range(len(records)))),
    "geojson": str(INTERIM / "amap_bus_routes.geojson"),
    "overview": str(OUTPUT / "amap_bus_routes_overview.png"),
}
(OUTPUT / "amap_bus_routes_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(qa, ensure_ascii=False, indent=2))
