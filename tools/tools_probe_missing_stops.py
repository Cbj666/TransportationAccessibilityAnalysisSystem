from pathlib import Path
import json
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from baidu_place import BaiduPlaceClient, load_ak

ak = load_ak()
client = BaiduPlaceClient(ak)


def geocode(address):
    params = {"address": address, "city": "武汉市", "output": "json", "ret_coordtype": "bd09ll", "ak": ak}
    url = "https://api.map.baidu.com/geocoding/v3/?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


for station in ["陈东路莲湖路", "东西湖大道全球保税商品中心", "三秀路公交停车场", "三秀路荷花园"]:
    print("=" * 80)
    print("STATION:", station)
    for label, query, tag in [
        ("with 公交站", f"{station} 公交站", None),
        ("plain", station, None),
        ("tag=公交站", station, "公交站"),
    ]:
        payload = client.search(query, page_size=10, tag=tag)
        print(f"-- {label}: total={payload.get('total')}")
        for item in payload.get("results", [])[:5]:
            loc = item.get("location", {})
            detail = item.get("detail_info", {})
            print(f"   {item.get('name')} | {loc.get('lng')},{loc.get('lat')} | {detail.get('tag','')} | {item.get('address','')[:90]}")
    result = geocode(station)
    print("-- geocode:", result.get("status"), result.get("result", {}).get("location"), result.get("result", {}).get("level"))
