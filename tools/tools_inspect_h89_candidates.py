import json
from pathlib import Path

payload = json.loads(Path("data/cache/pilot_candidates.json").read_text(encoding="utf-8"))
stations = payload["stations"]
candidates = payload["candidates"]
targets = {"陈东路东风大队", "东西湖大道新沟桥", "东西湖大道荷包湖三大队", "东西湖大道吴新干线", "东西湖大道全球保税商品中心", "三秀路公交停车场", "三秀路荷花园"}
for station, items in zip(stations, candidates):
    if station not in targets:
        continue
    print("=" * 80)
    print("STATION:", station)
    for item in items:
        print(
            f"  {item['similarity']:.2f} | bus={item['is_bus_stop']} | {item['name']} | "
            f"{item['area']} | {item['address'][:120]}"
        )
