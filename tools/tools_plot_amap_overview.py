from pathlib import Path
import sys

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from pilot_line import load_roads

INTERIM = ROOT / "data" / "interim"
OUTPUT = ROOT / "data" / "output"

stations = pd.read_csv(INTERIM / "amap_bus_stations_snapped.csv")
edges = pd.read_csv(INTERIM / "amap_bus_edges.csv")
coords = {
    row.station_key: (row.lng_wgs84, row.lat_wgs84)
    for row in stations.itertuples()
}

lines = []
for row in edges.itertuples():
    a = coords.get(row.from_station_key)
    b = coords.get(row.to_station_key)
    if a and b:
        lines.append(LineString([a, b]))
edges_gdf = gpd.GeoDataFrame(geometry=lines, crs=4326)

boundary = gpd.read_file(ROOT / "武汉市_市.geojson").to_crs(4326)
minx, miny, maxx, maxy = boundary.total_bounds
roads = load_roads((minx - 0.05, miny - 0.05, maxx + 0.05, maxy + 0.05)).to_crs(4326)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(figsize=(14, 14), dpi=180)
roads.plot(ax=ax, color="#dee2e6", linewidth=0.25, zorder=1)
edges_gdf.plot(ax=ax, color="#f08c00", linewidth=0.35, alpha=0.45, zorder=2)
high = stations[stations["snap_quality"] == "high"]
low = stations[stations["snap_quality"] == "low"]
ax.scatter(high["lng_wgs84"], high["lat_wgs84"], s=1.2, c="#1971c2", alpha=0.75, zorder=3, label="高/中吸附质量")
ax.scatter(low["lng_wgs84"], low["lat_wgs84"], s=10, c="#c92a2a", marker="x", linewidths=0.8, zorder=4, label="吸附距离 >80m")
boundary.boundary.plot(ax=ax, color="#c92a2a", linewidth=1.2, zorder=5)
ax.set_xlim(minx, maxx)
ax.set_ylim(miny, maxy)
ax.set_aspect(1 / 0.86)
ax.set_title("武汉公交网络与 OSM 路网叠加总览", fontsize=16)
ax.set_xlabel("经度")
ax.set_ylabel("纬度")
ax.grid(True, linestyle=":", alpha=0.25)
ax.legend(loc="lower left", markerscale=4, fontsize=10)
fig.tight_layout()
out = OUTPUT / "amap_bus_network_overview.png"
fig.savefig(out)
plt.close(fig)
print("wrote:", out)
print("stations:", len(stations), "edges:", len(edges_gdf), "roads:", len(roads))
