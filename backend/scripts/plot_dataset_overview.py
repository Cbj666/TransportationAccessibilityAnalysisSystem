# -*- coding: utf-8 -*-
"""Render a quick overview of the frozen v1 dataset for visual verification."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[2]  # project root
V1 = ROOT / "data" / "processed" / "v1"
OUT = ROOT / "data" / "output" / "v1_overview.png"


def main() -> None:
    b = gpd.read_file(V1 / "wuhan_boundary.geojson")
    wr = gpd.read_file(V1 / "osm_walk_roads.gpkg", layer="walk_roads")
    sb = pd.read_csv(V1 / "stops_bus.csv")
    sm = pd.read_csv(V1 / "stops_metro.csv")
    poi = gpd.read_file(V1 / "poi.gpkg", layer="poi_points")
    poi = poi[poi["in_boundary"]]

    fig, axes = plt.subplots(1, 2, figsize=(17, 8.4), constrained_layout=True)
    b.plot(ax=axes[0], facecolor="#f2f4f7", edgecolor="#333333", linewidth=1.2, zorder=0)
    wr[wr["in_boundary"]].plot(ax=axes[0], color="#9aa4b2", linewidth=0.08, zorder=1)
    axes[0].scatter(sb["lng"], sb["lat"], s=0.8, c="#1f78d1", alpha=0.55, zorder=2, label=f"公交站 {len(sb)}")
    axes[0].scatter(sm["lng"], sm["lat"], s=14, c="#d62728", marker="^", zorder=3, label=f"地铁站 {len(sm)}")
    axes[0].set_title("武汉步行路网 + 公交/地铁站点（v1 冻结数据）")
    axes[0].legend(loc="lower left", markerscale=6, fontsize=9)
    axes[0].set_xlabel("经度"); axes[0].set_ylabel("纬度")

    b.plot(ax=axes[1], facecolor="#ffffff", edgecolor="#333333", linewidth=1.0, zorder=0)
    vc = poi["category"].value_counts()
    colors = plt.cm.tab20.colors
    for i, (cat, grp) in enumerate(poi.groupby("category")):
        x = grp.geometry.x.to_numpy(); y = grp.geometry.y.to_numpy()
        axes[1].scatter(x, y, s=1.6, color=colors[i % len(colors)], label=f"{cat} {len(grp)}", alpha=0.7)
    axes[1].set_title("OSM POI 分类分布（边界内）")
    axes[1].legend(loc="lower left", markerscale=5, fontsize=8, ncol=2)
    axes[1].set_xlabel("经度")

    for ax in axes:
        ax.set_aspect("equal")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
