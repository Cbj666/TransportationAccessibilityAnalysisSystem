# -*- coding: utf-8 -*-
"""Isochrone computation on the multimodal graph.

One Dijkstra run from the origin gives the travel time to every node. A
continuous travel-time surface is then built from those node times, and the
15/30/45-minute areas are its level sets.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from .graph import (
    BUS_PLATFORM,
    BUS_STOP,
    KIND_NAMES,
    METRO_PLATFORM,
    METRO_STOP,
    WALK,
    Graph,
)
from .paths import V1


def nearest_walk_node(graph: Graph, lng: float, lat: float) -> tuple[int, float]:
    """Snap a coordinate to the closest vertex of the major walk component."""
    tree = graph.kdtree()
    x, y = _to_utm(lng, lat)
    d, i = tree.query([x, y], k=1)
    return int(graph._major_index[int(i)]), float(d)


def _to_utm(lng: float, lat: float) -> tuple[float, float]:
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    x, y = tr.transform(lng, lat)
    return float(x), float(y)


def travel_times(
    graph: Graph, origin: int, predecessors: bool = False
) -> tuple[np.ndarray, np.ndarray | None]:
    """Seconds from `origin` to every node (inf where unreachable)."""
    if predecessors:
        dist, pred = dijkstra(
            graph.csr, directed=True, indices=origin, return_predecessors=True
        )
        return np.asarray(dist, dtype=np.float64), pred
    dist = dijkstra(graph.csr, directed=True, indices=origin)
    return np.asarray(dist, dtype=np.float64), None


def time_surface(
    graph: Graph,
    dist: np.ndarray,
    bbox: tuple[float, float, float, float],
    res_m: float = 150.0,
    k: int = 8,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Travel-time surface over a regular grid.

    ``Z = min_n (t_n + |p - n| / walk_speed)`` — the reachable time at any map
    point, using the k nearest reachable network vertices. This is the standard
    way to turn a node-level shortest-path result into a continuous surface
    (a plain hull of reachable nodes produces spidery, angular shapes).

    Returns (X, Y, Z) with Z in seconds; unreachable cells are +inf.
    """
    finite = np.isfinite(dist)
    anchors = np.flatnonzero(finite)
    if anchors.size == 0:
        raise ValueError("no reachable nodes")
    tree = cKDTree(np.column_stack([graph.x[anchors], graph.y[anchors]]))
    xs = np.arange(bbox[0], bbox[2] + res_m, res_m)
    ys = np.arange(bbox[1], bbox[3] + res_m, res_m)
    X, Y = np.meshgrid(xs, ys)
    pts = np.column_stack([X.ravel(), Y.ravel()])
    d, idx = tree.query(pts, k=min(k, anchors.size))
    t = dist[anchors][idx] + d / graph.params.walk_speed_mps
    if t.ndim == 1:
        t = t[:, None]
    Z = t.min(axis=1).reshape(X.shape)
    return X, Y, Z


def surface_polygons(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    levels: list[float],
    boundary=None,
    smooth_m: float = 120.0,
    min_component_m2: float = 200_000.0,
) -> dict[float, shapely.Geometry]:
    """Turn the time surface into nested polygons (one per level).

    Cells whose surface time is below the level are merged into a single
    polygon, smoothed with a matching buffer-out/buffer-in, and tiny detached
    fragments (< 0.2 km²) are dropped. Nesting is enforced by unioning each
    smaller level into the next.
    """
    dx = float(X[0, 1] - X[0, 0])
    dy = float(Y[1, 0] - Y[0, 0])
    out: dict[float, shapely.Geometry] = {}
    prev = None
    for level in sorted(levels):
        mask = Z <= level
        if not mask.any():
            out[level] = shapely.Polygon()
            continue
        jj, ii = np.nonzero(mask)
        cx, cy = X[ii, jj], Y[ii, jj]
        boxes = shapely.box(cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2)
        geom = shapely.union_all(boxes)
        parts = [
            p for p in getattr(geom, "geoms", [geom]) if p.area >= min_component_m2
        ]
        geom = shapely.union_all(parts) if parts else shapely.Polygon()
        if not geom.is_empty:
            geom = geom.buffer(smooth_m, join_style="round").buffer(
                -smooth_m, join_style="round"
            )
        if prev is not None and not geom.is_empty:
            geom = geom.union(prev)
        if boundary is not None and not geom.is_empty:
            geom = geom.intersection(boundary)
        out[level] = geom
        prev = geom
    return out


def reachable_stops(
    graph: Graph, dist: np.ndarray, budget_s: float
) -> dict[str, np.ndarray]:
    return {
        "bus": np.flatnonzero((graph.kind == BUS_STOP) & (dist <= budget_s)),
        "metro": np.flatnonzero((graph.kind == METRO_STOP) & (dist <= budget_s)),
    }


def poi_stats(poly: shapely.Geometry, poi=None) -> dict:
    """Count OSM POIs inside a polygon, by category (UTM, polygon already metric)."""
    if poi is None:
        poi = gpd.read_file(V1 / "poi.gpkg", layer="poi_points")
    px, py = _to_utm_array(poi.geometry.x.to_numpy(), poi.geometry.y.to_numpy())
    inside = shapely.contains_xy(poly, px, py)
    sub = poi[inside]
    counts = sub["category"].value_counts().to_dict()
    return {"total": int(len(sub)), "by_category": {k: int(v) for k, v in counts.items()}}


def _to_utm_array(lng: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    x, y = tr.transform(lng, lat)
    return np.asarray(x), np.asarray(y)


def explain_path(
    graph: Graph, origin: int, target: int, pred: np.ndarray, id_map: dict | None = None
) -> list[dict]:
    """Decompose the shortest path into legs with mode and seconds."""
    path = [target]
    cur = target
    while cur != origin and cur >= 0:
        cur = int(pred[cur])
        if cur < 0:
            return []
        path.append(cur)
    path.reverse()
    if id_map is None:
        id_map = dict(zip(graph.named_idx.tolist(), graph.named_id.tolist()))

    def label(i: int) -> str:
        return id_map.get(i, f"walk:{i}" if i < graph.n_walk else f"node:{i}")

    legs: list[dict] = []
    for a, b in zip(path[:-1], path[1:]):
        sec = float(graph.csr[a, b])
        ka, kb = int(graph.kind[a]), int(graph.kind[b])
        if ka == WALK and kb == WALK:
            mode = "步行"
        elif ka in (BUS_STOP, METRO_STOP) and kb in (BUS_PLATFORM, METRO_PLATFORM):
            mode = "候车"
        elif ka in (BUS_PLATFORM, METRO_PLATFORM) and kb in (BUS_PLATFORM, METRO_PLATFORM):
            mode = "公交乘车" if ka == BUS_PLATFORM else "地铁乘车"
        elif ka in (BUS_PLATFORM, METRO_PLATFORM) and kb in (BUS_STOP, METRO_STOP):
            mode = "下车"
        elif ka == WALK and kb in (BUS_STOP, METRO_STOP):
            mode = "接驳步行"
        elif ka in (BUS_STOP, METRO_STOP) and kb == WALK:
            mode = "接驳步行"
        else:
            mode = f"{KIND_NAMES.get(ka, ka)}->{KIND_NAMES.get(kb, kb)}"
        legs.append({"mode": mode, "seconds": round(sec, 1), "from": label(a), "to": label(b)})

    merged: list[dict] = []
    for leg in legs:
        if merged and merged[-1]["mode"] == leg["mode"]:
            merged[-1]["seconds"] = round(merged[-1]["seconds"] + leg["seconds"], 1)
            merged[-1]["to"] = leg["to"]
        else:
            merged.append(dict(leg))
    return merged
