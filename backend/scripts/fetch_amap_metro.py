from __future__ import annotations

import csv
import io
import json
import re
import sys
import urllib.parse
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_amap_line_pilot import AmapClient
from geo_utils import gcj02_to_wgs84, haversine_m

OUT = ROOT / "data" / "interim" / "amap_metro"
OUT.mkdir(parents=True, exist_ok=True)
METRO_LABELS = ["1", "2", "3", "4", "6", "7", "8", "11", "阳逻线"]


def read_public_metro() -> dict[str, list[str]]:
    zpath = next(p for p in ROOT.glob("*.zip") if "轨道" in p.name)
    with zipfile.ZipFile(zpath) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        rows = list(csv.DictReader(io.StringIO(zf.read(member).decode("utf-8-sig"))))
    result = {}
    for row in rows:
        label = str(row["xl"]).strip()
        result.setdefault(label, []).append(str(row["cz"]).strip())
    return result


def line_regex(label: str):
    if label == "阳逻线":
        return re.compile(r"^轨道交通.*阳逻线[）)]")
    return re.compile(rf"^轨道交通{re.escape(label)}号线[（(]")


def parse_time(value: str) -> int | None:
    value = str(value or "").strip()
    if not value:
        return None
    parts = value.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_timedesc(raw: str):
    if not raw:
        return None
    try:
        parsed = json.loads(urllib.parse.unquote(str(raw)))
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def parse_polyline(raw: str) -> list[tuple[float, float]]:
    coords = []
    for pair in str(raw or "").split(";"):
        if "," not in pair:
            continue
        try:
            lng, lat = (float(v) for v in pair.split(",", 1))
        except ValueError:
            continue
        coords.append(gcj02_to_wgs84(lng, lat))
    return coords


def main():
    public = read_public_metro()
    client = AmapClient(interval=2.0)
    stop_rows = []
    shape_rows = []
    schedule_rows = []
    direction_rows = []
    raw_all = {}

    for label in METRO_LABELS:
        keyword = "阳逻线" if label == "阳逻线" else f"{label}号线"
        payload = client.get(
            "/v3/bus/linename",
            {"city": "420100", "keywords": keyword, "extensions": "all", "offset": "20", "page": "1"},
        )
        raw_all[label] = payload
        regex = line_regex(label)
        directions = [
            line for line in payload.get("buslines", [])
            if str(line.get("type", "")).strip() == "地铁" and regex.match(str(line.get("name", "")))
        ]
        print("=" * 80)
        print("LINE", label, "query:", keyword, "matched metro directions:", len(directions))
        for direction in directions:
            line_id = str(direction.get("id", ""))
            line_name = str(direction.get("name", ""))
            stops = direction.get("busstops", [])
            direction_rows.append(
                {
                    "public_line": label,
                    "line_id": line_id,
                    "line_name": line_name,
                    "start_stop": direction.get("start_stop", ""),
                    "end_stop": direction.get("end_stop", ""),
                    "station_count": len(stops),
                    "distance_km": direction.get("distance", ""),
                    "loop": direction.get("loop", ""),
                    "polyline_points": len(parse_polyline(direction.get("polyline", ""))),
                    "timedesc_present": bool(direction.get("timedesc")),
                }
            )
            for stop in stops:
                location = str(stop.get("location", ""))
                if "," not in location:
                    continue
                lng, lat = (float(v) for v in location.split(",", 1))
                lng_wgs, lat_wgs = gcj02_to_wgs84(lng, lat)
                stop_rows.append(
                    {
                        "public_line": label,
                        "line_id": line_id,
                        "line_name": line_name,
                        "sequence": int(stop.get("sequence", 0) or 0),
                        "station_id": str(stop.get("id", "")),
                        "station_name": str(stop.get("name", "")),
                        "lng_gcj02": lng,
                        "lat_gcj02": lat,
                        "lng_wgs84": lng_wgs,
                        "lat_wgs84": lat_wgs,
                    }
                )
            coords = parse_polyline(direction.get("polyline", ""))
            if len(coords) >= 2:
                shape_rows.append(
                    {
                        "public_line": label,
                        "line_id": line_id,
                        "line_name": line_name,
                        "start_stop": direction.get("start_stop", ""),
                        "end_stop": direction.get("end_stop", ""),
                        "distance_km": direction.get("distance", ""),
                        "geometry": LineString(coords),
                    }
                )
            parsed = parse_timedesc(direction.get("timedesc", ""))
            if not parsed:
                continue
            for group in parsed.get("rule_group", []):
                date = group.get("date", {})
                day_types = date.get("day_type", []) or ["all"]
                remark = group.get("remark", "")
                for item in group.get("time_group", []):
                    start = item.get("start_time", "")
                    end = item.get("end_time", "")
                    interval = item.get("interval_time", "")
                    fixed = bool(start and start == end and not interval)
                    schedule_rows.append(
                        {
                            "public_line": label,
                            "line_id": line_id,
                            "line_name": line_name,
                            "day_type": "|".join(str(x) for x in day_types),
                            "period_type": "fixed" if fixed else "base",
                            "start_time": start,
                            "end_time": end,
                            "interval_seconds": parse_time(interval),
                            "remark": remark,
                        }
                    )
            for period_type, key in (("peak", "peak_time_group"), ("flat", "flat_time_group"), ("low", "low_time_group")):
                for item in parsed.get(key, []):
                    schedule_rows.append(
                        {
                            "public_line": label,
                            "line_id": line_id,
                            "line_name": line_name,
                            "day_type": "all",
                            "period_type": period_type,
                            "start_time": item.get("start_time", ""),
                            "end_time": item.get("end_time", ""),
                            "interval_seconds": parse_time(item.get("interval_time", "")),
                            "remark": parsed.get("allRemark", ""),
                        }
                    )

    stop_df = pd.DataFrame(stop_rows)
    stop_df.to_csv(OUT / "metro_route_stops.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(direction_rows).to_csv(OUT / "metro_directions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(schedule_rows).to_csv(OUT / "metro_schedule.csv", index=False, encoding="utf-8-sig")

    # unique metro stations by 高德 station id
    stations = (
        stop_df.groupby("station_id", as_index=False)
        .agg(
            station_name=("station_name", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
            lng_wgs84=("lng_wgs84", "median"),
            lat_wgs84=("lat_wgs84", "median"),
            line_count=("line_id", "nunique"),
            record_count=("line_id", "size"),
        )
        .reset_index(drop=True)
    )
    stations.to_csv(OUT / "metro_stations.csv", index=False, encoding="utf-8-sig")

    # consecutive station edges per direction
    edge_rows = []
    for (line_id,), group in stop_df.groupby(["line_id"], sort=False):
        group = group.sort_values("sequence")
        rows = list(group.itertuples())
        for left, right in zip(rows, rows[1:]):
            if left.station_id == right.station_id:
                continue
            distance = haversine_m(left.lng_wgs84, left.lat_wgs84, right.lng_wgs84, right.lat_wgs84)
            edge_rows.append(
                {
                    "public_line": left.public_line,
                    "line_id": line_id,
                    "line_name": left.line_name,
                    "from_sequence": left.sequence,
                    "to_sequence": right.sequence,
                    "from_station_id": left.station_id,
                    "to_station_id": right.station_id,
                    "from_station_name": left.station_name,
                    "to_station_name": right.station_name,
                    "distance_m": round(distance, 1),
                }
            )
    edge_df = pd.DataFrame(edge_rows)
    edge_df.to_csv(OUT / "metro_edges.csv", index=False, encoding="utf-8-sig")

    if shape_rows:
        gdf = gpd.GeoDataFrame(shape_rows, geometry="geometry", crs=4326)
        gdf.to_file(OUT / "metro_routes.geojson", driver="GeoJSON")

    (OUT / "raw_metro.json").write_text(json.dumps(raw_all, ensure_ascii=False, indent=2), encoding="utf-8")

    qa = {
        "public_lines": len(public),
        "matched_directions": len(direction_rows),
        "route_stop_records": int(len(stop_df)),
        "unique_stations": int(len(stations)),
        "edges": int(len(edge_df)),
        "shapes": int(len(shape_rows)),
        "schedule_rows": int(len(schedule_rows)),
        "line_direction_counts": {
            label: int(sum(1 for row in direction_rows if row["public_line"] == label))
            for label in METRO_LABELS
        },
        "public_station_counts": {label: len(names) for label, names in public.items()},
    }
    (OUT / "metro_qa_summary.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2))
    print("API calls:", client.calls)
    print("wrote:", OUT)


if __name__ == "__main__":
    main()
