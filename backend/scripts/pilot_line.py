from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baidu_place import BaiduApiError, BaiduPlaceClient, BaiduQuotaError
from geo_utils import bd09_to_wgs84, haversine_m


ROOT = Path(__file__).resolve().parents[2]  # project root
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
RAW_DIR = ROOT / "data" / "raw"
INTERIM_DIR = ROOT / "data" / "interim"
OUTPUT_DIR = ROOT / "data" / "output"
CACHE_CANDIDATES = ROOT / "data" / "cache" / "pilot_candidates.json"
for directory in (RAW_DIR, INTERIM_DIR, OUTPUT_DIR, CACHE_CANDIDATES.parent):
    directory.mkdir(parents=True, exist_ok=True)


def read_bus_csv() -> list[dict]:
    for path in ROOT.glob("*.zip"):
        if "公交" not in path.name:
            continue
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not members:
                continue
            raw = zf.read(members[0])
        text = raw.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    raise FileNotFoundError("未找到公交线路站点信息压缩包")


def normalize_name(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("（", "(").replace("）", ")").replace("　", "")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"\(.*?\)", "", value)
    value = value.replace("公交车站", "").replace("公交站", "")
    value = re.sub(r"站$", "", value)
    return value


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def is_bus_stop(result: dict) -> bool:
    tag = str(result.get("detail_info", {}).get("tag", ""))
    classified = str(result.get("detail_info", {}).get("classified_poi_tag", ""))
    return "公交车站" in tag or "公交车站" in classified or "公交站" in tag


def extract_candidates(station: str, payload: dict) -> list[dict]:
    candidates = []
    for result in payload.get("results", []):
        name = result.get("name", "")
        location = result.get("location") or {}
        if "lng" not in location or "lat" not in location:
            continue
        sim = similarity(station, name)
        bus = is_bus_stop(result)
        if sim < 0.45 and not bus:
            continue
        detail = result.get("detail_info", {})
        candidates.append(
            {
                "name": name,
                "lng_bd09": float(location["lng"]),
                "lat_bd09": float(location["lat"]),
                "address": result.get("address", ""),
                "tag": detail.get("tag", ""),
                "classified_poi_tag": detail.get("classified_poi_tag", ""),
                "uid": result.get("uid", ""),
                "area": result.get("area", ""),
                "similarity": round(sim, 4),
                "is_bus_stop": bus,
            }
        )
    # keep a compact but diverse candidate pool for route-continuity DP
    candidates.sort(key=lambda c: (-c["similarity"], not c["is_bus_stop"]))
    exact = [c for c in candidates if c["similarity"] >= 0.95 and c["is_bus_stop"]]
    if exact:
        pool = exact + [c for c in candidates if c not in exact][:8]
    else:
        pool = [c for c in candidates if c["is_bus_stop"]][:10] or candidates[:10]
    return pool[:12]


def line_number_match(address: str, line_label: str) -> bool:
    if not address or not line_label:
        return False
    normalized = address.replace("；", ";").replace("，", ",")
    tokens = [t.strip() for t in normalized.replace(",", ";").split(";") if t.strip()]
    label = line_label.strip()
    bare = label[:-1] if label.endswith("路") else label
    for token in tokens:
        if token == label or token.startswith(label + "[") or token.startswith(label + "("):
            return True
        if bare and (token == bare or token.startswith(bare + "[") or token.startswith(bare + "(")):
            return True
    return False


def modal_area(candidates_by_station: list[list[dict]], line_label: str) -> str:
    areas = []
    for candidates in candidates_by_station:
        for candidate in candidates:
            if candidate["is_bus_stop"] and line_number_match(candidate["address"], line_label):
                areas.append(candidate["area"])
    if not areas:
        areas = [c["area"] for candidates in candidates_by_station for c in candidates if c["is_bus_stop"] and c["area"]]
    if not areas:
        return ""
    return max(set(areas), key=areas.count)


def emission_cost(station: str, candidate: dict, line_label: str, expected_area: str) -> float:
    sim = candidate["similarity"]
    cost = (1.0 - sim) * 5.0
    if not candidate["is_bus_stop"]:
        cost += 2.0
    if line_number_match(candidate["address"], line_label):
        cost -= 2.5
    else:
        cost += 0.8
    if expected_area and candidate["area"] and candidate["area"] != expected_area:
        cost += 1.2
    if candidate["similarity"] >= 0.99:
        cost -= 0.3
    return cost


def transition_cost(a: dict, b: dict) -> float:
    distance = haversine_m(a["lng_bd09"], a["lat_bd09"], b["lng_bd09"], b["lat_bd09"])
    # typical urban bus legs are hundreds of metres; penalise implausible jumps strongly
    cost = min(distance / 1000.0, 20.0) * 1.6 + (distance > 5000) * 6.0
    # distinct consecutive station names should not collapse onto the same point
    if distance < 20:
        cost += 1.5
    return cost


def select_route(stations: list[str], candidates_by_station: list[list[dict]], line_label: str) -> list[dict | None]:
    if not stations:
        return []
    expected_area = modal_area(candidates_by_station, line_label)
    states = candidates_by_station[0]
    if not states:
        return [None] * len(stations)
    dp = [emission_cost(stations[0], c, line_label, expected_area) for c in states]
    back = [[-1] * len(states)]
    for index in range(1, len(stations)):
        current = candidates_by_station[index]
        if not current:
            # no candidate: keep previous states, mark this station unresolved
            back.append(list(range(len(states))))
            continue
        new_dp = []
        new_back = []
        for candidate in current:
            costs = [
                dp[j] + transition_cost(prev, candidate) + emission_cost(stations[index], candidate, line_label, expected_area)
                for j, prev in enumerate(states)
            ]
            best = int(np.argmin(costs))
            new_dp.append(costs[best])
            new_back.append(best)
        states = current
        dp = new_dp
        back.append(new_back)

    best_last = int(np.argmin(dp))
    chosen: list[dict | None] = [None] * len(stations)
    state_index = best_last
    for index in range(len(stations) - 1, -1, -1):
        current = candidates_by_station[index]
        if current and 0 <= state_index < len(current):
            chosen[index] = current[state_index]
        if index > 0:
            if 0 <= state_index < len(back[index]):
                state_index = back[index][state_index]
            else:
                state_index = -1
    return chosen


def load_roads(bbox: tuple[float, float, float, float]):
    import geopandas as gpd

    gpkg = OSM_GPKG
    roads = gpd.read_file(gpkg, layer="gis_osm_roads_free", bbox=bbox, engine="pyogrio")
    if roads.crs is None:
        roads = roads.set_crs(4326)
    drivable = {
        "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "unclassified", "residential", "service",
        "living_street", "busway",
    }
    roads = roads[roads["fclass"].isin(drivable)].copy()
    return roads.to_crs(32650)


def snap_stations(df: pd.DataFrame, roads):
    import geopandas as gpd
    from shapely.ops import nearest_points
    from shapely.strtree import STRtree

    stations = gpd.GeoDataFrame(
        df.copy(),
        geometry=gpd.points_from_xy(df["lng_wgs84"], df["lat_wgs84"]),
        crs=4326,
    ).to_crs(32650)
    road_geoms = list(roads.geometry)
    tree = STRtree(road_geoms)
    snapped = []
    for point in stations.geometry:
        index = int(tree.nearest(point))
        road = road_geoms[index]
        snap = nearest_points(point, road)[1]
        row = roads.iloc[index]
        snapped.append(
            {
                "road_index": index,
                "road_fclass": row.get("fclass", ""),
                "road_name": row.get("name", ""),
                "snap_distance_m": round(point.distance(snap), 1),
                "snap_geometry": snap,
            }
        )
    snapped_gdf = gpd.GeoDataFrame(snapped, geometry="snap_geometry", crs=32650).to_crs(4326)
    df = df.copy()
    df["road_fclass"] = snapped_gdf["road_fclass"].values
    df["road_name"] = snapped_gdf["road_name"].values
    df["snap_distance_m"] = snapped_gdf["snap_distance_m"].values
    df["snap_lng"] = snapped_gdf.geometry.x.values
    df["snap_lat"] = snapped_gdf.geometry.y.values
    return df


def plot_overlay(df: pd.DataFrame, roads, output_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(12, 12), dpi=200)
    roads.plot(ax=ax, color="#c9ced6", linewidth=0.5, zorder=1)
    ready = df[df["use_for_network"]]
    low = df[~df["use_for_network"]]
    if len(ready) > 1:
        ax.plot(ready["snap_lng"], ready["snap_lat"], color="#d9480f", linewidth=2.2, alpha=0.8, zorder=2)
    ax.scatter(ready["snap_lng"], ready["snap_lat"], s=55, c="#c92a2a", edgecolors="white", linewidths=1.2, zorder=3, label="高/中置信度")
    if len(low):
        ax.scatter(low["snap_lng"], low["snap_lat"], s=65, c="#868e96", marker="x", linewidths=2, zorder=3, label="低置信度/待核验")
    for _, row in df.iterrows():
        ax.annotate(
            f'{int(row["sequence"])}. {row["station_name"]}',
            (row["snap_lng"], row["snap_lat"]),
            xytext=(6, 4),
            textcoords="offset points",
            fontsize=7,
            color="#333333" if row["use_for_network"] else "#868e96",
            zorder=4,
        )
    ax.legend(loc="lower left", fontsize=9)
    ax.set_title(f'公交 {df["line"].iloc[0]} 站点定位与 OSM 路网叠合（试点）', fontsize=14)
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    margin = 0.015
    ax.set_xlim(df["snap_lng"].min() - margin, df["snap_lng"].max() + margin)
    ax.set_ylim(df["snap_lat"].min() - margin, df["snap_lat"].max() + margin)
    ax.set_aspect(1 / math.cos(math.radians(df["snap_lat"].mean())))
    ax.grid(True, linestyle=":", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--line", default="340路")
    parser.add_argument("--skip-snap", action="store_true")
    parser.add_argument("--offline", action="store_true", help="只使用已有缓存，不发起百度请求")
    args = parser.parse_args()

    rows = read_bus_csv()
    row = next((r for r in rows if r["xlh"].strip() == args.line), None)
    if row is None:
        raise SystemExit(f"未找到线路 {args.line}")
    stations = [s.strip() for s in row["tkzd"].split("、") if s.strip()]
    print("line:", args.line, "stations:", len(stations), "route:", row["xlxx"])

    client = BaiduPlaceClient(offline=args.offline)
    candidates_by_station = []
    api_blocked = False
    for index, station in enumerate(stations, start=1):
        if api_blocked:
            candidates_by_station.append([])
            print(f"{index:02d}/{len(stations)} {station}: skipped (API unavailable)")
            continue
        try:
            payload = client.search(f"{station} 公交站")
        except BaiduQuotaError as exc:
            print(f"{index:02d}/{len(stations)} {station}: QUOTA/BLOCKED - {exc}")
            api_blocked = True
            candidates_by_station.append([])
            continue
        except BaiduApiError as exc:
            print(f"{index:02d}/{len(stations)} {station}: API error - {exc}")
            candidates_by_station.append([])
            continue
        candidates = extract_candidates(station, payload)
        candidates_by_station.append(candidates)
        top = candidates[0] if candidates else None
        print(f"{index:02d}/{len(stations)} {station}: total={payload.get('total')} candidates={len(candidates)} top={top['name'] if top else '-'}")

    CACHE_CANDIDATES.write_text(
        json.dumps({"line": args.line, "stations": stations, "candidates": candidates_by_station}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    chosen = select_route(stations, candidates_by_station, args.line)
    records = []
    previous = None
    for index, (station, candidates, selected) in enumerate(zip(stations, candidates_by_station, chosen), start=1):
        if selected is None:
            records.append(
                {
                    "line": args.line,
                    "sequence": index,
                    "station_name": station,
                    "chosen_name": "",
                    "similarity": 0,
                    "line_match": False,
                    "confidence": "unresolved",
                    "use_for_network": False,
                    "tag": "",
                    "candidates_count": len(candidates),
                    "lng_bd09": None,
                    "lat_bd09": None,
                    "lng_wgs84": None,
                    "lat_wgs84": None,
                    "leg_distance_m": None,
                    "flags": "unresolved",
                }
            )
            continue
        lng_wgs84, lat_wgs84 = bd09_to_wgs84(selected["lng_bd09"], selected["lat_bd09"])
        leg = None
        if previous is not None:
            leg = haversine_m(previous[0], previous[1], lng_wgs84, lat_wgs84)
        line_match = line_number_match(selected["address"], args.line)
        if selected["similarity"] >= 0.9 and selected["is_bus_stop"] and line_match:
            confidence = "high"
        elif (selected["similarity"] >= 0.8 and selected["is_bus_stop"]) or line_match:
            confidence = "medium"
        else:
            confidence = "low"
        flags = []
        if selected["similarity"] < 0.8:
            flags.append("low_similarity")
        if not selected["is_bus_stop"]:
            flags.append("not_bus_stop")
        if not line_match:
            flags.append("no_line_evidence")
        if confidence == "low":
            flags.append("low_confidence")
        if leg is not None and leg > 3000:
            flags.append("leg_gt_3000m")
        if leg is not None and leg < 20:
            flags.append("zero_leg")
        records.append(
            {
                "line": args.line,
                "sequence": index,
                "station_name": station,
                "chosen_name": selected["name"],
                "similarity": selected["similarity"],
                "line_match": line_match,
                "confidence": confidence,
                "use_for_network": confidence in ("high", "medium"),
                "tag": selected["tag"],
                "candidates_count": len(candidates),
                "lng_bd09": selected["lng_bd09"],
                "lat_bd09": selected["lat_bd09"],
                "lng_wgs84": lng_wgs84,
                "lat_wgs84": lat_wgs84,
                "leg_distance_m": round(leg, 1) if leg is not None else None,
                "flags": "|".join(flags),
            }
        )
        previous = (lng_wgs84, lat_wgs84)

    df = pd.DataFrame(records)
    # quality check: a non-adjacent earlier station with a different name must not collapse onto the same point
    for i in range(len(df)):
        if pd.isna(df.at[i, "lng_wgs84"]):
            continue
        for j in range(i - 1):
            if pd.isna(df.at[j, "lng_wgs84"]):
                continue
            if normalize_name(df.at[i, "station_name"]) == normalize_name(df.at[j, "station_name"]):
                continue
            distance = haversine_m(
                df.at[i, "lng_wgs84"], df.at[i, "lat_wgs84"],
                df.at[j, "lng_wgs84"], df.at[j, "lat_wgs84"],
            )
            if distance < 30:
                current = str(df.at[i, "flags"] or "")
                df.at[i, "flags"] = f"{current}|repeated_coordinate" if current else "repeated_coordinate"
                df.at[i, "confidence"] = "low"
                df.at[i, "use_for_network"] = False
                break
    resolved = df.dropna(subset=["lng_wgs84"]).copy()
    csv_bd_path = INTERIM_DIR / f"pilot_{args.line}_stations_bd09.csv"
    csv_wgs_path = INTERIM_DIR / f"pilot_{args.line}_stations_wgs84.csv"
    df.to_csv(csv_bd_path, index=False, encoding="utf-8-sig")
    df.to_csv(csv_wgs_path, index=False, encoding="utf-8-sig")
    print("wrote:", csv_bd_path)
    print("wrote:", csv_wgs_path)
    print("resolved:", len(resolved), "/", len(df), "avg leg:", round(resolved["leg_distance_m"].mean(), 1) if len(resolved) else None)

    if args.skip_snap or resolved.empty:
        return
    try:
        minx, miny = resolved["lng_wgs84"].min() - 0.03, resolved["lat_wgs84"].min() - 0.03
        maxx, maxy = resolved["lng_wgs84"].max() + 0.03, resolved["lat_wgs84"].max() + 0.03
        roads = load_roads((minx, miny, maxx, maxy))
        print("roads in bbox:", len(roads))
        snapped = snap_stations(resolved, roads)
        snapped["flags"] = snapped["flags"].fillna("")
        snapped.loc[snapped["snap_distance_m"] > 80, "flags"] = snapped["flags"].apply(lambda x: f"{x}|snap_gt_80m" if x else "snap_gt_80m")
        snapped_path = INTERIM_DIR / f"pilot_{args.line}_stations_snapped.csv"
        snapped.to_csv(snapped_path, index=False, encoding="utf-8-sig")
        plot_path = OUTPUT_DIR / f"pilot_{args.line}_overlay.png"
        plot_overlay(snapped, roads, plot_path)
        summary = {
            "line": args.line,
            "station_count": int(len(df)),
            "resolved_count": int(len(resolved)),
            "high_confidence": int((df["confidence"] == "high").sum()),
            "medium_confidence": int((df["confidence"] == "medium").sum()),
            "low_confidence": int((df["confidence"] == "low").sum()),
            "unresolved": int((df["confidence"] == "unresolved").sum()),
            "network_ready": int(df["use_for_network"].sum()),
            "roads_in_bbox": int(len(roads)),
            "avg_snap_distance_m": round(float(snapped["snap_distance_m"].mean()), 1),
            "max_snap_distance_m": round(float(snapped["snap_distance_m"].max()), 1),
            "snap_gt_80m": int((snapped["snap_distance_m"] > 80).sum()),
            "avg_leg_distance_m": round(float(snapped["leg_distance_m"].mean()), 1),
            "max_leg_distance_m": round(float(snapped["leg_distance_m"].max()), 1),
            "flagged_rows": int((snapped["flags"].astype(str).str.len() > 0).sum()),
        }
        summary_path = OUTPUT_DIR / f"pilot_{args.line}_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote:", snapped_path)
        print("wrote:", plot_path)
        print("wrote:", summary_path)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except ImportError as exc:
        print("GIS 依赖尚未安装完成，跳过路网吸附:", exc)
    except Exception as exc:
        print("路网吸附失败:", type(exc).__name__, str(exc)[:500])


if __name__ == "__main__":
    main()
