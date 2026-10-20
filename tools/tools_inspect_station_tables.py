from pathlib import Path
import csv
import io
import zipfile


def read_csv_from_zip(path):
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not members:
            return None, None, []
        raw = zf.read(members[0])

    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"无法解码 {path}")

    rows = list(csv.reader(io.StringIO(text)))
    return members[0], encoding, rows


def main():
    for path in sorted(Path(".").glob("*.zip")):
        if "公交" not in path.name and "轨道" not in path.name:
            continue
        member, encoding, rows = read_csv_from_zip(path)
        print("=" * 70)
        print(path.name)
        print("member:", member)
        print("encoding:", encoding)
        print("row_count:", len(rows))
        for row in rows[:6]:
            print(row)


if __name__ == "__main__":
    main()
