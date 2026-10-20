from pathlib import Path
import json
import zipfile

keywords = ("h50", "武汉", "wuhan", "250", "25万", "geojson")
for path in sorted(Path(".").iterdir()):
    if not path.is_file():
        continue
    name = path.name
    if any(k.lower() in name.lower() for k in keywords):
        print("=" * 80)
        print("FILE:", name)
        print("SIZE:", path.stat().st_size)
        suffix = path.suffix.lower()
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    for info in zf.infolist()[:40]:
                        print("  ZIP:", info.filename, info.file_size)
            except Exception as exc:
                print("  ZIP error:", exc)
        elif suffix in (".json", ".geojson"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                print("  type:", payload.get("type"))
                if payload.get("type") == "FeatureCollection":
                    features = payload.get("features", [])
                    print("  features:", len(features))
                    if features:
                        print("  first properties:", features[0].get("properties"))
                        print("  first geometry:", features[0].get("geometry", {}).get("type"))
                print("  crs:", payload.get("crs"))
            except Exception as exc:
                print("  JSON error:", exc)
