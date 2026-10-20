from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import box

ROOT = Path(".")
boundary = gpd.read_file(ROOT / "武汉市_市.geojson")
print("boundary crs:", boundary.crs, "features:", len(boundary))
boundary = boundary.to_crs(4326)
print("boundary bounds:", boundary.total_bounds)

# area in CGCS2000 / 3-degree Gauss-Kruger CM 114E
boundary_m = boundary.to_crs(4547)
print("Wuhan area km2:", round(boundary_m.area.sum() / 1e6, 1))

h50_dir = ROOT / "data" / "raw" / "h50c002001" / "h50c002001"
roads = gpd.read_file(h50_dir / "lrdl.shp").to_crs(4326)
water = gpd.read_file(h50_dir / "hyda.shp").to_crs(4326)
residential = gpd.read_file(h50_dir / "resa.shp").to_crs(4326)
railways = gpd.read_file(h50_dir / "lrrl.shp").to_crs(4326)

print("h50 roads:", len(roads), "grade counts:")
print(roads["RTEG"].fillna("(空)").value_counts().to_string())
print("h50 railways:", len(railways), "water polygons:", len(water), "residential polygons:", len(residential))

# coverage fraction of the map sheet over Wuhan
sheet = gpd.GeoDataFrame(geometry=[box(114.0, 30.0, 115.5, 31.0)], crs=4326).to_crs(4547)
wuhan_m = boundary.to_crs(4547)
intersection = wuhan_m.geometry.intersection(sheet.geometry.iloc[0])
covered = intersection.area.sum()
print("sheet-covered Wuhan area km2:", round(covered / 1e6, 1))
print("coverage fraction:", f"{covered / wuhan_m.area.sum():.1%}")

# clip to Wuhan for a quick overview
roads_w = gpd.clip(roads, boundary)
water_w = gpd.clip(water, boundary)
res_w = gpd.clip(residential, boundary)
rail_w = gpd.clip(railways, boundary)
print("within Wuhan: roads", len(roads_w), "water", len(water_w), "residential", len(res_w), "railways", len(rail_w))

fig, ax = plt.subplots(figsize=(10, 10), dpi=180)
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
water_w.plot(ax=ax, color="#a5d8ff", edgecolor="none", alpha=0.8, zorder=1)
res_w.plot(ax=ax, color="#ffe8cc", edgecolor="none", alpha=0.8, zorder=2)
roads_w.plot(ax=ax, color="#868e96", linewidth=0.5, alpha=0.8, zorder=3)
rail_w.plot(ax=ax, color="#7048e8", linewidth=1.2, alpha=0.9, zorder=4)
boundary.boundary.plot(ax=ax, color="#c92a2a", linewidth=1.6, zorder=5)
ax.set_title("武汉市行政边界与 1:25 万矢量地图（裁剪后）", fontsize=14)
ax.set_xlabel("经度")
ax.set_ylabel("纬度")
ax.set_aspect(1 / 0.86)
ax.grid(True, linestyle=":", alpha=0.25)
fig.tight_layout()
out = ROOT / "data" / "output" / "wuhan_h50_overview.png"
fig.savefig(out)
plt.close(fig)
print("wrote:", out)
