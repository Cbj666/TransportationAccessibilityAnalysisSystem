from pathlib import Path
import json
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from geo_utils import gcj02_to_wgs84
from pilot_line import load_roads, plot_overlay, snap_stations

OUT = ROOT / "data" / "output"
INTERIM = ROOT / "data" / "interim" / "amap_pilot"
OUT.mkdir(parents=True, exist_ok=True)

summaries = []
for label in ("340路", "H82路"):
    path = INTERIM / f"stops_{label}.csv"
    df = pd.read_csv(path)
    coords = [gcj02_to_wgs84(lng, lat) for lng, lat in zip(df["lng_gcj02"], df["lat_gcj02"])]
    df["lng_wgs84"] = [c[0] for c in coords]
    df["lat_wgs84"] = [c[1] for c in coords]
    df["use_for_network"] = True
    df["flags"] = ""
    df["station_name"] = df["station_name"].astype(str)

    minx, miny = df["lng_wgs84"].min() - 0.03, df["lat_wgs84"].min() - 0.03
    maxx, maxy = df["lng_wgs84"].max() + 0.03, df["lat_wgs84"].max() + 0.03
    roads = load_roads((minx, miny, maxx, maxy))
    snapped = snap_stations(df, roads)
    snapped["flags"] = snapped["flags"].fillna("")
    snapped.loc[snapped["snap_distance_m"] > 80, "flags"] = "snap_gt_80m"

    snapped_path = INTERIM / f"snapped_{label}.csv"
    snapped.to_csv(snapped_path, index=False, encoding="utf-8-sig")
    plot_path = OUT / f"amap_pilot_{label}_overlay.png"
    plot_overlay(snapped, roads, plot_path)

    summary = {
        "line": label,
        "stations": int(len(snapped)),
        "roads_in_bbox": int(len(roads)),
        "avg_snap_distance_m": round(float(snapped["snap_distance_m"].mean()), 2),
        "max_snap_distance_m": round(float(snapped["snap_distance_m"].max()), 2),
        "snap_gt_80m": int((snapped["snap_distance_m"] > 80).sum()),
        "first_station": str(snapped.iloc[0]["station_name"]),
        "last_station": str(snapped.iloc[-1]["station_name"]),
    }
    summary_path = OUT / f"amap_pilot_{label}_snap_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summaries.append(summary)
    print(json.dumps(summary, ensure_ascii=False))

print(json.dumps(summaries, ensure_ascii=False, indent=2))
