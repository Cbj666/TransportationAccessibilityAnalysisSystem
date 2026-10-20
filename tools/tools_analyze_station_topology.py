from pathlib import Path
import csv
import io
import json
import zipfile
from collections import Counter, defaultdict


def load_member(zip_path, suffix):
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(suffix)]
        if not names:
            return None, None
        return names[0], zf.read(names[0])


def decode(raw):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("decode failed")


def find_zip(keyword):
    for path in Path(".").glob("*.zip"):
        if keyword in path.name:
            return path
    raise FileNotFoundError(keyword)


def inspect_bus():
    path = find_zip("公交")
    print("=" * 70)
    print("BUS", path.name)
    member, raw = load_member(path, ".json")
    print("json member:", member)
    payload = json.loads(decode(raw))
    if isinstance(payload, dict):
        print("json top-level keys:", list(payload.keys())[:20])
        for key, value in payload.items():
            if isinstance(value, list) and value:
                print("list key:", key, "len:", len(value), "first keys:", list(value[0].keys()) if isinstance(value[0], dict) else type(value[0]))
                print("first record:", value[0])
                break
    elif isinstance(payload, list):
        print("json list len:", len(payload), "first keys:", list(payload[0].keys()) if payload and isinstance(payload[0], dict) else None)
        print("first record:", payload[0] if payload else None)

    member, raw = load_member(path, ".csv")
    rows = list(csv.DictReader(io.StringIO(decode(raw))))
    print("csv rows:", len(rows))
    lines = [r["xlh"].strip() for r in rows]
    line_counts = Counter(lines)
    duplicates = {k: v for k, v in line_counts.items() if v > 1}
    print("unique line labels:", len(line_counts), "duplicated labels:", len(duplicates))
    print("duplicate examples:", list(duplicates.items())[:10])

    stations = []
    station_counts = Counter()
    for row in rows:
        names = [s.strip() for s in row["tkzd"].split("、") if s.strip()]
        stations.append(names)
        station_counts.update(names)
    print("total station mentions:", sum(station_counts.values()))
    print("unique station names:", len(station_counts))
    print("top repeated names:", station_counts.most_common(10))

    # identical station lists may indicate duplicate directions or duplicate records
    signatures = Counter(tuple(s) for s in stations)
    same = [(sig, n) for sig, n in signatures.items() if n > 1]
    print("identical station sequences:", len(same))
    if same:
        print("example length:", len(same[0][0]), "count:", same[0][1])

    # compare lines sharing the same name: are sequences reversed?
    by_line = defaultdict(list)
    for row, seq in zip(rows, stations):
        by_line[row["xlh"].strip()].append(seq)
    reversed_pairs = 0
    examples = []
    for line, seqs in by_line.items():
        if len(seqs) < 2:
            continue
        for i in range(len(seqs)):
            for j in range(i + 1, len(seqs)):
                if seqs[i] == list(reversed(seqs[j])):
                    reversed_pairs += 1
                    if len(examples) < 5:
                        examples.append((line, len(seqs[i])))
    print("reversed direction pairs:", reversed_pairs)
    print("reversed examples:", examples)

    lengths = [len(s) for s in stations]
    print("stations per route min/median/max:", min(lengths), sorted(lengths)[len(lengths)//2], max(lengths))


def inspect_metro():
    path = find_zip("轨道")
    print("=" * 70)
    print("METRO", path.name)
    member, raw = load_member(path, ".json")
    print("json member:", member)
    payload = json.loads(decode(raw))
    if isinstance(payload, dict):
        print("json top-level keys:", list(payload.keys())[:20])
        for key, value in payload.items():
            if isinstance(value, list) and value:
                print("list key:", key, "len:", len(value), "first keys:", list(value[0].keys()) if isinstance(value[0], dict) else type(value[0]))
                print("first record:", value[0])
                break
    elif isinstance(payload, list):
        print("json list len:", len(payload), "first keys:", list(payload[0].keys()) if payload and isinstance(payload[0], dict) else None)
        print("first record:", payload[0] if payload else None)

    member, raw = load_member(path, ".csv")
    rows = list(csv.DictReader(io.StringIO(decode(raw))))
    print("csv rows:", len(rows))
    names = Counter(r["cz"].strip() for r in rows)
    lines = Counter(r["xl"].strip() for r in rows)
    print("unique station names:", len(names), "unique lines:", len(lines))
    print("lines:", sorted(lines.items(), key=lambda x: (len(x[0]), x[0])))
    print("transfer station examples:", [(n, c) for n, c in names.most_common(10) if c > 1])

    by_line = defaultdict(list)
    for row in rows:
        by_line[row["xl"].strip()].append((row["id"].strip(), row["cz"].strip()))
    for line, items in sorted(by_line.items(), key=lambda x: (len(x[0]), x[0])):
        ids = [i for i, _ in items]
        print("line", line, "stations", len(items), "id range", min(ids), max(ids), "first", items[:3], "last", items[-2:])


if __name__ == "__main__":
    inspect_bus()
    inspect_metro()
