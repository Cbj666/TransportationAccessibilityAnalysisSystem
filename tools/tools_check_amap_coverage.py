from pathlib import Path
import csv
import io
import zipfile

import pandas as pd

ROOT = Path(".")
summary = pd.read_csv(ROOT / "data/interim/amap_pilot/summary.csv")
summary_lines = set(summary["line"].astype(str))

for path in ROOT.glob("*.zip"):
    if "公交" not in path.name:
        continue
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        rows = list(csv.DictReader(io.StringIO(zf.read(member).decode("utf-8-sig"))))
    public_lines = [r["xlh"].strip() for r in rows]
    break

print("public lines:", len(public_lines), "unique:", len(set(public_lines)))
print("summary rows:", len(summary))
print("missing from summary:", [line for line in public_lines if line not in summary_lines])
print("\nzero-overlap ok lines:")
print(summary[(summary.status == "ok") & (summary.station_overlap == 0)][["line", "best_direction", "best_stations", "station_overlap"]].to_string(index=False))
print("\nlow-overlap (<0.2) ok lines:")
print(summary[(summary.status == "ok") & (summary.station_overlap < 0.2)][["line", "best_direction", "best_stations", "station_overlap"]].to_string(index=False))
