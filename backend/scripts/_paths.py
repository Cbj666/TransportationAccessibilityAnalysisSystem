# -*- coding: utf-8 -*-
"""Shared paths for the pipeline scripts (sibling importable from ``scripts/``).

Every script does::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend/
    from _paths import BOUNDARY, INTERIM, OUTPUT, V1, OSM_GPKG

so the same script works from any working directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
DATA = PROJECT / "data"

RAW = DATA / "raw"
INTERIM = DATA / "interim"
OUTPUT = DATA / "output"
CACHE = DATA / "cache"

V1 = DATA / "processed" / "v1"
GRAPH_CACHE = DATA / "processed" / "graph"

# raw inputs
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
OSM_PBF = RAW / "hubei" / "hubei-261013.osm.pbf"

# Amap interim tables
AMAP_PILOT = INTERIM / "amap_pilot"
AMAP_METRO = INTERIM / "amap_metro"

# make ``import app`` work from any script in this folder
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
