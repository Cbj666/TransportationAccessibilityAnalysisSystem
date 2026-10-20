# -*- coding: utf-8 -*-
"""Read the frozen v1 dataset back and verify it is usable for development."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

ROOT = Path(__file__).resolve().parents[2]  # project root
V1 = ROOT / "data" / "processed" / "v1"


def show(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    man = json.loads((V1 / "manifest.json").read_text(encoding="utf-8"))
    show("manifest")
    print("files:", len(man["files"]))
    for f in man["files"]:
        rows = f.get("rows", f.get("features"))
        print(f"  {f['name']:<24} {f['bytes']/1024:>9.1f} KB  rows={rows}")

    show("boundary")
    b = gpd.read_file(V1 / "wuhan_boundary.geojson")
    print("crs", b.crs, "valid", bool(b.is_valid.all()))
    print("bounds", [round(x, 4) for x in b.total_bounds])

    show("stops")
    sb = pd.read_csv(V1 / "stops_bus.csv")
    sm = pd.read_csv(V1 / "stops_metro.csv")
    print("bus", len(sb), "metro", len(sm))
    print("bus node_id unique:", sb["node_id"].is_unique, "null coords:", int(sb[["lng", "lat"]].isna().sum().sum()))
    print("metro node_id unique:", sm["node_id"].is_unique)
    print("bus in_boundary:", int(sb["in_boundary"].sum()), "metro in_boundary: n/a")

    show("edges")
    eb = pd.read_csv(V1 / "edges_bus.csv")
    em = pd.read_csv(V1 / "edges_metro.csv")
    bus_keys = set(sb["node_id"])
    met_keys = set(sm["node_id"])
    print("bus edges", len(eb), "unknown from/to:",
          int((~eb["from_node"].isin(bus_keys)).sum()), int((~eb["to_node"].isin(bus_keys)).sum()))
    print("metro edges", len(em), "unknown from/to:",
          int((~em["from_node"].isin(met_keys)).sum()), int((~em["to_node"].isin(met_keys)).sum()))
    # every edge endpoint must exist; every bus stop should be used at least once
    used = set(eb["from_node"]) | set(eb["to_node"])
    print("bus stops never used by an edge:", len(bus_keys - used))
    print("edge_id unique:", eb["edge_id"].is_unique, em["edge_id"].is_unique)

    show("walk roads")
    wr = gpd.read_file(V1 / "osm_walk_roads.gpkg", layer="walk_roads")
    print("crs", wr.crs, "segments", len(wr), "km", round(wr["length_m"].sum() / 1000, 1))
    print("invalid geoms:", int((~wr.is_valid).sum()), "null len:", int(wr["length_m"].isna().sum()))
    print("in_boundary:", int(wr["in_boundary"].sum()), "/", len(wr))
    print(wr["walk_group"].value_counts().to_dict())
    print("fclass top:", wr["fclass"].value_counts().head(8).to_dict())

    show("poi")
    poi = gpd.read_file(V1 / "poi.gpkg", layer="poi_points")
    print("crs", poi.crs, "features", len(poi))
    print("in boundary", int(poi["in_boundary"].sum()))
    print("geom kinds:", poi["geom_kind"].value_counts().to_dict())
    print("poi_areas layer:", len(gpd.read_file(V1 / "poi.gpkg", layer="poi_areas")))
    inner = poi[poi["in_boundary"]]
    print("categories:", inner["category"].value_counts().to_dict())

    show("metro schedule")
    sc = pd.read_csv(V1 / "metro_schedule.csv")
    print("rows", len(sc), "intervals", sorted(sc["interval_seconds"].unique().tolist()))

    show("coordinate sanity")
    print("bus lng range", round(float(sb["lng"].min()), 3), round(float(sb["lng"].max()), 3))
    print("bus lat range", round(float(sb["lat"].min()), 3), round(float(sb["lat"].max()), 3))
    print("metro lng range", round(float(sm["lng"].min()), 3), round(float(sm["lng"].max()), 3))

    show("walk connectivity")
    # consecutive-vertex union-find: how much of the network is one component
    import numpy as np
    import shapely

    geoms = wr.geometry.to_numpy()
    coords = shapely.get_coordinates(geoms)
    keys = np.round(coords, 6)
    uk, inv = np.unique(keys, axis=0, return_inverse=True)
    n = len(uk)
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    per_geom = np.array([len(shapely.get_coordinates(g)) for g in geoms])
    starts = np.concatenate([[0], np.cumsum(per_geom)[:-1]])
    for s, c in zip(starts, per_geom):
        for i in range(c - 1):
            ra, rb = find(inv[s + i]), find(inv[s + i + 1])
            if ra != rb:
                parent[rb] = ra
    roots = np.array([find(i) for i in range(n)])
    _, counts = np.unique(roots, return_counts=True)
    biggest = counts.max()
    print(f"nodes {n}, components {len(counts)}, largest {biggest} "
          f"({100 * biggest / n:.1f}% of vertices)")

    print("\nALL CHECKS RAN")


if __name__ == "__main__":
    main()
