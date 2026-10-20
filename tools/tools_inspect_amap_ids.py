from pathlib import Path
import json


for path in sorted(Path("data/cache/amap_bus").glob("*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    for line in payload.get("buslines", []):
        name = line.get("name", "")
        if not any(key in name for key in ("340", "H89", "H82", "P101")):
            continue
        stops = line.get("busstops", [])
        print("=" * 80)
        print("name:", name)
        print("id:", line.get("id"), "direc:", line.get("direc"), "loop:", line.get("loop"))
        print("start_stop:", line.get("start_stop"), "end_stop:", line.get("end_stop"))
        print("busstops:", len(stops))
        if stops:
            print("first stop keys:", list(stops[0].keys()))
            print("first stop:", stops[0])
            print("last stop:", stops[-1])
