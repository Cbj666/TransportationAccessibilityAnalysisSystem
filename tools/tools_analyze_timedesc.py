from pathlib import Path
import json
import urllib.parse

RAW = Path("data/interim/amap_pilot")
stats = {
    "directions": 0,
    "timedesc_present": 0,
    "timedesc_parse_ok": 0,
    "has_time_group": 0,
    "has_peak": 0,
    "has_flat": 0,
    "has_low": 0,
    "has_interval": 0,
    "has_fixed_departure": 0,
    "start_time_nonempty": 0,
    "end_time_nonempty": 0,
}
examples = []
for path in sorted(RAW.glob("raw_*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    for direction in payload.get("directions", []):
        stats["directions"] += 1
        if direction.get("start_time"):
            stats["start_time_nonempty"] += 1
        if direction.get("end_time"):
            stats["end_time_nonempty"] += 1
        raw = direction.get("timedesc")
        if not raw:
            continue
        stats["timedesc_present"] += 1
        try:
            parsed = json.loads(urllib.parse.unquote(raw))
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if not isinstance(parsed, dict):
                continue
        except Exception:
            continue
        stats["timedesc_parse_ok"] += 1
        if parsed.get("rule_group"):
            stats["has_time_group"] += 1
        if parsed.get("peak_time_group"):
            stats["has_peak"] += 1
        if parsed.get("flat_time_group"):
            stats["has_flat"] += 1
        if parsed.get("low_time_group"):
            stats["has_low"] += 1
        intervals = []
        for group in parsed.get("rule_group", []):
            for item in group.get("time_group", []):
                if item.get("interval_time"):
                    intervals.append(item["interval_time"])
        for group in ("peak_time_group", "flat_time_group", "low_time_group"):
            for item in parsed.get(group, []):
                if item.get("interval_time"):
                    intervals.append(item["interval_time"])
        if intervals:
            stats["has_interval"] += 1
        remark = str(parsed.get("allRemark", ""))
        if "定点" in remark or "定点" in str(parsed):
            stats["has_fixed_departure"] += 1
        if len(examples) < 3 and parsed.get("rule_group"):
            examples.append((path.stem, direction.get("name"), parsed))

print(json.dumps(stats, ensure_ascii=False, indent=2))
for name, line, parsed in examples:
    print("=" * 80)
    print(name, "|", line)
    print(json.dumps(parsed, ensure_ascii=False, indent=2)[:2000])
