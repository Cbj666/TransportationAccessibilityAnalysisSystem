# -*- coding: utf-8 -*-
"""Data audit: verify integrity of all prepared transport/geo inputs.

Read-only. Writes a JSON + Markdown report under data/output/.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(__file__).resolve().parents[2]  # project root
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
INTERIM = ROOT / "data" / "interim"
METRO = INTERIM / "amap_metro"
OUT = ROOT / "data" / "output"
OUT.mkdir(parents=True, exist_ok=True)

report: dict = {}


def pct(v, n):
    return round(100.0 * v / n, 2) if n else None


def check(name: str, func):
    try:
        res = func()
        report[name] = res
        print(f"[ok]   {name}")
    except Exception as exc:  # noqa: BLE001
        report[name] = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[fail] {name}: {exc}")


def audit():
    # ---------------------------------------------------------------- boundary
    def boundary():
        g = gpd.read_file(BOUNDARY)
        w = g.to_crs(4326)
        b = w.total_bounds
        return {
            "rows": int(len(g)),
            "source_crs": str(g.crs),
            "geom_types": w.geom_type.value_counts().to_dict(),
            "valid": bool(w.is_valid.all()),
            "bounds_wgs84": [round(float(x), 6) for x in b],
            "area_km2": round(float(w.to_crs(3857).area.sum() / 1e6), 2),
        }

    check("boundary", boundary)

    # ------------------------------------------------------------ bus stations
    def bus_stations():
        df = pd.read_csv(INTERIM / "amap_bus_stations_snapped.csv")
        key_dup = int(df["station_key"].duplicated().sum())
        nan_snap = int(df["snap_lng"].isna().sum())
        bad_q = df["snap_quality"].value_counts(dropna=False).to_dict()
        return {
            "rows": int(len(df)),
            "unique_station_key": int(df["station_key"].nunique()),
            "dup_station_key": key_dup,
            "unique_raw_station_id": int(df["station_id"].nunique()),
            "null_snap": nan_snap,
            "outside_wuhan": int((df["inside_wuhan"] == False).sum()),  # noqa: E712
            "snap_quality": {str(k): int(v) for k, v in bad_q.items()},
            "snap_distance_m": {
                "median": round(float(df["snap_distance_m"].median()), 1),
                "p95": round(float(df["snap_distance_m"].quantile(0.95)), 1),
                "max": round(float(df["snap_distance_m"].max()), 1),
            },
            "bounds_wgs84": [
                round(float(df["lng_wgs84"].min()), 6),
                round(float(df["lat_wgs84"].min()), 6),
                round(float(df["lng_wgs84"].max()), 6),
                round(float(df["lat_wgs84"].max()), 6),
            ],
            "line_count_sum": int(df["line_count"].sum()),
        }

    check("bus_stations", bus_stations)

    # --------------------------------------------------------------- bus edges
    def bus_edges():
        e = pd.read_csv(INTERIM / "amap_bus_edges.csv")
        s = pd.read_csv(
            INTERIM / "amap_bus_stations_snapped.csv", usecols=["station_key"]
        )
        keys = set(s["station_key"])
        missing_from = int((~e["from_station_key"].isin(keys)).sum())
        missing_to = int((~e["to_station_key"].isin(keys)).sum())
        loops = int((e["from_station_key"] == e["to_station_key"]).sum())
        dup = int(
            e.duplicated(
                subset=["line_id", "from_sequence", "to_sequence"]
            ).sum()
        )
        neg = int((e["distance_m"] <= 0).sum())
        return {
            "rows": int(len(e)),
            "lines": int(e["line_id"].nunique()),
            "dangling_from_key": missing_from,
            "dangling_to_key": missing_to,
            "self_loops": loops,
            "dup_line_seq": dup,
            "nonpositive_distance": neg,
            "distance_m": {
                "min": round(float(e["distance_m"].min()), 1),
                "median": round(float(e["distance_m"].median()), 1),
                "mean": round(float(e["distance_m"].mean()), 1),
                "p95": round(float(e["distance_m"].quantile(0.95)), 1),
                "max": round(float(e["distance_m"].max()), 1),
            },
            "gt_3000m": int(e["leg_gt_3000m"].sum()),
            "gt_5000m": int(e["leg_gt_5000m"].sum()),
            "gt_10000m": int(e["leg_gt_10000m"].sum()),
        }

    check("bus_edges", bus_edges)

    # --------------------------------------------------------- bus route stops
    def bus_route_stops():
        r = pd.read_csv(INTERIM / "amap_bus_route_stops.csv")
        dup = int(r.duplicated(subset=["line_id", "sequence"]).sum())
        nullkey = int(r["station_key"].isna().sum())
        return {
            "rows": int(len(r)),
            "lines": int(r["line_id"].nunique()),
            "directions": int(r["line_name"].nunique()),
            "null_station_key": nullkey,
            "dup_line_seq": dup,
            "seq_min": int(r["sequence"].min()),
            "seq_max": int(r["sequence"].max()),
        }

    check("bus_route_stops", bus_route_stops)

    # -------------------------------------------------------------- bus shapes
    def bus_shapes():
        g = gpd.read_file(INTERIM / "amap_bus_routes.geojson")
        return {
            "rows": int(len(g)),
            "crs": str(g.crs),
            "geom_types": g.geom_type.value_counts().to_dict(),
            "valid": bool(g.is_valid.all()),
            "empty_geom": int(g.geometry.is_empty.sum()),
            "bounds_wgs84": [round(float(x), 6) for x in g.total_bounds],
            "cols": g.columns.tolist(),
        }

    check("bus_shapes", bus_shapes)

    # ------------------------------------------------------------ metro stuff
    def metro_stations():
        df = pd.read_csv(METRO / "metro_stations_snapped.csv")
        return {
            "rows": int(len(df)),
            "unique_station_id": int(df["station_id"].nunique()),
            "null_snap": int(df["snap_lng"].isna().sum()),
            "snap_quality": {
                str(k): int(v)
                for k, v in df["snap_quality"].value_counts(dropna=False).items()
            },
            "snap_distance_m": {
                "median": round(float(df["snap_distance_m"].median()), 1),
                "max": round(float(df["snap_distance_m"].max()), 1),
            },
            "line_count_hist": {
                str(k): int(v)
                for k, v in df["line_count"].value_counts().sort_index().items()
            },
        }

    check("metro_stations", metro_stations)

    def metro_edges():
        e = pd.read_csv(METRO / "metro_edges.csv")
        s = pd.read_csv(METRO / "metro_stations.csv")
        keys = set(s["station_id"])
        return {
            "rows": int(len(e)),
            "directions": int(e["line_id"].nunique()),
            "dangling_from": int((~e["from_station_id"].isin(keys)).sum()),
            "dangling_to": int((~e["to_station_id"].isin(keys)).sum()),
            "self_loops": int((e["from_station_id"] == e["to_station_id"]).sum()),
            "distance_m": {
                "min": round(float(e["distance_m"].min()), 1),
                "median": round(float(e["distance_m"].median()), 1),
                "max": round(float(e["distance_m"].max()), 1),
            },
        }

    check("metro_edges", metro_edges)

    def metro_schedule():
        df = pd.read_csv(METRO / "metro_schedule.csv")
        return {
            "rows": int(len(df)),
            "lines": int(df["line_id"].nunique()),
            "day_types": df["day_type"].value_counts().to_dict(),
            "period_types": df["period_type"].value_counts().to_dict(),
            "interval_s_range": [
                int(df["interval_seconds"].min()),
                int(df["interval_seconds"].max()),
            ],
            "interval_s_median": int(df["interval_seconds"].median()),
        }

    check("metro_schedule", metro_schedule)

    # ---------------------------------------------------- bus<->metro proximity
    def bus_metro_transfer():
        b = pd.read_csv(INTERIM / "amap_bus_stations_snapped.csv")
        m = pd.read_csv(METRO / "metro_stations_snapped.csv")
        b_ptr = np.asarray(b["lng_wgs84"], dtype=float)
        b_ptl = np.asarray(b["lat_wgs84"], dtype=float)
        m_ptr = np.radians(np.asarray(m["lng_wgs84"], dtype=float))
        m_ptl = np.radians(np.asarray(m["lat_wgs84"], dtype=float))
        p_lon = np.radians(b_ptr)[:, None]
        p_lat = np.radians(b_ptl)[:, None]
        dlon = m_ptr[None, :] - p_lon
        dlat = m_ptl[None, :] - p_lat
        a = np.sin(dlat / 2) ** 2 + np.cos(p_lat) * np.cos(m_ptl)[None, :] * np.sin(
            dlon / 2
        ) ** 2
        d = 2 * 6371008.8 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        nearest = d.min(axis=1)
        s = pd.Series(nearest)
        return {
            "bus_stops_within_50m": int((s <= 50).sum()),
            "bus_stops_within_100m": int((s <= 100).sum()),
            "bus_stops_within_200m": int((s <= 200).sum()),
            "bus_stops_within_500m": int((s <= 500).sum()),
            "bus_stops_within_800m": int((s <= 800).sum()),
            "median_nearest_m": round(float(s.median()), 1),
            "p90_nearest_m": round(float(s.quantile(0.90)), 1),
            "note": "haversine nearest metro station per bus stop (station centre)",
        }

    check("bus_metro_proximity", bus_metro_transfer)


def osm_inventory():
    """Count OSM features clipped to Wuhan bbox."""
    gpkg = OSM_GPKG
    b = gpd.read_file(BOUNDARY).to_crs(4326).total_bounds
    bbox = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    layers = [
        "gis_osm_roads_free",
        "gis_osm_pois_free",
        "gis_osm_pofw_free",
        "gis_osm_transport_free",
        "gis_osm_places_free",
        "gis_osm_traffic_free",
        "gis_osm_railways_free",
        "gis_osm_natural_free",
        "gis_osm_buildings_a_free",
        "gis_osm_adminareas_a_free",
    ]
    out = {"bbox_wgs84": [round(x, 5) for x in bbox], "layers": {}}
    for layer in layers:
        try:
            info = pyogrio.read_info(str(gpkg), layer=layer)
            g = pyogrio.read_dataframe(
                str(gpkg), layer=layer, bbox=bbox, read_geometry=False
            )
            out["layers"][layer] = {
                "hubei_total": int(info["features"]),
                "in_bbox": int(len(g)),
                "fields": list(info["fields"]),
            }
            print(f"[osm]  {layer}: {info['features']} total / {len(g)} in bbox")
        except Exception as exc:  # noqa: BLE001
            out["layers"][layer] = {"error": str(exc)}
            print(f"[osm!] {layer}: {exc}")
    report["osm_inventory"] = out


def main():
    audit()
    osm_inventory()
    (OUT / "data_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nwrote", OUT / "data_audit.json")


if __name__ == "__main__":
    sys.exit(main())
