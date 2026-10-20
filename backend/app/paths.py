# -*- coding: utf-8 -*-
"""Single source of truth for every path used by the backend.

Layout
    <project>/backend/app          this package
    <project>/backend/scripts      pipeline + pilot scripts
    <project>/data/raw             immutable downloads (gitignored)
    <project>/data/interim         merged Amap tables (gitignored, regenerable)
    <project>/data/processed/v1    frozen dataset (committed)
    <project>/data/processed/graph cached multimodal graph (gitignored)
    <project>/data/output          maps, isochrones, QA reports (committed)
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent

DATA = PROJECT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
OUTPUT = DATA / "output"

V1 = DATA / "processed" / "v1"
GRAPH_CACHE = DATA / "processed" / "graph"

# raw inputs
BOUNDARY = RAW / "boundary" / "武汉市_市.geojson"
OSM_GPKG = RAW / "hubei" / "hubei-261013-free-OpenMap" / "hubei.gpkg"
OSM_PBF = RAW / "hubei" / "hubei-261013.osm.pbf"

# Amap interim tables
AMAP_PILOT = INTERIM / "amap_pilot"
AMAP_METRO = INTERIM / "amap_metro"


def ensure_dirs() -> None:
    """Create the writable directories the pipeline expects."""
    for p in (OUTPUT, INTERIM, V1, GRAPH_CACHE):
        p.mkdir(parents=True, exist_ok=True)
