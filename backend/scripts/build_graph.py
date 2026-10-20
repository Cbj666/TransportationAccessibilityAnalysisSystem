# -*- coding: utf-8 -*-
"""Build (and cache) the multimodal graph from the frozen v1 dataset."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT  # noqa: E402
from app.graph import CACHE, build  # noqa: E402


def main() -> None:
    t0 = time.time()
    g = build(params=DEFAULT, verbose=True)
    out = CACHE / "v1" / "multimodal.npz"
    g.save(out)
    print(f"\nwrote {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"meta {out.with_suffix('.meta.pkl')}")
    print(f"elapsed {time.time() - t0:.1f}s")

    # quick sanity: origin at 武汉大学, how far can we get on foot alone?
    import numpy as np

    from app.isochrone import nearest_walk_node, travel_times

    o, snap = nearest_walk_node(g, 114.3610, 30.5390)
    dist, _ = travel_times(g, o)
    for b in (900, 1800, 2700):
        n = int(np.sum((g.kind == 0) & (dist <= b)))
        stops = int(np.sum(np.isin(g.kind, (1, 2)) & (dist <= b)))
        print(f"  {b // 60:>2} min: walk nodes {n:>7,}  stops {stops:>5,}")


if __name__ == "__main__":
    main()
