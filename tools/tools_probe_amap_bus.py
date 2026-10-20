from pathlib import Path
import json
import urllib.parse
import urllib.request


def load_key():
    for name in (".env", ".env.txt"):
        path = Path(name)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in ("GAODE_KEY", "AMAP_KEY", "GAODE_WEB_KEY"):
                    return value.strip()
    raise RuntimeError("未找到 GAODE_KEY")


def main():
    key = load_key()
    print("key loaded: yes, length:", len(key))
    params = {
        "key": key,
        "city": "420100",
        "keywords": "340",
        "extensions": "all",
        "offset": "20",
        "page": "1",
        "output": "json",
    }
    url = "https://restapi.amap.com/v3/bus/linename?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "wuhan-isochrone-course-project/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    print("status:", payload.get("status"), "info:", payload.get("info"), "infocode:", payload.get("infocode"))
    print("count:", payload.get("count"))
    for line in payload.get("buslines", []):
        stops = line.get("busstops", [])
        print("=" * 70)
        print("name:", line.get("name"), "type:", line.get("type"))
        print("start_stop:", line.get("start_stop"), "end_stop:", line.get("end_stop"))
        print("distance:", line.get("distance"), "loop:", line.get("loop"), "direc:", line.get("direc"))
        print("station_count:", len(stops))
        for stop in stops[:5] + stops[-3:]:
            print("  ", stop.get("sequence"), stop.get("name"), stop.get("location"), stop.get("id"))


if __name__ == "__main__":
    main()
