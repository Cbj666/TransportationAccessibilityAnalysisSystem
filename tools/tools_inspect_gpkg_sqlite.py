from pathlib import Path
import sqlite3


def main():
    gpkg = Path("hubei-261013-free-OpenMap/hubei.gpkg")
    print("exists:", gpkg.exists(), "size:", gpkg.stat().st_size if gpkg.exists() else None)
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    cur = con.cursor()

    print("\n== gpkg_contents ==")
    for row in cur.execute("SELECT table_name, data_type, identifier, min_x, min_y, max_x, max_y FROM gpkg_contents"):
        print(row)

    tables = [row[0] for row in cur.execute("SELECT table_name FROM gpkg_contents")]
    for table in tables:
        print(f"\n== {table} ==")
        cols = list(cur.execute(f'PRAGMA table_info("{table}")'))
        print("columns:", [c[1] for c in cols])
        count = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        print("rows:", count)
        names = [c[1] for c in cols]
        if "fclass" in names:
            print("top fclass:")
            for row in cur.execute(f'SELECT fclass, COUNT(*) FROM "{table}" GROUP BY fclass ORDER BY COUNT(*) DESC LIMIT 30'):
                print("  ", row)
            for target in ("bus_stop", "bus_station", "railway_station", "subway_entrance", "station"):
                hit = cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE fclass=?', (target,)).fetchone()[0]
                if hit:
                    print(f"  {target}: {hit}")
    con.close()


if __name__ == "__main__":
    main()
