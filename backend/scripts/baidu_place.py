from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]  # project root
CACHE_DIR = ROOT / "data" / "cache" / "baidu_place"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class BaiduApiError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(f"Baidu API error {status}: {message}")


class BaiduQuotaError(BaiduApiError):
    pass


def load_ak() -> str:
    for name in (".env", ".env.txt", "AK.txt"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            value = line.split("=", 1)[1].strip() if "=" in line else line
            if value:
                return value
    raise RuntimeError("未找到百度服务端 AK，请检查 .env/.env.txt")


def cache_keys(query: str, region: str, page_size: int, scope: int, tag: str | None) -> list[str]:
    base = f"{query}|{region}|{page_size}|{scope}"
    keys = [hashlib.sha1(base.encode("utf-8")).hexdigest()]
    if tag:
        keys.append(hashlib.sha1(f"{base}|{tag}".encode("utf-8")).hexdigest())
    return keys


class BaiduPlaceClient:
    def __init__(self, ak: str | None = None, interval: float = 0.4, offline: bool = False):
        self.ak = ak or load_ak()
        self.interval = interval
        self.offline = offline
        self._last_call = 0.0

    def _wait(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last_call = time.monotonic()

    def search(self, query: str, region: str = "武汉市", page_size: int = 20, scope: int = 2, tag: str | None = None) -> dict:
        keys = cache_keys(query, region, page_size, scope, tag)
        for key in keys:
            cache_path = CACHE_DIR / f"{key}.json"
            if not cache_path.exists():
                continue
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            # never reuse a cached quota/error response
            if payload.get("status") == 0:
                return payload
        if self.offline:
            raise BaiduApiError(-1, f"offline cache miss: {query}")

        self._wait()
        params = {
            "query": query,
            "region": region,
            "output": "json",
            "scope": str(scope),
            "page_size": str(page_size),
            "page_num": "0",
            "ak": self.ak,
        }
        if tag:
            params["tag"] = tag
        url = "https://api.map.baidu.com/place/v2/search?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": "wuhan-isochrone-course-project/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))

        status = payload.get("status")
        if status != 0:
            message = str(payload.get("message", ""))
            if status in (302, 401) or "配额" in message or "限制" in message:
                raise BaiduQuotaError(status, message)
            raise BaiduApiError(status, message)

        # write only successful responses; legacy key keeps compatibility with earlier cache
        primary = CACHE_DIR / f"{keys[-1]}.json"
        primary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
