from pathlib import Path
import csv
import io
import json
import re
import sqlite3
import struct
import zipfile
from collections import Counter, defaultdict


def decode_text(raw):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("decode failed")


def read_zip_table(keyword, suffix=".csv"):
    for path in Path(".").glob("*.zip"):
        if keyword in path.name:
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(suffix)]
                if names:
                    return path, decode_text(zf.read(names[0]))
    raise FileNotFoundError(keyword)


def parse_gpkg_point(blob):
    if blob is None or blob[:2] != b"GP":
        return None
    flags = blob[3]
    little = bool(flags & 0x01)
    envelope_code = (flags >> 1) & 0x07
    envelope_sizes = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}
    offset = 8 + envelope_sizes.get(envelope_code, 0) * 8
    if flags & 0x10:
        return None
    wkb = blob[offset:]
    if not wkb:
        return None
    endian = "<" if wkb[0] == 1 else ">"
    geom_type = struct.unpack(endian + "I", wkb[1:5])[0]
    base_type = geom_type & 0xFF
    if base_type != 1:
        return None
    x, y = struct.unpack(endian + "dd", wkb[5:21])
    return x, y


def normalize_name(name):
    value = str(name or "").strip()
    value = value.replace("（", "(").replace("）", ")").replace("　", "")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"\(.*?\)", "", value)
    value = value.replace("公交车站", "").replace("公交站", "")
    value = re.sub(r"站$", "", value)
    return value


def load_osm_transport():
    gpkg = Path("hubei-261013-free-OpenMap/hubei.gpkg")
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT fclass, name, geom FROM gis_osm_transport_free WHERE fclass IN ('bus_stop','bus_station','railway_station')"
    ).fetchall()
    con.close()
    points = []
    for fclass, name, geom in rows:
        xy = parse_gpkg_point(geom)
        if xy is None or not name:
            continue
        points.append({"fclass": fclass, "name": name, "lon": xy[0], "lat": xy[1]})
    return points


def main():
    _, bus_text = read_zip_table("公交")
    bus_rows = list(csv.DictReader(io.StringIO(bus_text)))
    station_mentions = Counter()
    for row in bus_rows:
        names = [s.strip() for s in row["tkzd"].split("、") if s.strip()]
        station_mentions.update(names)

    _, metro_text = read_zip_table("轨道")
    metro_rows = list(csv.DictReader(io.StringIO(metro_text)))
    metro_names = Counter(row["cz"].strip() for row in metro_rows)

    osm = load_osm_transport()
    print("OSM transport points with names:", len(osm))
    print("OSM fclass counts:", Counter(p["fclass"] for p in osm))

    osm_by_name = defaultdict(list)
    osm_by_norm = defaultdict(list)
    for p in osm:
        osm_by_name[p["name"].strip()].append(p)
        osm_by_norm[normalize_name(p["name"])].append(p)

    def match_stats(counter, label):
        exact = 0
        normalized_only = 0
        unmatched = []
        ambiguous = 0
        matched_mentions = 0
        total_mentions = sum(counter.values())
        for name, count in counter.items():
            if name in osm_by_name:
                exact += 1
                matched_mentions += count
                if len(osm_by_name[name]) > 1:
                    ambiguous += 1
            elif normalize_name(name) in osm_by_norm:
                normalized_only += 1
                matched_mentions += count
                if len(osm_by_norm[normalize_name(name)]) > 1:
                    ambiguous += 1
            else:
                unmatched.append((name, count))
        print(f"\n== {label} ==")
        print("unique names:", len(counter), "mentions:", total_mentions)
        print("exact matches:", exact, "normalized-only matches:", normalized_only)
        print("unique matched:", exact + normalized_only, f"({(exact+normalized_only)/len(counter):.1%})")
        print("mentions matched:", matched_mentions, f"({matched_mentions/total_mentions:.1%})")
        print("ambiguous names with >1 OSM point:", ambiguous)
        print("unmatched unique:", len(unmatched))
        print("unmatched top mentions:", sorted(unmatched, key=lambda x: -x[1])[:15])
        return unmatched

    bus_unmatched = match_stats(station_mentions, "BUS unique station names")
    metro_unmatched = match_stats(metro_names, "METRO unique station names")

    out = Path("data/interim")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "osm_transport_points.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fclass", "name", "lon", "lat"])
        writer.writeheader()
        writer.writerows(osm)
    with (out / "bus_stations_unmatched_osm.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["station_name", "mentions"])
        writer.writerows(bus_unmatched)
    print("\nwrote:", out / "osm_transport_points.csv")
    print("wrote:", out / "bus_stations_unmatched_osm.csv")


if __name__ == "__main__":
    main()
