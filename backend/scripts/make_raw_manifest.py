# -*- coding: utf-8 -*-
"""Generate a SHA-256 manifest for the raw inputs that are handed out offline.

`data/raw/` and `data/interim/amap_pilot/` are gitignored because they are
too large for the repository; teammates copy them from a shared drive. This
script writes a small committed file so they can verify the copy:

    data/raw-inputs.sha256      "hash  size  relative/path"

Verify from `data/raw/`:

    sha256sum -c ../raw-inputs.sha256          # Git Bash / Linux / macOS
    Get-FileHash ...                           # or see data/README.md

Only the inputs needed to rebuild the frozen dataset are hashed by default.
The 11 GB `cptond/` archive is not used by the pipeline and is skipped.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

DEFAULT_DIRS = [
    "hubei",          # OSM 提取：hubei.gpkg（重建 v1 必需）
    "boundary",       # 武汉市行政边界（必需）
    "public_transit", # 公开公交/轨道数据（对照用）
    "h50",            # 1:25 万矢量地图（制图用，非必需）
]
SKIP = {"cptond"}     # 11 GB，未参与任何流程


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not RAW.exists():
        print(f"missing: {RAW}", file=sys.stderr)
        return 1
    entries: list[tuple[str, int, str]] = []
    for d in DEFAULT_DIRS:
        base = RAW / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(RAW).as_posix()
            entries.append((sha256(p), p.stat().st_size, rel))
            print(f"  {rel}")
    out = ROOT / "data" / "raw-inputs.sha256"
    lines = [f"{h}  {size}  {rel}" for h, size, rel in entries]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(e[1] for e in entries) / 1024**3
    print(f"\n{len(entries)} files, {total:.2f} GB -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
