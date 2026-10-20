from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]  # project root
CACHE_DIR = ROOT / "data" / "cache" / "amap_pilot"
OUT_DIR = ROOT / "data" / "interim" / "amap_pilot"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

PILOT_LINES = [
    "340路",
    "H89路",
    "H82路",
    "P101路",
    "402路",
    "906路",
    "910路",
    "408外环路",
    "电5内环路",
    "鄂101路",
]


class AmapError(RuntimeError):
    pass


class AmapDailyQuotaError(AmapError):
    pass


def load_key() -> str:
    for name in (".env", ".env.txt"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in ("GAODE_KEY", "AMAP_KEY", "GAODE_WEB_KEY"):
                    return value.strip()
    raise RuntimeError("未找到 GAODE_KEY")


class AmapClient:
    def __init__(self, interval: float = 2.0):
        self.key = load_key()
        self.interval = interval
        self.last_call = 0.0
        self.calls = 0

    def _wait(self):
        elapsed = time.monotonic() - self.last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_call = time.monotonic()

    def _cache_path(self, endpoint: str, params: dict) -> Path:
        key_params = {k: v for k, v in params.items() if k != "key"}
        raw = endpoint + "|" + json.dumps(key_params, ensure_ascii=False, sort_keys=True)
        return CACHE_DIR / (hashlib.sha1(raw.encode("utf-8")).hexdigest() + ".json")

    def get(self, endpoint: str, params: dict) -> dict:
        cache = self._cache_path(endpoint, params)
        if cache.exists():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if payload.get("status") == "1":
                return payload

        for attempt in range(4):
            self._wait()
            query = dict(params)
            query["key"] = self.key
            query["output"] = "json"
            url = "https://restapi.amap.com" + endpoint + "?" + urllib.parse.urlencode(query)
            request = urllib.request.Request(url, headers={"User-Agent": "wuhan-isochrone-course-project/0.2"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.calls += 1
            status = str(payload.get("status"))
            info = str(payload.get("info", ""))
            if status == "1":
                cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                return payload
            if "CUQPS" in info or "QPS" in info:
                sleep_for = 2 ** (attempt + 1)
                print(f"    QPS limit, retry in {sleep_for}s: {info}")
                time.sleep(sleep_for)
                continue
            if any(word in info.upper() for word in ("QUOTA", "LIMIT", "EXCEED")):
                raise AmapDailyQuotaError(f"{info} ({payload.get('infocode')})")
            raise AmapError(f"{info} ({payload.get('infocode')})")
        raise AmapError("QPS retry exhausted")


def read_public_lines() -> dict[str, dict]:
    for path in ROOT.glob("*.zip"):
        if "公交" not in path.name:
            continue
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not members:
                continue
            rows = list(csv.DictReader(io.StringIO(zf.read(members[0]).decode("utf-8-sig"))))
        result = {}
        for row in rows:
            label = row["xlh"].strip()
            stations = [s.strip() for s in row["tkzd"].split("、") if s.strip()]
            result[label] = {"stations": stations, "route": row.get("xlxx", "").strip()}
        return result
    raise FileNotFoundError("未找到公交线路站点压缩包")


def normalize_name(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("（", "(").replace("）", ")").replace("　", "")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"\(.*?\)", "", value)
    value = value.replace("公交车站", "").replace("公交站", "")
    value = re.sub(r"站$", "", value)
    return value


def line_core(label: str) -> str:
    value = label.strip()
    value = re.sub(r"路$", "", value)
    return value


def line_tokens(label: str) -> list[str]:
    label = str(label or "").strip()
    core = line_core(label)
    tokens = {label, core}
    if not label.endswith("路"):
        tokens.add(label + "路")
    for suffix in ("夜行", "区间", "快", "内环", "外环"):
        if suffix in core:
            base = core.replace(suffix, "")
            tokens.update(
                {
                    base, base + "路", base + suffix, base + "路" + suffix,
                    suffix + base, suffix + base + "路", base + suffix + "路",
                }
            )
            if suffix == "快":
                tokens.update({base + "快线", base + "路快线", base + "快"})
    if core.endswith("路"):
        tokens.add(core[:-1])
    return [t for t in dict.fromkeys(tokens) if t]


def line_name_matches(name: str, label: str) -> bool:
    prefix = re.split(r"[（(]", str(name or ""))[0].strip().replace(" ", "")
    if not prefix:
        return False
    for token in line_tokens(label):
        if prefix == token:
            return True
        if prefix.startswith(token):
            tail = prefix[len(token):len(token) + 1]
            if tail in ("路", "线", "("):
                return True
    return False


def address_matches_line(address: str, label: str) -> bool:
    if not address:
        return False
    text = address.replace("；", ";").replace("，", ",")
    parts = [p.strip() for p in re.split(r"[;,、]", text) if p.strip()]
    tokens = line_tokens(label)
    for part in parts:
        for token in tokens:
            if part == token or part.startswith(token + "(") or part.startswith(token + "["):
                return True
            if token == line_core(label) and part.startswith(token + "路"):
                return True
    return False


def query_variants(label: str) -> list[str]:
    label = str(label or "").strip()
    core = line_core(label)
    variants = [label, core]
    if "夜行" in core:
        base = core.replace("夜行", "")
        variants.extend([base, base + "路", "夜行" + base + "路"])
    if "区间" in core:
        base = core.replace("区间", "")
        variants.extend([base, base + "路"])
    if "快" in core:
        base = core.replace("快", "")
        variants.extend([base, base + "路"])
    return [item for item in dict.fromkeys(variants) if item]


def fetch_place_pages(client: AmapClient, label: str) -> tuple[list[dict], int, int]:
    pois: dict[str, dict] = {}
    total = 0
    pages = 0
    for keyword in query_variants(label):
        for page in range(1, 8):
            payload = client.get(
                "/v3/place/text",
                {
                    "keywords": keyword,
                    "city": "420100",
                    "citylimit": "true",
                    "types": "150700",
                    "offset": "25",
                    "page": str(page),
                    "extensions": "all",
                },
            )
            pages += 1
            total = int(payload.get("count") or 0)
            current = payload.get("pois") or []
            for poi in current:
                pois[str(poi.get("id"))] = poi
            if not current or len(pois) >= total:
                break
        if pois:
            break
    return list(pois.values()), total, pages


def filter_pois(pois: list[dict], label: str) -> tuple[list[dict], int]:
    matched = []
    for poi in pois:
        address = str(poi.get("address", ""))
        if "夜行" in label and "夜行" not in address:
            continue
        if address_matches_line(address, label):
            matched.append(poi)
    # If address filtering is too strict, fall back to all type-150700 results but flag it.
    return matched, len(pois) - len(matched)


def find_line_ids(client: AmapClient, station_id: str, label: str, allow_fallback: bool = True) -> tuple[list[dict], str]:
    payload = client.get("/v3/bus/stopid", {"id": station_id})
    lines = []
    for stop in payload.get("busstops", []):
        for line in stop.get("buslines", []):
            name = str(line.get("name", ""))
            if line_name_matches(name, label):
                lines.append(
                    {
                        "id": line.get("id"),
                        "name": name,
                        "start_stop": line.get("start_stop", ""),
                        "end_stop": line.get("end_stop", ""),
                    }
                )
    source = "stopid"
    if not lines and not allow_fallback:
        return [], "stopid-no-match"
    if not lines:
        # low-quota fallback; only used when POI/stopid discovery fails
        payload = client.get(
            "/v3/bus/linename",
            {"city": "420100", "keywords": line_core(label), "extensions": "all", "offset": "20", "page": "1"},
        )
        for line in payload.get("buslines", []):
            name = str(line.get("name", ""))
            if line_name_matches(name, label):
                lines.append(
                    {
                        "id": line.get("id"),
                        "name": name,
                        "start_stop": line.get("start_stop", ""),
                        "end_stop": line.get("end_stop", ""),
                    }
                )
        source = "linename-fallback"
    dedup = {str(item["id"]): item for item in lines if item.get("id")}
    return list(dedup.values()), source


def fetch_line_details(client: AmapClient, line_id: str) -> list[dict]:
    payload = client.get("/v3/bus/lineid", {"id": line_id, "extensions": "all"})
    return payload.get("buslines", [])


def split_route(route: str) -> tuple[str, str]:
    parts = re.split(r"——|—|-{2,}", route or "")
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return "", ""


def direction_score(public_start: str, public_end: str, line: dict) -> float:
    start = str(line.get("start_stop", ""))
    end = str(line.get("end_stop", ""))
    direct = (
        SequenceMatcher(None, normalize_name(public_start), normalize_name(start)).ratio()
        + SequenceMatcher(None, normalize_name(public_end), normalize_name(end)).ratio()
    ) / 2
    reverse = (
        SequenceMatcher(None, normalize_name(public_start), normalize_name(end)).ratio()
        + SequenceMatcher(None, normalize_name(public_end), normalize_name(start)).ratio()
    ) / 2
    return max(direct, reverse)


def loop_suffix(value: str) -> str:
    value = str(value or "")
    for suffix in ("内环", "外环", "区间"):
        if suffix in value:
            return suffix
    return ""


def choose_best_direction(public_stations: list[str], public_start: str, public_end: str, label: str, directions: list[dict]) -> tuple[dict, float]:
    public_names = {normalize_name(s) for s in public_stations}
    public_suffix = loop_suffix(label)
    variant_terms = ("之后", "区间", "放学期间", "专线", "大站", "快线")
    public_variant = any(term in label for term in variant_terms)
    best = None
    best_score = -1.0
    best_overlap = 0.0
    for line in directions:
        stops = line.get("busstops", [])
        names = {normalize_name(s.get("name", "")) for s in stops}
        overlap = len(public_names & names) / max(1, len(public_names | names))
        terminus = direction_score(public_start, public_end, line)
        line_suffix = loop_suffix(line.get("name", ""))
        if public_suffix and line_suffix:
            suffix_score = 1.0 if public_suffix == line_suffix else -1.0
        elif public_suffix and not line_suffix:
            suffix_score = -0.5
        else:
            suffix_score = 0.0
        score = 0.5 * overlap + 0.4 * terminus + 0.1 * suffix_score
        line_variant = any(term in str(line.get("name", "")) for term in variant_terms)
        if line_variant and not public_variant:
            score -= 0.15
        if score > best_score:
            best_score = score
            best = line
            best_overlap = overlap
    if best is None:
        raise ValueError("no direction")
    return best, best_overlap


def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", value)


def main():
    public = read_public_lines()
    missing = [line for line in PILOT_LINES if line not in public]
    if missing:
        print("未在公共数据中找到线路:", missing)
    lines = [line for line in PILOT_LINES if line in public]

    client = AmapClient(interval=2.0)
    summaries = []

    for index, label in enumerate(lines, start=1):
        print("=" * 80)
        print(f"[{index}/{len(lines)}] {label}")
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
            "status": "ok",
            "notes": "",
        }
        try:
            pois, total, pages = fetch_place_pages(client, label)
            kept, dropped = filter_pois(pois, label)
            if not kept:
                kept = pois
                row["notes"] = "address_filter_empty_used_all"
            row.update(
                {
                    "poi_total": max(total, len(pois)),
                    "poi_pages": pages,
                    "poi_kept": len(kept),
                    "poi_dropped": dropped,
                    "station_ids": len({p.get("id") for p in kept}),
                }
            )
            print(f"  POI: total={total}, kept={len(kept)}, dropped={dropped}")

            if not kept:
                row["status"] = "no_poi"
                summaries.append(row)
                continue

            line_ids = []
            source = ""
            for poi in kept:
                station_id = str(poi.get("id", ""))
                if not station_id:
                    continue
                line_ids, source = find_line_ids(client, station_id, label)
                if line_ids:
                    break
            row["line_ids"] = len(line_ids)
            row["id_source"] = source
            print(f"  line_ids: {len(line_ids)} via {source}")
            if not line_ids:
                row["status"] = "no_line_id"
                summaries.append(row)
                continue

            directions = []
            for item in line_ids:
                directions.extend(fetch_line_details(client, str(item["id"])))
            directions = [d for d in directions if d.get("busstops")]
            row["directions"] = len(directions)
            if not directions:
                row["status"] = "no_direction"
                summaries.append(row)
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
            print(f"  best: {best.get('name')} stations={len(best_stops)} overlap={overlap:.1%}")

            stops_path = OUT_DIR / f"stops_{safe_name(label)}.csv"
            with stops_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["line", "line_id", "line_name", "sequence", "station_id", "station_name", "lng_gcj02", "lat_gcj02", "address"])
                for stop in best_stops:
                    location = str(stop.get("location", ""))
                    lng, lat = (location.split(",", 1) + [""])[:2] if "," in location else ("", "")
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
            (OUT_DIR / f"raw_{safe_name(label)}.json").write_text(
                json.dumps({"label": label, "public": info, "pois": pois, "line_ids": line_ids, "directions": directions}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except AmapDailyQuotaError as exc:
            row["status"] = "daily_quota"
            row["notes"] = str(exc)
            summaries.append(row)
            print("  DAILY QUOTA:", exc)
            break
        except Exception as exc:
            row["status"] = "error"
            row["notes"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            print("  ERROR:", row["notes"])
        summaries.append(row)

    summary_path = OUT_DIR / "summary.csv"
    pd.DataFrame(summaries).to_csv(summary_path, index=False, encoding="utf-8-sig")
    print("=" * 80)
    print("API calls this run:", client.calls)
    print("wrote:", summary_path)
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    main()
