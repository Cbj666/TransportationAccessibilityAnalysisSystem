from pathlib import Path
import json
import time
import urllib.parse
import urllib.request


def load_key():
    for name in (".env", ".env.txt"):
        path = Path(name)
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() in ("GAODE_KEY", "AMAP_KEY", "GAODE_WEB_KEY"):
                        return value.strip()
    raise RuntimeError("未找到 GAODE_KEY")


def main():
    time.sleep(2)
    params = {
        "key": load_key(),
        "keywords": "340路",
        "city": "420100",
        "citylimit": "true",
        "types": "150700",
        "offset": "20",
        "page": "2",
        "extensions": "all",
        "output": "json",
    }
    url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "wuhan-isochrone-course-project/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print("status:", payload.get("status"), "info:", payload.get("info"), "count:", payload.get("count"))
    for poi in payload.get("pois", []):
        print(poi.get("name"), "|", poi.get("id"), "|", poi.get("location"), "|", poi.get("address"))


if __name__ == "__main__":
    main()
