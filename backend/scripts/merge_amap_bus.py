from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # project root
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo_utils import gcj02_to_wgs84, haversine_m
from pilot_line import load_roads, snap_stations


RAW_DIR = ROOT / "data" / "interim" / "amap_pilot"
OUT_DIR = ROOT / "data" / "interim"
OUTPUT_DIR = ROOT / "data" / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def read_raw_records() -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    line_rows = []
    for path in sorted(RAW_DIR.glob("raw_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        label = payload.get("label", "")
        directions = payload.get("directions", [])
        line_rows.append(
            {
                "label": label,
                "direction_count": len(directions),
                "line_ids": "|".join(str(d.get("id", "")) for d in directions),
                "line_names": "|".join(str(d.get("name", "")) for d in directions),
            }
        )
        for direction in directions:
            line_id = str(direction.get("id", ""))
            line_name = str(direction.get("name", ""))
            for stop in direction.get("busstops", []):
                location = str(stop.get("location", ""))
                if "," not in location:
                    continue
                lng, lat = location.split(",", 1)
                try:
                    lng_gcj, lat_gcj = float(lng), float(lat)
                except ValueError:
                    continue
                lng_wgs, lat_wgs = gcj02_to_wgs84(lng_gcj, lat_gcj)
                records.append(
                    {
                        "label": label,
                        "line_id": line_id,
                        "line_name": line_name,
                        "sequence": int(stop.get("sequence", 0) or 0),
                        "station_id": str(stop.get("id", "")),
                        "station_name": str(stop.get("name", "")),
                        "lng_gcj02": lng_gcj,
                        "lat_gcj02": lat_gcj,
                        "lng_wgs84": lng_wgs,
                        "lat_wgs84": lat_wgs,
                    }
                )
    return pd.DataFrame(records), pd.DataFrame(line_rows)


def assign_station_keys(records: pd.DataFrame, cluster_m: float = 100.0) -> pd.DataFrame:
    """Split a reused 高德 station_id into spatial clusters when its records are far apart."""
    records = records.copy()
    key_map = {}
    for station_id, group in records.groupby("station_id", sort=False):
        points = list(group[["lng_wgs84", "lat_wgs84"]].itertuples(index=False, name=None))
        if not points:
            continue
        # greedy clustering around running centroids
        clusters = []
        for lng, lat in points:
            assigned = False
            for cluster in clusters:
                distance = haversine_m(lng, lat, cluster["lng"], cluster["lat"])
                if distance <= cluster_m:
                    cluster["points"].append((lng, lat))
                    cluster["lng"] = sum(p[0] for p in cluster["points"]) / len(cluster["points"])
                    cluster["lat"] = sum(p[1] for p in cluster["points"]) / len(cluster["points"])
                    assigned = True
                    break
            if not assigned:
                clusters.append({"lng": lng, "lat": lat, "points": [(lng, lat)]})
        if len(clusters) == 1:
            key_map[station_id] = [(station_id, clusters[0]["lng"], clusters[0]["lat"])]
        else:
            key_map[station_id] = [
                (f"{station_id}__C{index + 1}", cluster["lng"], cluster["lat"])
                for index, cluster in enumerate(clusters)
            ]

    keys = []
    for row in records.itertuples():
        candidates = key_map.get(row.station_id, [])
        if not candidates:
            keys.append(row.station_id)
            continue
        best = min(candidates, key=lambda item: haversine_m(row.lng_wgs84, row.lat_wgs84, item[1], item[2]))
        keys.append(best[0])
    records["station_key"] = keys
    return records


def build_stations(records: pd.DataFrame) -> pd.DataFrame:
    valid = records[records["station_id"].astype(str).str.len() > 0].copy()
    grouped = (
        valid.groupby("station_key", as_index=False)
        .agg(
            station_id=("station_id", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
            station_name=("station_name", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
            lng_wgs84=("lng_wgs84", "median"),
            lat_wgs84=("lat_wgs84", "median"),
            line_count=("line_id", "nunique"),
            record_count=("line_id", "size"),
        )
        .reset_index(drop=True)
    )
    spreads = []
    for station_key, group in valid.groupby("station_key"):
        lng = float(group["lng_wgs84"].median())
        lat = float(group["lat_wgs84"].median())
        spread = max(haversine_m(lng, lat, row.lng_wgs84, row.lat_wgs84) for row in group.itertuples())
        spreads.append((station_key, spread))
    spread_map = dict(spreads)
    grouped["coord_spread_m"] = grouped["station_key"].map(spread_map).fillna(0).round(1)
    return grouped


def add_inside_wuhan(stations: pd.DataFrame) -> pd.DataFrame:
    boundary_path = BOUNDARY
    if not boundary_path.exists():
        stations["inside_wuhan"] = None
        return stations
    boundary = gpd.read_file(boundary_path).to_crs(4326)
    wuhan = boundary.geometry.union_all()
    points = gpd.GeoDataFrame(
        stations.copy(),
        geometry=gpd.points_from_xy(stations["lng_wgs84"], stations["lat_wgs84"]),
        crs=4326,
    )
    stations["inside_wuhan"] = points.geometry.within(wuhan).values
    return stations


def build_edges(records: pd.DataFrame) -> pd.DataFrame:
    edges = []
    for (label, line_id), group in records.groupby(["label", "line_id"], sort=False):
        group = group.sort_values("sequence")
        rows = list(group.itertuples())
        for left, right in zip(rows, rows[1:]):
            if left.station_key == right.station_key:
                continue
            distance = haversine_m(left.lng_wgs84, left.lat_wgs84, right.lng_wgs84, right.lat_wgs84)
            edges.append(
                {
                    "label": label,
                    "line_id": line_id,
                    "line_name": left.line_name,
                    "from_sequence": left.sequence,
                    "to_sequence": right.sequence,
                    "from_station_key": left.station_key,
                    "to_station_key": right.station_key,
                    "from_station_id": left.station_id,
                    "to_station_id": right.station_id,
                    "from_station_name": left.station_name,
                    "to_station_name": right.station_name,
                    "distance_m": round(distance, 1),
                    "leg_gt_3000m": distance > 3000,
                    "leg_gt_5000m": distance > 5000,
                    "leg_gt_10000m": distance > 10000,
                }
            )
    return pd.DataFrame(edges)


def main():
    records, line_rows = read_raw_records()
    if records.empty:
        raise SystemExit("没有找到 raw_*.json 中的线路站点数据")
    records = records.drop_duplicates(subset=["line_id", "sequence", "station_id", "station_name"]).copy()
    records = assign_station_keys(records, cluster_m=100.0)
    print(
        "records:", len(records),
        "lines:", line_rows["label"].nunique(),
        "raw line ids:", records["line_id"].nunique(),
        "unique station keys:", records["station_key"].nunique(),
    )

    records.to_csv(OUT_DIR / "amap_bus_route_stops.csv", index=False, encoding="utf-8-sig")
    line_rows.to_csv(OUT_DIR / "amap_bus_lines.csv", index=False, encoding="utf-8-sig")

    stations = build_stations(records)
    stations = add_inside_wuhan(stations)
    stations.to_csv(OUT_DIR / "amap_bus_stations.csv", index=False, encoding="utf-8-sig")
    print("unique stations:", len(stations), "inside Wuhan:", int(stations["inside_wuhan"].fillna(False).sum()))

    edges = build_edges(records)
    edges.to_csv(OUT_DIR / "amap_bus_edges.csv", index=False, encoding="utf-8-sig")
    print("edges:", len(edges), "max leg:", round(float(edges["distance_m"].max()), 1) if len(edges) else None)

    minx, miny = stations["lng_wgs84"].min() - 0.05, stations["lat_wgs84"].min() - 0.05
    maxx, maxy = stations["lng_wgs84"].max() + 0.05, stations["lat_wgs84"].max() + 0.05
    roads = load_roads((minx, miny, maxx, maxy))
    print("roads in bbox:", len(roads))
    snapped = snap_stations(stations, roads)
    snapped["flags"] = ""
    snapped.loc[snapped["snap_distance_m"] > 80, "flags"] = "snap_gt_80m"
    snapped.loc[snapped["snap_distance_m"] > 500, "flags"] = "snap_gt_500m"
    snapped["snap_quality"] = "high"
    snapped.loc[snapped["snap_distance_m"] > 80, "snap_quality"] = "low"
    snapped.to_csv(OUT_DIR / "amap_bus_stations_snapped.csv", index=False, encoding="utf-8-sig")

    snapped_gdf = gpd.GeoDataFrame(
        snapped.copy(),
        geometry=gpd.points_from_xy(snapped["snap_lng"], snapped["snap_lat"]),
        crs=4326,
    )
    snapped_gdf.to_file(OUT_DIR / "amap_bus_stations_snapped.geojson", driver="GeoJSON")

    original_ids = stations["station_id"].nunique()
    split_ids = int((stations.groupby("station_id").size() > 1).sum())
    qa = {
        "route_records": int(len(records)),
        "public_lines": int(line_rows["label"].nunique()),
        "line_ids": int(records["line_id"].nunique()),
        "unique_stations": int(len(stations)),
        "original_station_ids": int(original_ids),
        "station_ids_split_by_location": split_ids,
        "stations_inside_wuhan": int(stations["inside_wuhan"].fillna(False).sum()),
        "stations_outside_wuhan": int((~stations["inside_wuhan"].fillna(False)).sum()),
        "edges": int(len(edges)),
        "edges_gt_3000m": int(edges["leg_gt_3000m"].sum()) if len(edges) else 0,
        "edges_gt_5000m": int(edges["leg_gt_5000m"].sum()) if len(edges) else 0,
        "edges_gt_10000m": int(edges["leg_gt_10000m"].sum()) if len(edges) else 0,
        "max_leg_m": round(float(edges["distance_m"].max()), 1) if len(edges) else 0,
        "snap_median_m": round(float(snapped["snap_distance_m"].median()), 2),
        "snap_p90_m": round(float(snapped["snap_distance_m"].quantile(0.90)), 2),
        "snap_p95_m": round(float(snapped["snap_distance_m"].quantile(0.95)), 2),
        "snap_avg_m": round(float(snapped["snap_distance_m"].mean()), 2),
        "snap_max_m": round(float(snapped["snap_distance_m"].max()), 2),
        "snap_gt_80m": int((snapped["snap_distance_m"] > 80).sum()),
        "snap_gt_500m": int((snapped["snap_distance_m"] > 500).sum()),
        "station_coord_spread_gt_50m": int((stations["coord_spread_m"] > 50).sum()),
    }
    (OUTPUT_DIR / "amap_bus_qa_summary.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
