# -*- coding: utf-8 -*-
"""Pilot: 15/30/45-minute isochrones for three Wuhan test points.

Outputs (data/output/isochrones/v1/):
    <point>_<budget>.geojson    one file per point and budget
    pilot_isochrones.geojson    all nine polygons, with attributes
    pilot_summary.json          areas, POI counts, reachable stops, example paths
    pilot_map.png               three-panel map for visual review
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import shapely

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT  # noqa: E402
from app.graph import METRO_STOP, load_or_build  # noqa: E402
from app.isochrone import (  # noqa: E402
    explain_path,
    nearest_walk_node,
    poi_stats,
    reachable_stops,
    surface_polygons,
    time_surface,
    travel_times,
)

OUT = ROOT / "data" / "output" / "isochrones" / "v1"
V1 = ROOT / "data" / "processed" / "v1"
BUDGETS = (900, 1800, 2700)
BUDGET_LABELS = {900: "15", 1800: "30", 2700: "45"}
COLORS = {"15": "#2b8cbe", "30": "#fec44f", "45": "#d7301f"}

TEST_POINTS = [
    ("wuda", "武汉大学（八一路珞珈山）", 114.354658, 30.534155),
    ("guanggu", "光谷广场", 114.396500, 30.505500),
    ("hankou_station", "汉口火车站", 114.253800, 30.618500),
]

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _utm_one(lng: float, lat: float) -> tuple[float, float]:
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    x, y = tr.transform(lng, lat)
    return float(x), float(y)


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    g = load_or_build(cache=True, params=DEFAULT)
    boundary = (
        gpd.read_file(V1 / "wuhan_boundary.geojson").to_crs(32650).geometry.union_all()
    )
    poi = gpd.read_file(V1 / "poi.gpkg", layer="poi_points")
    print(f"[pilot] graph {g.n_nodes:,} nodes, {g.csr.nnz:,} edges")

    features: list[dict] = []
    summary: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dataset_version": "v1",
        "params": DEFAULT.to_dict(),
        "graph": g.stats,
        "points": [],
    }
    panels = []

    for slug, label, lng, lat in TEST_POINTS:
        print(f"\n=== {label} ({lng}, {lat}) ===")
        origin, snap_m = nearest_walk_node(g, lng, lat)
        dist, pred = travel_times(g, origin, predecessors=True)
        id_map = dict(zip(g.named_idx.tolist(), g.named_id.tolist()))

        ox, oy = _utm_one(lng, lat)
        bbox = (ox - 30_000, oy - 30_000, ox + 30_000, oy + 30_000)
        X, Y, Z = time_surface(g, dist, bbox, res_m=100.0)
        surf = surface_polygons(X, Y, Z, list(BUDGETS), boundary, smooth_m=110.0)

        polys: dict[str, shapely.Geometry] = {}
        point_summary = {
            "slug": slug,
            "label": label,
            "lng": lng,
            "lat": lat,
            "origin_snap_m": round(snap_m, 1),
            "budgets": [],
        }
        for b in BUDGETS:
            lab = BUDGET_LABELS[b]
            poly = surf[float(b)]
            polys[lab] = poly

            stops = reachable_stops(g, dist, b)
            stats = poi_stats(poly, poi)
            area_km2 = poly.area / 1e6
            entry = {
                "budget_min": b // 60,
                "area_km2": round(area_km2, 2),
                "bus_stops_reached": int(len(stops["bus"])),
                "metro_stations_reached": int(len(stops["metro"])),
                "poi_total": stats["total"],
                "poi_by_category": stats["by_category"],
            }
            point_summary["budgets"].append(entry)
            print(
                f"  {lab:>2} min: {area_km2:8.2f} km2  bus {entry['bus_stops_reached']:>4}  "
                f"metro {entry['metro_stations_reached']:>3}  POI {stats['total']:>5}"
            )

            geom_wgs = gpd.GeoSeries([poly], crs=32650).to_crs(4326).iloc[0]
            props = {
                "point": slug,
                "label": label,
                "budget_min": b // 60,
                "area_km2": entry["area_km2"],
                "poi_total": entry["poi_total"],
                "bus_stops": entry["bus_stops_reached"],
                "metro_stations": entry["metro_stations_reached"],
            }
            features.append(
                {
                    "type": "Feature",
                    "properties": props,
                    "geometry": shapely.geometry.mapping(geom_wgs),
                }
            )
            gpd.GeoDataFrame([props], geometry=[geom_wgs], crs=4326).to_file(
                OUT / f"{slug}_{lab}.geojson", driver="GeoJSON"
            )

        point_summary["nested"] = bool(
            polys["15"].within(polys["30"].buffer(1))
            and polys["30"].within(polys["45"].buffer(1))
        )
        print(f"  nested 15<30<45: {point_summary['nested']}")

        # explain example trips: nearest and farthest metro station within 30 min
        metro_nodes = np.flatnonzero(g.kind == METRO_STOP)
        cand = metro_nodes[dist[metro_nodes] <= 1800]
        examples = []
        if len(cand):
            for target in (cand[np.argmin(dist[cand])], cand[np.argmax(dist[cand])]):
                legs = explain_path(g, origin, int(target), pred, id_map)
                name = id_map.get(int(target), str(target))
                examples.append(
                    {
                        "target": name,
                        "total_min": round(float(dist[target]) / 60, 1),
                        "legs": legs,
                    }
                )
                print(
                    f"  example -> {name}: {dist[target] / 60:5.1f} min  "
                    + " | ".join(f"{l['mode']} {l['seconds'] / 60:.1f}" for l in legs)
                )
        point_summary["examples"] = examples
        summary["points"].append(point_summary)
        panels.append((slug, label, {"polys": polys, "origin": (lng, lat)}))

    combined = gpd.GeoDataFrame.from_features(features, crs=4326)
    combined.to_file(OUT / "pilot_isochrones.geojson", driver="GeoJSON")
    (OUT / "pilot_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    render(panels)
    print(f"\n[pilot] wrote {OUT}")
    print(f"[pilot] elapsed {time.time() - t0:.1f}s")


def render(panels) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(21, 7.6), constrained_layout=True)
    sb = pd.read_csv(V1 / "stops_bus.csv")
    sm = pd.read_csv(V1 / "stops_metro.csv")
    for ax, (slug, label, data) in zip(axes, panels):
        for lab in ("45", "30", "15"):
            poly = gpd.GeoSeries([data["polys"][lab]], crs=32650).to_crs(4326).iloc[0]
            gpd.GeoSeries([poly], crs=4326).plot(
                ax=ax, color=COLORS[lab], alpha=0.32,
                edgecolor=COLORS[lab], linewidth=1.1, zorder=3,
            )
        ax.scatter(sb["lng"], sb["lat"], s=0.7, c="#1f78d1", alpha=0.45, zorder=2)
        ax.scatter(sm["lng"], sm["lat"], s=9, c="#111111", marker="^", zorder=4)
        ax.scatter(*data["origin"], s=140, c="#ffffff", edgecolor="#000000", zorder=6)
        ax.text(
            *data["origin"], "  " + label, fontsize=10, zorder=7,
            bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=1.5),
        )
        ax.set_title(f"{label}\n15 / 30 / 45 分钟（步行 + 公交 + 地铁）", fontsize=11)
        ax.set_aspect("equal")
        ax.set_xlabel("经度")
        ax.set_ylabel("纬度")
        bounds = gpd.GeoSeries([data["polys"]["45"]], crs=32650).to_crs(4326).total_bounds
        pad = 0.015
        ax.set_xlim(bounds[0] - pad, bounds[2] + pad)
        ax.set_ylim(bounds[1] - pad, bounds[3] + pad)
    out = OUT / "pilot_map.png"
    fig.savefig(out, dpi=140)
    print(f"[pilot] map -> {out}")


if __name__ == "__main__":
    main()
