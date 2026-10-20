from pathlib import Path
import json
import sys

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely.ops import nearest_points
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]  # project root
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
METRO = ROOT / "data" / "interim" / "amap_metro"
OUTPUT = ROOT / "data" / "output"

stations = pd.read_csv(METRO / "metro_stations.csv")
routes = gpd.read_file(METRO / "metro_routes.geojson").to_crs(4326)
boundary = gpd.read_file(BOUNDARY).to_crs(4326)

minx, miny = stations["lng_wgs84"].min() - 0.05, stations["lat_wgs84"].min() - 0.05
maxx, maxy = stations["lng_wgs84"].max() + 0.05, stations["lat_wgs84"].max() + 0.05
roads = gpd.read_file(
    OSM_GPKG,
    layer="gis_osm_roads_free",
    bbox=(minx, miny, maxx, maxy),
    engine="pyogrio",
).to_crs(32650)
walkable = {
    "footway", "pedestrian", "path", "steps", "living_street", "residential",
    "service", "unclassified", "tertiary", "tertiary_link", "secondary",
    "secondary_link", "primary", "primary_link", "trunk", "trunk_link", "cycleway",
}
roads = roads[roads["fclass"].isin(walkable)].copy()
road_geoms = list(roads.geometry)
tree = STRtree(road_geoms)

points = gpd.GeoDataFrame(
    stations.copy(),
    geometry=gpd.points_from_xy(stations["lng_wgs84"], stations["lat_wgs84"]),
    crs=4326,
).to_crs(32650)
snapped = []
for point in points.geometry:
    index = int(tree.nearest(point))
    road = roads.iloc[index]
    snap = nearest_points(point, road.geometry)[1]
    snapped.append(
        {
            "road_fclass": road.get("fclass", ""),
            "road_name": road.get("name", ""),
            "snap_distance_m": round(point.distance(snap), 1),
            "geometry": snap,
        }
    )
snapped_gdf = gpd.GeoDataFrame(snapped, geometry="geometry", crs=32650).to_crs(4326)
out = stations.copy()
out["road_fclass"] = snapped_gdf["road_fclass"].values
out["road_name"] = snapped_gdf["road_name"].values
out["snap_distance_m"] = snapped_gdf["snap_distance_m"].values
out["snap_lng"] = snapped_gdf.geometry.x.values
out["snap_lat"] = snapped_gdf.geometry.y.values
out["snap_quality"] = "high"
out.loc[out["snap_distance_m"] > 80, "snap_quality"] = "low"
out.to_csv(METRO / "metro_stations_snapped.csv", index=False, encoding="utf-8-sig")
gpd.GeoDataFrame(out.copy(), geometry=gpd.points_from_xy(out["snap_lng"], out["snap_lat"]), crs=4326).to_file(
    METRO / "metro_stations_snapped.geojson", driver="GeoJSON"
)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(figsize=(13, 13), dpi=180)
roads.to_crs(4326).plot(ax=ax, color="#e9ecef", linewidth=0.25, zorder=1)
routes.plot(ax=ax, column="public_line", linewidth=1.8, alpha=0.75, zorder=2, legend=False)
high = out[out["snap_quality"] == "high"]
low = out[out["snap_quality"] == "low"]
ax.scatter(high["lng_wgs84"], high["lat_wgs84"], s=10, c="#c92a2a", zorder=3, label="地铁站（吸附≤80m）")
ax.scatter(low["lng_wgs84"], low["lat_wgs84"], s=22, c="#f08c00", marker="x", zorder=4, label="地铁站（吸附>80m）")
boundary.boundary.plot(ax=ax, color="#495057", linewidth=1.0, zorder=5)
ax.set_xlim(boundary.total_bounds[0], boundary.total_bounds[2])
ax.set_ylim(boundary.total_bounds[1], boundary.total_bounds[3])
ax.set_aspect(1 / 0.86)
ax.set_title("武汉地铁线路、站点与 OSM 步行路网", fontsize=15)
ax.set_xlabel("经度")
ax.set_ylabel("纬度")
ax.grid(True, linestyle=":", alpha=0.25)
ax.legend(loc="lower left", fontsize=9)
fig.tight_layout()
fig.savefig(OUTPUT / "metro_network_overview.png")
plt.close(fig)

qa = {
    "stations": int(len(out)),
    "high_quality": int((out["snap_quality"] == "high").sum()),
    "low_quality": int((out["snap_quality"] == "low").sum()),
    "snap_median_m": round(float(out["snap_distance_m"].median()), 2),
    "snap_p90_m": round(float(out["snap_distance_m"].quantile(0.90)), 2),
    "snap_max_m": round(float(out["snap_distance_m"].max()), 2),
}
(METRO / "metro_snap_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(qa, ensure_ascii=False, indent=2))
