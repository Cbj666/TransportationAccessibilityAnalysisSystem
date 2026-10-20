from pathlib import Path
import hashlib
import json
import urllib.parse
import urllib.request


CACHE = Path("data/cache/amap_bus")
CACHE.mkdir(parents=True, exist_ok=True)


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


def fetch(keyword):
    key = load_key()
    params = {
        "key": key,
        "city": "420100",
        "keywords": keyword,
        "extensions": "all",
        "offset": "20",
        "page": "1",
        "output": "json",
    }
    url = "https://restapi.amap.com/v3/bus/linename?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "wuhan-isochrone-course-project/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    cache = CACHE / f"{hashlib.sha1(keyword.encode('utf-8')).hexdigest()}.json"
    cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main():
    import sys
    import time

    keywords = sys.argv[1:] or ["H89", "H82", "P101"]
    for index, keyword in enumerate(keywords):
        if index:
            time.sleep(2)
        payload = fetch(keyword)
        print("=" * 80)
        print("QUERY:", keyword, "status:", payload.get("status"), "info:", payload.get("info"), "count:", payload.get("count"))
        for line in payload.get("buslines", []):
            stops = line.get("busstops", [])
            print(
                "  ", line.get("name"),
                "| stations:", len(stops),
                "|", line.get("start_stop"), "->", line.get("end_stop"),
                "| loop:", line.get("loop"),
            )
            if stops:
                print("     first:", stops[0].get("name"), stops[0].get("location"), "last:", stops[-1].get("name"), stops[-1].get("location"))


if __name__ == "__main__":
    main()
