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


def get(url, params):
    params = dict(params)
    params["key"] = load_key()
    params["output"] = "json"
    full = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full, headers={"User-Agent": "wuhan-isochrone-course-project/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    print("== bus/lineid ==")
    payload = get("https://restapi.amap.com/v3/bus/lineid", {"id": "420100014315", "extensions": "all"})
    print("status:", payload.get("status"), "info:", payload.get("info"), "count:", payload.get("count"))
    for line in payload.get("buslines", []):
        stops = line.get("busstops", [])
        print("name:", line.get("name"), "id:", line.get("id"), "stations:", len(stops), "loop:", line.get("loop"))
        if stops:
            print("  first:", stops[0])
            print("  last:", stops[-1])

    time.sleep(2)
    print("\n== bus/stopid ==")
    payload = get("https://restapi.amap.com/v3/bus/stopid", {"id": "BV11339078"})
    print("status:", payload.get("status"), "info:", payload.get("info"), "count:", payload.get("count"))
    for stop in payload.get("busstops", []):
        print("stop:", stop.get("name"), "id:", stop.get("id"), "location:", stop.get("location"))
        for line in stop.get("buslines", [])[:8]:
            print("  line:", line.get("name"), "id:", line.get("id"), "start:", line.get("start_stop"), "end:", line.get("end_stop"))


if __name__ == "__main__":
    main()
