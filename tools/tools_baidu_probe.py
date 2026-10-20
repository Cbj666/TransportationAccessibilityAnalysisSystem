from pathlib import Path
import json
import os
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent
ENV_CANDIDATES = [ROOT / ".env", ROOT / ".env.txt", ROOT / "AK.txt"]


def load_env(paths):
    values = {}
    used = []
    for path in paths:
        if not path.exists():
            continue
        used.append(path.name)
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
            elif "BAIDU_SERVER_AK" not in values:
                values["BAIDU_SERVER_AK"] = line
        break
    return values, used


def get_json(url, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "wuhan-isochrone-course-project/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def redact(payload):
    text = json.dumps(payload, ensure_ascii=False)
    for marker in ("ak=", "AK="):
        if marker in text:
            text = text.replace(marker, marker + "***")
    return text


def main():
    env, used = load_env(ENV_CANDIDATES)
    print("env files:", used)
    print("variable names:", list(env.keys()))
    ak = env.get("BAIDU_SERVER_AK") or env.get("BAIDU_AK") or env.get("BAIDU_MAP_AK")
    if not ak:
        print("AK variable not found.")
        return
    print("AK loaded:", "yes", "length:", len(ak))

    print("\n== geocoding ==")
    try:
        data = get_json(
            "https://api.map.baidu.com/geocoding/v3/",
            {
                "address": "珞喻路光谷广场",
                "city": "武汉市",
                "output": "json",
                "ret_coordtype": "bd09ll",
                "ak": ak,
            },
        )
        print(redact(data))
    except Exception as exc:
        print("geocoding error:", type(exc).__name__, str(exc)[:300])

    print("\n== place search ==")
    try:
        data = get_json(
            "https://api.map.baidu.com/place/v2/search",
            {
                "query": "珞喻路光谷广场 公交站",
                "region": "武汉市",
                "output": "json",
                "scope": "2",
                "page_size": "10",
                "page_num": "0",
                "ak": ak,
            },
        )
        print(redact(data))
    except Exception as exc:
        print("place search error:", type(exc).__name__, str(exc)[:300])


if __name__ == "__main__":
    main()
