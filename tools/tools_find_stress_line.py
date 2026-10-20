from pathlib import Path
import csv
import io
import zipfile
from collections import Counter


def main():
    path = next(p for p in Path(".").glob("*.zip") if "公交" in p.name)
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        rows = list(csv.DictReader(io.StringIO(zf.read(member).decode("utf-8-sig"))))

    stats = []
    for row in rows:
        stations = [s.strip() for s in row["tkzd"].split("、") if s.strip()]
        duplicates = [name for name, count in Counter(stations).items() if count > 1]
        stats.append((len(stations), len(set(stations)), row["xlh"], row["xlxx"], len(duplicates), duplicates[:3]))

    print("longest lines:")
    for item in sorted(stats, reverse=True)[:12]:
        print(item)
    print("\nlines with duplicate station names:")
    for item in [s for s in stats if s[4] > 0][:12]:
        print(item)


if __name__ == "__main__":
    main()
