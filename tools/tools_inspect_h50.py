from pathlib import Path
import zipfile

import pyogrio

root = Path("data/raw/h50c002001")
root.mkdir(parents=True, exist_ok=True)
zip_path = Path("20261019213541093/h50c002001.zip")
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(root)

for shp in sorted(root.rglob("*.shp")):
    print("=" * 80)
    print(shp.name)
    info = pyogrio.read_info(shp)
    print("features:", info.get("features"), "crs:", info.get("crs"))
    print("geometry_type:", info.get("geometry_type"))
    print("fields:", list(info.get("fields", [])))
    print("dtypes:", list(info.get("dtypes", [])))
    print("total_bounds:", info.get("total_bounds"))
    try:
        df = pyogrio.read_dataframe(shp, max_features=3)
        print(df.drop(columns="geometry", errors="ignore").to_string(index=False))
    except Exception as exc:
        print("read sample error:", exc)
