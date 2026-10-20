from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from fetch_amap_line_pilot import (
    AmapClient,
    AmapDailyQuotaError,
    OUT_DIR,
    choose_best_direction,
    fetch_line_details,
    fetch_place_pages,
    filter_pois,
    find_line_ids,
    read_public_lines,
    safe_name,
    split_route,
)


SUMMARY = OUT_DIR / "summary.csv"
PROGRESS = OUT_DIR / "progress.json"
SUMMARY_COLUMNS = [
    "line", "public_stations", "public_start", "public_end",
    "poi_total", "poi_pages", "poi_kept", "poi_dropped", "station_ids",
    "line_ids", "directions", "best_direction", "best_stations",
    "station_overlap", "id_source", "status", "notes",
]


def load_existing() -> dict[str, dict]:
    if not SUMMARY.exists():
        return {}
    df = pd.read_csv(SUMMARY, encoding="utf-8-sig")
    return {str(row["line"]): row.to_dict() for _, row in df.iterrows()}


def write_summary(rows: dict[str, dict]):
    df = pd.DataFrame(list(rows.values()))
    for column in SUMMARY_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[SUMMARY_COLUMNS]
    temp = SUMMARY.with_suffix(".csv.tmp")
    df.to_csv(temp, index=False, encoding="utf-8-sig")
    temp.replace(SUMMARY)


def write_progress(total: int, done: int, rows: dict[str, dict], calls: int, elapsed: float, linename_used: int, current: str):
    status_counts = {}
    for row in rows.values():
        status = str(row.get("status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
    payload = {
        "total_lines": total,
        "done_lines": done,
        "ok_lines": status_counts.get("ok", 0),
        "status_counts": status_counts,
        "api_calls_this_run": calls,
        "elapsed_seconds": round(elapsed, 1),
        "linename_fallback_used": linename_used,
        "current_line": current,
    }
    PROGRESS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条，0 表示全部")
    parser.add_argument("--offset", type=int, default=0, help="从第 N 条开始")
    parser.add_argument("--only", default="", help="逗号分隔的线路名，仅处理这些线路")
    parser.add_argument("--problems", action="store_true", help="只重跑失败、低重合度或缺失的线路")
    parser.add_argument("--interval", type=float, default=2.0, help="请求间隔秒数")
    parser.add_argument("--linename-cap", type=int, default=90, help="bus/linename 兜底最多使用次数")
    args = parser.parse_args()

    public = read_public_lines()
    labels = list(public.keys())
    rows = load_existing()
    if args.problems:
        selected = []
        for label in labels:
            row = rows.get(label)
            if not row:
                selected.append(label)
                continue
            status = str(row.get("status", ""))
            try:
                overlap = float(row.get("station_overlap") or 0)
            except (TypeError, ValueError):
                overlap = 0.0
            if pd.isna(overlap):
                overlap = 0.0
            if status != "ok" or overlap < 0.3:
                selected.append(label)
        labels = selected
    elif args.only:
        wanted = [item.strip() for item in args.only.split(",") if item.strip()]
        labels = [label for label in labels if label in wanted]
    else:
        labels = labels[args.offset:]
        if args.limit:
            labels = labels[: args.limit]

    client = AmapClient(interval=args.interval)
    linename_used = sum(1 for row in rows.values() if str(row.get("id_source", "")) == "linename-fallback")
    total = len(labels)
    started = time.monotonic()
    done = 0
    print(f"TOTAL LINES: {total}, existing summaries: {len(rows)}, linename_used: {linename_used}")

    for index, label in enumerate(labels, start=1):
        done = index
        existing = rows.get(label)
        stops_path = OUT_DIR / f"stops_{safe_name(label)}.csv"
        if not args.problems and not args.only and existing and str(existing.get("status")) == "ok" and stops_path.exists():
            print(f"[{index}/{total}] {label}: cached ok, skip")
            write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, label)
            continue
        if args.problems or args.only:
            # remove stale wrong match before retrying
            stops_path.unlink(missing_ok=True)
            (OUT_DIR / f"raw_{safe_name(label)}.json").unlink(missing_ok=True)

        info = public[label]
        public_stations = info["stations"]
        public_start, public_end = split_route(info["route"])
        row = {
            "line": label,
            "public_stations": len(public_stations),
            "public_start": public_start,
            "public_end": public_end,
            "poi_total": 0,
            "poi_pages": 0,
            "poi_kept": 0,
            "poi_dropped": 0,
            "station_ids": 0,
            "line_ids": 0,
            "directions": 0,
            "best_direction": "",
            "best_stations": 0,
            "station_overlap": 0.0,
            "id_source": "",
            "status": "running",
            "notes": "",
        }
        try:
            pois, total_poi, pages = fetch_place_pages(client, label)
            kept, dropped = filter_pois(pois, label)
            if not kept:
                kept = pois
                row["notes"] = "address_filter_empty_used_all"
            row.update(
                {
                    "poi_total": max(total_poi, len(pois)),
                    "poi_pages": pages,
                    "poi_kept": len(kept),
                    "poi_dropped": dropped,
                    "station_ids": len({p.get("id") for p in kept}),
                }
            )
            if not kept:
                row["status"] = "no_poi"
                rows[label] = row
                write_summary(rows)
                print(f"[{index}/{total}] {label}: NO POI")
                write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, label)
                continue

            line_ids = []
            source = ""
            allow_fallback = linename_used < args.linename_cap
            for poi in kept:
                station_id = str(poi.get("id", ""))
                if not station_id:
                    continue
                line_ids, source = find_line_ids(client, station_id, label, allow_fallback=allow_fallback)
                if source == "linename-fallback":
                    linename_used += 1
                    allow_fallback = False
                    # one fallback attempt per line, never loop over all POIs
                    if line_ids:
                        break
                    break
                if line_ids:
                    break
            row["line_ids"] = len(line_ids)
            row["id_source"] = source
            if not line_ids:
                row["status"] = "no_line_id"
                row["notes"] = (str(row["notes"]) + "|linename_fallback_capped" if not allow_fallback else str(row["notes"])).strip("|")
                rows[label] = row
                write_summary(rows)
                print(f"[{index}/{total}] {label}: NO LINE ID ({source})")
                write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, label)
                continue

            directions = []
            for item in line_ids:
                directions.extend(fetch_line_details(client, str(item["id"])))
            directions = [d for d in directions if d.get("busstops")]
            row["directions"] = len(directions)
            if not directions:
                row["status"] = "no_direction"
                rows[label] = row
                write_summary(rows)
                print(f"[{index}/{total}] {label}: NO DIRECTION")
                write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, label)
                continue

            best, overlap = choose_best_direction(public_stations, public_start, public_end, label, directions)
            best_stops = best.get("busstops", [])
            row.update(
                {
                    "best_direction": best.get("name", ""),
                    "best_stations": len(best_stops),
                    "station_overlap": round(overlap, 3),
                    "status": "ok",
                }
            )
            with stops_path.open("w", encoding="utf-8-sig", newline="") as f:
                import csv

                writer = csv.writer(f)
                writer.writerow(["line", "line_id", "line_name", "sequence", "station_id", "station_name", "lng_gcj02", "lat_gcj02", "address"])
                for stop in best_stops:
                    location = str(stop.get("location", ""))
                    lng, lat = location.split(",", 1) if "," in location else ("", "")
                    writer.writerow(
                        [
                            label,
                            best.get("id", ""),
                            best.get("name", ""),
                            stop.get("sequence", ""),
                            stop.get("id", ""),
                            stop.get("name", ""),
                            lng,
                            lat,
                            "",
                        ]
                    )
            raw_path = OUT_DIR / f"raw_{safe_name(label)}.json"
            raw_path.write_text(
                json.dumps({"label": label, "public": info, "pois": pois, "line_ids": line_ids, "directions": directions}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"[{index}/{total}] {label}: POI={len(kept)}/{max(total_poi, len(pois))} "
                f"lines={len(line_ids)} dirs={len(directions)} best={len(best_stops)} overlap={overlap:.1%}"
            )
        except AmapDailyQuotaError as exc:
            row["status"] = "daily_quota"
            row["notes"] = str(exc)
            rows[label] = row
            write_summary(rows)
            print(f"[{index}/{total}] {label}: DAILY QUOTA - {exc}")
            write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, label)
            break
        except Exception as exc:
            row["status"] = "error"
            row["notes"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            rows[label] = row
            print(f"[{index}/{total}] {label}: ERROR - {row['notes']}")
        rows[label] = row
        write_summary(rows)
        write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, label)

    write_summary(rows)
    write_progress(total, done, rows, client.calls, time.monotonic() - started, linename_used, "")
    print("=" * 80)
    print("DONE. API calls this run:", client.calls)
    print("summary:", SUMMARY)
    print("progress:", PROGRESS)


if __name__ == "__main__":
    main()
