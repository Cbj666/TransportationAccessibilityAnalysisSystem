# -*- coding: utf-8 -*-
"""Multimodal graph: walking network + bus + metro, as a scipy sparse CSR matrix.

Node kinds
    0  walking-network vertex
    1  bus stop (street level, boarding point)
    2  metro station (street level, boarding point)
    3  bus platform (one per line-direction-stop)
    4  metro platform

Edge semantics (all weights in seconds, all edges directed)
    walk vertex  <-> walk vertex     length / walk_speed
    walk vertex  <-> stop            access distance / walk_speed
    stop          -> platform        wait time (headway/2)
    platform(a)   -> platform(b)     ride time (dist_route / speed + dwell)
    platform      -> stop            0

Splitting stops from platforms makes transfer cost emerge naturally: alighting
is free, boarding again costs another wait, and walking between two stops
happens on the real street network.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree

from .config import DEFAULT, Params
from .paths import GRAPH_CACHE as CACHE
from .paths import V1

WALK, BUS_STOP, METRO_STOP, BUS_PLATFORM, METRO_PLATFORM = 0, 1, 2, 3, 4
KIND_NAMES = {
    WALK: "walk",
    BUS_STOP: "bus_stop",
    METRO_STOP: "metro_stop",
    BUS_PLATFORM: "bus_platform",
    METRO_PLATFORM: "metro_platform",
}


@dataclass
class Graph:
    csr: csr_matrix
    kind: np.ndarray          # int8, shape (n,)
    x: np.ndarray             # UTM 50N easting, metres
    y: np.ndarray             # UTM 50N northing, metres
    lng: np.ndarray
    lat: np.ndarray
    named_idx: np.ndarray     # int32 indices of nodes that carry an id (stops/platforms)
    named_id: np.ndarray      # unicode ids
    named_name: np.ndarray    # unicode names
    walk_comp_size: np.ndarray  # int32, size of the walk component each vertex belongs to
    n_walk: int
    params: Params
    stats: dict
    _kd: object | None = None

    def kdtree(self):
        """KD-tree over the major walk component (cached)."""
        if self._kd is None:
            from scipy.spatial import cKDTree

            major = self.walk_comp_size[: self.n_walk] >= max(1000, 0.01 * self.n_walk)
            self._major_index = np.flatnonzero(major)
            self._kd = cKDTree(
                np.column_stack(
                    [self.x[self._major_index], self.y[self._major_index]]
                )
            )
        return self._kd

    @property
    def n_nodes(self) -> int:
        return int(self.kind.shape[0])

    def id_to_index(self) -> dict[str, int]:
        return dict(zip(self.named_id.tolist(), self.named_idx.tolist()))

    def nodes_of_kind(self, kind: int) -> np.ndarray:
        return np.flatnonzero(self.kind == kind)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            data=self.csr.data.astype(np.float32),
            indices=self.csr.indices.astype(np.int32),
            indptr=self.csr.indptr.astype(np.int32),
            kind=self.kind,
            x=self.x,
            y=self.y,
            lng=self.lng,
            lat=self.lat,
            named_idx=self.named_idx,
            named_id=self.named_id,
            named_name=self.named_name,
            walk_comp_size=self.walk_comp_size,
            n_walk=np.array([self.n_walk]),
        )
        path.with_suffix(".meta.pkl").write_bytes(
            pickle.dumps({"params": self.params, "stats": self.stats})
        )

    @classmethod
    def load(cls, path: Path) -> "Graph":
        z = np.load(path, allow_pickle=False)
        n = z["indptr"].shape[0] - 1
        csr = csr_matrix((z["data"], z["indices"], z["indptr"]), shape=(n, n))
        meta = pickle.loads(Path(path).with_suffix(".meta.pkl").read_bytes())
        return cls(
            csr=csr,
            kind=z["kind"],
            x=z["x"],
            y=z["y"],
            lng=z["lng"],
            lat=z["lat"],
            named_idx=z["named_idx"],
            named_id=z["named_id"],
            named_name=z["named_name"],
            walk_comp_size=z["walk_comp_size"],
            n_walk=int(z["n_walk"][0]),
            params=meta["params"],
            stats=meta["stats"],
        )


# --------------------------------------------------------------------- helpers
def _utm(lng: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    x, y = tr.transform(np.asarray(lng, float), np.asarray(lat, float))
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def _read_walk_network():
    """Unique vertices, segment endpoints, segment lengths (metres), metric coords."""
    gdf = pyogrio.read_dataframe(V1 / "osm_walk_roads.gpkg", layer="walk_roads")
    geoms = gdf.geometry.to_numpy()
    counts = shapely.get_num_coordinates(geoms)
    coords = shapely.get_coordinates(geoms)
    uk, inv = np.unique(np.round(coords, 6), axis=0, return_inverse=True)

    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    a, b = inv[:-1], inv[1:]
    keep = np.ones(len(a), dtype=bool)
    keep[starts[1:] - 1] = False          # do not join the end of one way to the next
    a, b = a[keep], b[keep]

    x, y = _utm(uk[:, 0], uk[:, 1])
    seg_len = np.hypot(x[b] - x[a], y[b] - y[a])
    ok = (seg_len > 0.01) & (a != b)
    return uk, a[ok], b[ok], seg_len[ok], x, y


def metro_wait_by_line() -> dict[str, float]:
    sched = pd.read_csv(V1 / "metro_schedule.csv")
    out: dict[str, float] = {}
    for lid, grp in sched[sched["day_type"] == "weekday"].groupby("line_id"):
        out[str(lid)] = max(90.0, float(grp["interval_seconds"].min()) / 2.0)
    return out


# ----------------------------------------------------------------------- build
def build(params: Params = DEFAULT, verbose: bool = True) -> Graph:
    def say(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    say("[graph] reading walk network ...")
    uk, seg_a, seg_b, seg_len, wx, wy = _read_walk_network()
    n_walk = len(uk)
    say(f"[graph] walk nodes {n_walk:,}, segments {len(seg_a):,}")

    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    vals: list[np.ndarray] = []

    # --- walking -----------------------------------------------------------
    w = seg_len / params.walk_speed_mps
    rows += [seg_a, seg_b]
    cols += [seg_b, seg_a]
    vals += [w, w]

    # --- walk connectivity -------------------------------------------------
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    w_csr = coo_matrix(
        (np.ones(len(seg_a), dtype=np.int8), (seg_a, seg_b)), shape=(n_walk, n_walk)
    ).tocsr()
    ncomp, labels = connected_components(w_csr, directed=False)
    sizes = np.bincount(labels)
    walk_comp = sizes[labels].astype(np.int32)
    big_index = np.flatnonzero(walk_comp == walk_comp.max())
    del w_csr
    say(
        f"[graph] walk components {ncomp:,}, largest {int(walk_comp.max()):,} vertices "
        f"({100 * walk_comp.max() / n_walk:.1f}%)"
    )

    # --- stops -------------------------------------------------------------
    bus = pd.read_csv(V1 / "stops_bus.csv")
    metro = pd.read_csv(V1 / "stops_metro.csv")
    n_bus, n_metro = len(bus), len(metro)
    bus0 = n_walk
    metro0 = n_walk + n_bus
    next_node = metro0 + n_metro

    stop_index: dict[str, int] = {}
    stop_index.update({nid: bus0 + i for i, nid in enumerate(bus["node_id"])})
    stop_index.update({nid: metro0 + i for i, nid in enumerate(metro["node_id"])})

    named_idx: list[int] = list(range(bus0, metro0)) + list(range(metro0, next_node))
    named_id: list[str] = list(bus["node_id"]) + list(metro["node_id"])
    named_name: list[str] = list(bus["name"].astype(str)) + list(metro["name"].astype(str))

    say("[graph] snapping stops to the walk network ...")
    tree = cKDTree(np.column_stack([wx[big_index], wy[big_index]]))
    tree_all = cKDTree(np.column_stack([wx, wy]))
    b_lng = bus["snap_lng"].fillna(bus["lng"]).to_numpy()
    b_lat = bus["snap_lat"].fillna(bus["lat"]).to_numpy()
    m_lng = metro["snap_lng"].fillna(metro["lng"]).to_numpy()
    m_lat = metro["snap_lat"].fillna(metro["lat"]).to_numpy()
    all_lng = np.concatenate([b_lng, m_lng])
    all_lat = np.concatenate([b_lat, m_lat])
    sx, sy = _utm(all_lng, all_lat)
    q = np.column_stack([sx, sy])
    acc_d, acc_i = (np.asarray(v) for v in tree.query(q, k=1))
    if tree_all is not None:
        acc_i = big_index[acc_i]
        # stops that sit on a walk fragment: fall back to the nearest vertex anywhere
        far = acc_d > 400.0
        if far.any():
            d2, i2 = (np.asarray(v) for v in tree_all.query(q[far], k=1))
            acc_d[far] = d2
            acc_i[far] = i2
    stop_nodes = np.arange(bus0, next_node)
    ok = acc_d <= params.walk_access_max_m
    acc_w = acc_d[ok] / params.walk_speed_mps
    rows += [stop_nodes[ok], acc_i[ok]]
    cols += [acc_i[ok], stop_nodes[ok]]
    vals += [acc_w, acc_w]
    say(
        f"[graph] access edges {int(ok.sum())}/{len(ok)} "
        f"(median {np.median(acc_d):.1f} m, max {acc_d.max():.1f} m"
        f"{', dropped ' + str(int((~ok).sum())) if (~ok).any() else ''})"
    )

    # --- platforms + ride edges -------------------------------------------
    say("[graph] expanding routes into platforms ...")
    bus_rs = pd.read_csv(V1 / "bus_route_stops.csv")
    bus_ed = pd.read_csv(V1 / "edges_bus.csv")
    met_rs = pd.read_csv(V1 / "metro_route_stops.csv")
    met_ed = pd.read_csv(V1 / "edges_metro.csv")

    platform_rows: list[int] = []
    platform_ids: list[str] = []
    platform_names: list[str] = []
    platform_lng: list[float] = []
    platform_lat: list[float] = []
    metro_platform_rows: list[int] = []

    def add_routes(
        rs: pd.DataFrame,
        ed: pd.DataFrame,
        mode: str,
        kind_code: int,
        wait: float | dict[str, float],
        metro_flag: bool,
    ) -> tuple[int, float, float]:
        nonlocal next_node
        ride = {
            (str(r.line_id), int(r.from_sequence), int(r.to_sequence)): (
                float(r.dist_route_m)
                if np.isfinite(r.dist_route_m)
                else float(r.distance_m) * 1.2
            )
            for r in ed.itertuples()
        }
        n_plat = 0
        sum_wait = 0.0
        sum_ride = 0.0
        for lid, grp in rs.groupby("line_id"):
            grp = grp.sort_values("sequence")
            w_line = (
                wait if isinstance(wait, float)
                else wait.get(str(lid), params.metro_wait_fallback_s)
            )
            nodes: list[int] = []
            seqs = grp["sequence"].to_numpy()
            node_ids = grp["node_id"].tolist()
            names = grp["station_name"].astype(str).tolist()
            lngs = grp["lng_wgs84"].to_numpy()
            lats = grp["lat_wgs84"].to_numpy()
            for seq, node_id, name, plng, plat in zip(seqs, node_ids, names, lngs, lats):
                p = next_node
                next_node += 1
                platform_rows.append(p)
                platform_ids.append(f"P-{mode}-{lid}-{seq}")
                platform_names.append(name)
                platform_lng.append(float(plng))
                platform_lat.append(float(plat))
                nodes.append(p)
                n_plat += 1
                stop = stop_index.get(node_id)
                if stop is not None:
                    rows.append(np.array([stop]))
                    cols.append(np.array([p]))
                    vals.append(np.array([w_line]))
                    rows.append(np.array([p]))
                    cols.append(np.array([stop]))
                    vals.append(np.array([0.0]))
                    sum_wait += w_line
                if metro_flag:
                    metro_platform_rows.append(p)
            for k in range(1, len(nodes)):
                d = ride.get((str(lid), int(seqs[k - 1]), int(seqs[k])))
                if d is None:
                    continue
                t = params.ride_time(mode, d)
                rows.append(np.array([nodes[k - 1]]))
                cols.append(np.array([nodes[k]]))
                vals.append(np.array([t]))
                sum_ride += t
        return n_plat, sum_wait, sum_ride

    p_bus, w_bus, r_bus = add_routes(
        bus_rs, bus_ed, "bus", BUS_PLATFORM, params.bus_wait_s, False
    )
    say(f"[graph] bus platforms {p_bus:,}")
    m_wait = metro_wait_by_line()
    p_met, w_met, r_met = add_routes(
        met_rs, met_ed, "metro", METRO_PLATFORM, m_wait, True
    )
    say(f"[graph] metro platforms {p_met:,} (wait {min(m_wait.values()):.0f}–{max(m_wait.values()):.0f} s)")

    n_nodes = next_node
    row = np.concatenate(rows)
    col = np.concatenate(cols)
    val = np.concatenate(vals).astype(np.float32)
    csr = csr_matrix((val, (row, col)), shape=(n_nodes, n_nodes))

    kind = np.zeros(n_nodes, dtype=np.int8)
    kind[bus0:metro0] = BUS_STOP
    kind[metro0:metro0 + n_metro] = METRO_STOP
    kind[np.asarray(platform_rows, dtype=np.int64)] = BUS_PLATFORM
    kind[np.asarray(metro_platform_rows, dtype=np.int64)] = METRO_PLATFORM

    plng = np.asarray(platform_lng, dtype=np.float64)
    plat = np.asarray(platform_lat, dtype=np.float64)
    px, py = _utm(plng, plat)

    lng = np.concatenate([uk[:, 0], all_lng, plng])
    lat = np.concatenate([uk[:, 1], all_lat, plat])
    x = np.concatenate([wx, sx, px])
    y = np.concatenate([wy, sy, py])

    named_idx_arr = np.asarray(named_idx + platform_rows, dtype=np.int64)
    named_id_arr = np.asarray(named_id + platform_ids, dtype="U48")
    named_name_arr = np.asarray(named_name + platform_names, dtype="U48")

    walk_comp_size = np.zeros(n_nodes, dtype=np.int32)
    walk_comp_size[:n_walk] = walk_comp

    stats = {
        "n_nodes": int(n_nodes),
        "n_walk_nodes": int(n_walk),
        "n_bus_stops": int(n_bus),
        "n_metro_stops": int(n_metro),
        "n_platforms": int(p_bus + p_met),
        "n_edges": int(csr.nnz),
        "n_directed_walk": int(2 * len(seg_a)),
        "access_median_m": round(float(np.median(acc_d)), 2),
        "access_max_m": round(float(acc_d.max()), 2),
        "access_dropped": int((~ok).sum()),
        "walk_components": int(ncomp),
        "walk_largest_component": int(walk_comp.max()),
    }
    say(f"[graph] done: {stats}")

    return Graph(
        csr=csr,
        kind=kind,
        x=x,
        y=y,
        lng=lng,
        lat=lat,
        named_idx=named_idx_arr,
        named_id=named_id_arr,
        named_name=named_name_arr,
        walk_comp_size=walk_comp_size,
        n_walk=n_walk,
        params=params,
        stats=stats,
    )


def load_or_build(cache: bool = True, params: Params = DEFAULT, verbose: bool = True) -> Graph:
    path = CACHE / "v1" / "multimodal.npz"
    if cache and path.exists():
        if verbose:
            print(f"[graph] loading cache {path}", flush=True)
        return Graph.load(path)
    g = build(params=params, verbose=verbose)
    if cache:
        g.save(path)
        if verbose:
            print(f"[graph] cached -> {path}", flush=True)
    return g
