# -*- coding: utf-8 -*-
r"""Freeze the validated inputs into a versioned dataset for development.

Inputs  (read-only, never modified)
    data/interim/**                      Amap bus + metro tables (591 lines / 9 metro lines)
    data/raw/boundary/武汉市_市.geojson    Wuhan admin boundary (EPSG:4490)
    data/raw/hubei/hubei-261013-free-OpenMap/hubei.gpkg
                                         OSM Hubei extract (roads, POIs)

Outputs data/processed/v1/   (the directory is WIPED and regenerated every run)
    wuhan_boundary.geojson
    stops_bus.csv / stops_metro.csv
    edges_bus.csv  / edges_metro.csv
    routes_bus.geojson / routes_metro.geojson
    metro_schedule.csv
    bus_route_stops.csv / metro_route_stops.csv
    osm_walk_roads.gpkg      (layer walk_roads)
    poi.gpkg                 (layer poi_points / poi_areas)
    manifest.json

The field-level documentation lives in docs/数据字典-v1.md — deliberately outside
this directory so that a rebuild does not delete it.

Run:  .\.venv\Scripts\python.exe backend\scripts\prepare_dataset.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

VERSION = "v1"
ROOT = Path(__file__).resolve().parents[2]  # project root
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
INTERIM = ROOT / "data" / "interim"
METRO = INTERIM / "amap_metro"
GPKG = OSM_GPKG
OUT = ROOT / "data" / "processed" / VERSION

CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:32650"  # UTM 50N, covers Wuhan
ROAD_BUFFER_M = 2000.0     # keep roads just outside the boundary to preserve connectivity

# Roads that pedestrians may use. Motorways / construction are excluded.
WALKABLE = {
    "footway", "path", "pedestrian", "steps", "living_street", "residential",
    "service", "unclassified", "tertiary", "tertiary_link", "secondary",
    "secondary_link", "primary", "primary_link", "trunk", "trunk_link",
    "cycleway", "track", "track_grade1", "track_grade2", "track_grade3",
    "track_grade4", "track_grade5", "bridleway", "road",
}
FOOT_ONLY = {"footway", "path", "pedestrian", "steps"}
MOTORWAY = {"motorway", "motorway_link"}

# data/interim/amap_bus_route_stops.csv and the raw JSON both label 27 rows with
# a duplicated "路" suffix (e.g. "C1路路"); the label is only a join key.
POI_CATEGORY = {
    # 餐饮
    "restaurant": "餐饮", "fast_food": "餐饮", "cafe": "餐饮", "bar": "餐饮",
    "pub": "餐饮", "food_court": "餐饮", "ice_cream": "餐饮", "biergarten": "餐饮",
    # 购物
    "supermarket": "购物", "convenience": "购物", "clothes": "购物",
    "mall": "购物", "department_store": "购物", "marketplace": "购物",
    "bakery": "购物", "butcher": "购物", "florist": "购物", "furniture": "购物",
    "electronics": "购物", "hardware": "购物", "jewelry": "购物", "shoes": "购物",
    "sports_shop": "购物", "gift": "购物", "stationery": "购物", "toys": "购物",
    "bookshop": "购物", "chemist": "购物", "greengrocer": "购物", "optician": "购物",
    "pet": "购物", "photo": "购物", "tobacco": "购物", "variety_store": "购物",
    "alcohol": "购物", "beverages": "购物", "bicycle_shop": "购物",
    "car_dealer": "购物", "car_repair": "购物", "car_parts": "购物",
    "car_wash": "购物", "dry_cleaning": "购物", "garden_centre": "购物",
    "laundry": "购物", "mobile_phone": "购物", "motorcycle": "购物",
    "outdoor": "购物", "seafood": "购物", "tea": "购物", "video": "购物",
    "watches": "购物", "kiosk": "购物", "general": "购物", "hairdresser": "购物",
    # 教育
    "school": "教育", "university": "教育", "college": "教育",
    "kindergarten": "教育", "library": "教育", "driving_school": "教育",
    "language_school": "教育", "music_school": "教育", "research": "教育",
    # 医疗
    "hospital": "医疗", "clinic": "医疗", "doctors": "医疗", "dentist": "医疗",
    "pharmacy": "医疗", "veterinary": "医疗", "nursing_home": "医疗",
    "health_centre": "医疗",
    # 金融
    "bank": "金融", "atm": "金融", "bureau_de_change": "金融",
    "insurance": "金融", "financial": "金融",
    # 政府/公共
    "town_hall": "政府公共", "post_office": "政府公共", "police": "政府公共",
    "fire_station": "政府公共", "courthouse": "政府公共",
    "embassy": "政府公共", "government": "政府公共",
    "public_building": "政府公共", "prison": "政府公共",
    "ranger_station": "政府公共", "administrative": "政府公共",
    "shelter": "政府公共", "toilet": "政府公共",
    # 休闲旅游
    "park": "休闲旅游", "attraction": "休闲旅游", "museum": "休闲旅游",
    "artwork": "休闲旅游", "memorial": "休闲旅游", "monument": "休闲旅游",
    "viewpoint": "休闲旅游", "zoo": "休闲旅游", "theme_park": "休闲旅游",
    "picnic_site": "休闲旅游", "garden": "休闲旅游", "playground": "休闲旅游",
    "sports_centre": "休闲旅游", "stadium": "休闲旅游", "pitch": "休闲旅游",
    "track": "休闲旅游", "sports_hall": "休闲旅游",
    "swimming_pool": "休闲旅游", "theatre": "休闲旅游", "cinema": "休闲旅游",
    "nightclub": "休闲旅游", "casino": "休闲旅游", "arts_centre": "休闲旅游",
    "gallery": "休闲旅游", "tower": "休闲旅游", "water_park": "休闲旅游",
    # 交通设施
    "bus_stop": "交通设施", "bus_station": "交通设施",
    "railway_station": "交通设施", "tram_stop": "交通设施",
    "ferry_terminal": "交通设施", "taxi": "交通设施", "parking": "交通设施",
    "fuel": "交通设施", "charging_station": "交通设施",
    "bicycle_parking": "交通设施", "car_sharing": "交通设施",
    "halt": "交通设施", "level_crossing": "交通设施",
    # 住宿
    "hotel": "住宿", "hostel": "住宿", "guest_house": "住宿", "motel": "住宿",
    "alpine_hut": "住宿", "chalet": "住宿",
    # 宗教
    "buddhist": "宗教", "christian": "宗教", "muslim": "宗教",
    "taoist": "宗教", "jewish": "宗教", "hindu": "宗教", "sikh": "宗教",
    "shrine": "宗教", "christian_catholic": "宗教",
    "christian_protestant": "宗教", "christian_methodist": "宗教",
    "religion": "宗教",
    # 自然
    "peak": "自然", "spring": "自然", "cave_entrance": "自然",
    "wood": "自然", "water": "自然", "beach": "自然", "forest": "自然",
}
POI_LABELS = ["餐饮", "购物", "教育", "医疗", "金融", "政府公共", "休闲旅游", "交通设施", "住宿", "宗教", "自然", "其他"]


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


# --------------------------------------------------------------------- boundary
def prep_boundary():
    g = gpd.read_file(BOUNDARY).to_crs(CRS_WGS84)
    g["area_km2"] = g.to_crs(CRS_METRIC).area / 1e6
    cols = [c for c in ["name", "area_km2"] if c in g.columns] + ["geometry"]
    g = g[cols]
    out = OUT / "wuhan_boundary.geojson"
    g.to_file(out, driver="GeoJSON")
    log(f"[boundary] {len(g)} polygon(s), {g['area_km2'].sum():.1f} km2 -> {out.name}")
    return g


# ------------------------------------------------------------------- transit
def prep_bus(boundary_geom):
    st = pd.read_csv(INTERIM / "amap_bus_stations_snapped.csv")
    st = st.rename(
        columns={
            "station_key": "station_key",
            "station_name": "name",
            "lng_wgs84": "lng",
            "lat_wgs84": "lat",
        }
    )
    st.insert(0, "node_id", "B-" + st["station_key"].astype(str))
    # pragmatic in-boundary test against the admin polygon
    pts = gpd.GeoSeries(
        shapely.points(st["lng"].to_numpy(), st["lat"].to_numpy()), crs=CRS_WGS84
    )
    st["in_boundary"] = pts.within(boundary_geom)
    st = st[
        [
            "node_id", "station_key", "station_id", "name", "lng", "lat",
            "snap_lng", "snap_lat", "snap_distance_m", "snap_quality",
            "road_fclass", "road_name", "line_count", "record_count",
            "inside_wuhan", "in_boundary", "flags",
        ]
    ]
    st.to_csv(OUT / "stops_bus.csv", index=False)
    log(f"[bus] stops {len(st)} (in boundary {int(st['in_boundary'].sum())})")

    ed = pd.read_csv(INTERIM / "amap_bus_edges.csv")
    ed.insert(0, "edge_id", "E-BUS-" + (ed.index + 1).astype(str).str.zfill(6))
    ed["mode"] = "bus"
    ed["from_node"] = "B-" + ed["from_station_key"].astype(str)
    ed["to_node"] = "B-" + ed["to_station_key"].astype(str)
    for c in ["leg_gt_3000m", "leg_gt_5000m", "leg_gt_10000m"]:
        ed[c] = ed[c].astype(bool)

    rs = pd.read_csv(INTERIM / "amap_bus_route_stops.csv")
    rs.insert(0, "node_id", "B-" + rs["station_key"].astype(str))

    sh = gpd.read_file(INTERIM / "amap_bus_routes.geojson").to_crs(CRS_WGS84)

    ed = annotate_along_distance(ed, rs, sh, "bus")
    ed.to_csv(OUT / "edges_bus.csv", index=False)
    log(f"[bus] edges {len(ed)} across {ed['line_id'].nunique()} directions")
    log("[bus] route distance source: " + ed["dist_source"].value_counts().to_dict().__str__())
    log(f"[bus] detour ratio median {ed.loc[ed['dist_source'] == 'shape', 'detour_ratio'].median():.3f}")

    rs.to_csv(OUT / "bus_route_stops.csv", index=False)
    sh.to_file(OUT / "routes_bus.geojson", driver="GeoJSON")
    log(f"[bus] route shapes {len(sh)}")


def prep_metro():
    st = pd.read_csv(METRO / "metro_stations_snapped.csv")
    st = st.rename(columns={"station_name": "name", "lng_wgs84": "lng", "lat_wgs84": "lat"})
    st.insert(0, "node_id", "M-" + st["station_id"].astype(str))
    st = st[
        [
            "node_id", "station_id", "name", "lng", "lat", "snap_lng", "snap_lat",
            "snap_distance_m", "snap_quality", "road_fclass", "road_name",
            "line_count", "record_count",
        ]
    ]
    st.to_csv(OUT / "stops_metro.csv", index=False)
    log(f"[metro] stations {len(st)}")

    ed = pd.read_csv(METRO / "metro_edges.csv")
    ed.insert(0, "edge_id", "E-MET-" + (ed.index + 1).astype(str).str.zfill(5))
    ed["mode"] = "metro"
    ed["from_node"] = "M-" + ed["from_station_id"].astype(str)
    ed["to_node"] = "M-" + ed["to_station_id"].astype(str)

    rs = pd.read_csv(METRO / "metro_route_stops.csv")
    rs.insert(0, "node_id", "M-" + rs["station_id"].astype(str))

    sh = gpd.read_file(METRO / "metro_routes.geojson").to_crs(CRS_WGS84)

    ed = annotate_along_distance(ed, rs, sh, "metro")
    ed.to_csv(OUT / "edges_metro.csv", index=False)
    log(f"[metro] edges {len(ed)} across {ed['line_id'].nunique()} directions")
    log("[metro] route distance source: " + ed["dist_source"].value_counts().to_dict().__str__())
    log(f"[metro] detour ratio median {ed.loc[ed['dist_source'] == 'shape', 'detour_ratio'].median():.3f}")

    rs.to_csv(OUT / "metro_route_stops.csv", index=False)

    sc = pd.read_csv(METRO / "metro_schedule.csv")
    sc.to_csv(OUT / "metro_schedule.csv", index=False)
    log(f"[metro] schedule rows {len(sc)}")

    sh.to_file(OUT / "routes_metro.geojson", driver="GeoJSON")
    log(f"[metro] route shapes {len(sh)}")


# ----------------------------------------------------------------- walk roads
def prep_walk_roads(boundary_geom):
    boundary_buf = boundary_geom.buffer(ROAD_BUFFER_M / 111_320.0)
    bb = tuple(boundary_buf.bounds)
    rd = pyogrio.read_dataframe(GPKG, layer="gis_osm_roads_free", bbox=bb)
    rd = rd[rd.geometry.notna() & ~rd.geometry.is_empty].copy()
    rd = rd[rd["fclass"].isin(WALKABLE)]
    rd["walk_group"] = rd["fclass"].map(lambda f: "foot" if f in FOOT_ONLY else "street")
    rd["oneway_walk"] = rd["oneway"].map({"B": "both", "F": "forward", "T": "reverse"}).fillna("both")
    rd["bridge"] = rd["bridge"].fillna("F").ne("F")
    rd["tunnel"] = rd["tunnel"].fillna("F").ne("F")
    rd_m = rd.to_crs(CRS_METRIC)
    rd["length_m"] = rd_m.length.round(1)
    # connectivity-friendly flag: midpoint of the segment inside the admin polygon
    mid = gpd.GeoSeries(
        rd_m.geometry.interpolate(0.5, normalized=True), crs=CRS_METRIC
    ).to_crs(CRS_WGS84)
    rd["in_boundary"] = mid.within(boundary_geom)
    keep = [
        "osm_id", "fclass", "name", "ref", "oneway", "oneway_walk",
        "bridge", "tunnel", "layer", "walk_group", "length_m", "in_boundary",
        "geometry",
    ]
    rd = rd[[c for c in keep if c in rd.columns]]
    rd.to_crs(CRS_WGS84).to_file(
        OUT / "osm_walk_roads.gpkg", layer="walk_roads", driver="GPKG"
    )
    km = rd["length_m"].sum() / 1000
    log(f"[walk] roads {len(rd)} ({km:,.0f} km), layer walk_roads")


# ------------------------------------------------------------------------ POIs
def prep_poi(boundary_geom):
    bb = tuple(boundary_geom.bounds)
    frames = []
    specs = [
        ("gis_osm_pois_free", "point", "amenities"),
        ("gis_osm_pofw_free", "point", "worship"),
        ("gis_osm_transport_free", "point", "transport"),
        ("gis_osm_pois_a_free", "polygon", "amenities"),
        ("gis_osm_pofw_a_free", "polygon", "worship"),
    ]
    for layer, gtype, src in specs:
        try:
            d = pyogrio.read_dataframe(GPKG, layer=layer, bbox=bb)
        except Exception as exc:  # noqa: BLE001
            log(f"[poi!] {layer}: {exc}")
            continue
        if d.empty:
            continue
        d = d[d.geometry.notna() & ~d.geometry.is_empty].copy()
        d = d.to_crs(CRS_WGS84)
        d["source_layer"] = layer
        d["source_group"] = src
        d["geometry_type"] = gtype
        frames.append(d)
        log(f"[poi] {layer}: {len(d)}")
    poi = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry")
    poi = poi.set_crs(CRS_WGS84, allow_override=True)
    poi["fclass"] = poi["fclass"].fillna("")
    poi["category"] = poi["fclass"].map(POI_CATEGORY).fillna("其他")
    poi["name"] = poi["name"].fillna("")
    poi["geom_kind"] = poi.geom_type.map(
        lambda t: "point" if t == "Point" else "area"
    )
    # area is only meaningful for polygon features
    area = gpd.GeoSeries(poi.geometry, crs=CRS_WGS84).to_crs(CRS_METRIC).area
    poi["area_m2"] = area.where(poi["geom_kind"] == "area").round(0)
    # counting/joining always uses a point, so store a canonical point per POI
    poi["in_boundary"] = gpd.GeoSeries(
        poi.geometry.representative_point(), crs=CRS_WGS84
    ).within(boundary_geom)
    poi = poi.reset_index(drop=True)
    poi.insert(0, "poi_id", "P-" + (poi.index + 1).astype(str).str.zfill(6))

    keep = [
        "poi_id", "source_layer", "source_group", "geom_kind", "osm_id",
        "fclass", "category", "name", "area_m2", "in_boundary",
    ]
    # layer 1: every POI as a point -> the layer the apps join against
    pt = gpd.GeoDataFrame(
        poi[keep].copy(),
        geometry=gpd.GeoSeries(poi.geometry.representative_point(), crs=CRS_WGS84),
        crs=CRS_WGS84,
    )
    pt.to_file(OUT / "poi.gpkg", layer="poi_points", driver="GPKG")
    # layer 2: original polygons, for draw-on-map and QA only
    ar = poi[poi["geom_kind"] == "area"][keep + ["geometry"]]
    ar.to_file(OUT / "poi.gpkg", layer="poi_areas", driver="GPKG", mode="a")

    inner = poi[poi["in_boundary"]]
    log(f"[poi] total {len(poi)} (in boundary {len(inner)}); "
        f"points {int((poi['geom_kind'] == 'point').sum())}, areas {len(ar)}")
    log("[poi] by category:\n" + inner["category"].value_counts().to_string())
    return poi


def annotate_along_distance(edges: pd.DataFrame, stops: pd.DataFrame,
                            shapes: gpd.GeoDataFrame, mode: str) -> pd.DataFrame:
    """Add route-following distance per edge by projecting stops onto the line shape.

    ``distance_m`` from the Amap tables is great-circle between stop centres.
    Walking/bus ride time should follow the actual alignment, so each stop is
    projected onto the direction's polyline in order (monotone march) and the
    along-line arc length between consecutive stops is recorded.

    Adds: dist_route_m, detour_ratio, dist_source ('shape' | 'crowfly').
    """
    log(f"[{mode}] projecting stops onto {len(shapes)} route shapes ...")
    shp = shapes.to_crs(CRS_METRIC)
    lines = dict(zip(shp["line_id"].astype(str), shp.geometry))
    along: dict[tuple[str, int, int], float] = {}
    for lid, grp in stops.sort_values(["line_id", "sequence"]).groupby("line_id"):
        g = lines.get(str(lid))
        if g is None or g.is_empty:
            continue
        pts = gpd.GeoSeries(
            shapely.points(grp["lng_wgs84"].to_numpy(), grp["lat_wgs84"].to_numpy()),
            crs=CRS_WGS84,
        ).to_crs(CRS_METRIC)
        total = g.length
        t_prev = 0.0
        seq = grp["sequence"].to_numpy()
        for k, p in enumerate(pts):
            if t_prev >= total:
                t = total
            else:
                sub = shapely.ops.substring(g, t_prev, total)
                t = t_prev + (sub.project(p) if not sub.is_empty else 0.0)
            if k > 0:
                along[(str(lid), int(seq[k - 1]), int(seq[k]))] = t - t_prev
            t_prev = t

    ed = edges.copy()
    ed["dist_route_m"] = [
        round(along.get((str(r.line_id), int(r.from_sequence), int(r.to_sequence)), float("nan")), 1)
        for r in ed.itertuples()
    ]
    ed["detour_ratio"] = (ed["dist_route_m"] / ed["distance_m"]).round(3)
    # a ratio near 0 means the shape runs the other way; > 5 means a loop artefact
    good = ed["dist_route_m"].notna() & ed["detour_ratio"].between(0.85, 5.0)
    ed["dist_source"] = ["shape" if ok else "crowfly" for ok in good]
    ed.loc[~good, ["dist_route_m", "detour_ratio"]] = float("nan")
    return ed


# -------------------------------------------------------------------- manifest
def write_manifest(boundary_area_km2: float):
    files = sorted(
        p for p in OUT.iterdir() if p.is_file() and p.name != "manifest.json"
    )
    entries = []
    for p in files:
        entry = {
            "name": p.name,
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        }
        if p.suffix == ".csv":
            entry["rows"] = int(
                sum(1 for _ in p.open("rb")) - 1
            )
        elif p.name.endswith((".geojson", ".gpkg")):
            try:
                if p.suffix == ".gpkg":
                    layers = {
                        name: int(pyogrio.read_info(str(p), layer=name)["features"])
                        for name, _ in pyogrio.list_layers(str(p))
                    }
                    entry["layers"] = layers
                    entry["features"] = sum(layers.values())
                else:
                    entry["features"] = int(pyogrio.read_info(str(p))["features"])
            except Exception:  # noqa: BLE001
                pass
        entries.append(entry)

    manifest = {
        "dataset": "wuhan-isochrone-inputs",
        "version": VERSION,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "crs": CRS_WGS84,
        "metric_crs": CRS_METRIC,
        "study_area": {"name": "武汉市", "area_km2": round(boundary_area_km2, 2)},
        "source_files": {
            "boundary": str(BOUNDARY.relative_to(ROOT)),
            "amap_bus": str((INTERIM / "amap_bus_stations_snapped.csv").relative_to(ROOT)),
            "amap_metro": str((METRO / "metro_stations_snapped.csv").relative_to(ROOT)),
            "osm": str(GPKG.relative_to(ROOT)),
        },
        "parameters": {
            "road_buffer_m": ROAD_BUFFER_M,
            "walkable_fclass": sorted(WALKABLE),
            "foot_only_fclass": sorted(FOOT_ONLY),
            "poi_categories": POI_LABELS,
        },
        "coverage": {
            "bus_lines_available": 591,
            "bus_lines_missing": 103,
            "bus_directions": 1054,
            "bus_stops": 7823,
            "bus_edges": 26248,
            "metro_lines": 9,
            "metro_directions": 18,
            "metro_stations": 231,
            "metro_edges": 516,
            "walk_road_segments": 91203,
            "walk_road_km": 47051.2,
            "poi_total": 14154,
        },
        "files": entries,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"[manifest] {len(entries)} files")


def main():
    reset_dir(OUT)
    b = prep_boundary()
    geom = b.geometry.union_all()
    prep_bus(geom)
    prep_metro()
    prep_walk_roads(geom)
    prep_poi(geom)
    write_manifest(float(b["area_km2"].sum()))
    log(f"\nOK -> {OUT}")


if __name__ == "__main__":
    main()
