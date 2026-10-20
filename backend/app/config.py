# -*- coding: utf-8 -*-
"""Tunable parameters for the multimodal graph and isochrone engine.

Every value here is a modelling assumption, not measured data. They are
collected in one dataclass so the API can override them per request and the
report can print exactly what was used.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Params:
    # --- walking -----------------------------------------------------------
    walk_speed_mps: float = 1.2          # 4.3 km/h, average pedestrian
    walk_access_max_m: float = 800.0     # ignore stops further than this from a walk node

    # --- bus ---------------------------------------------------------------
    bus_speed_mps: float = 4.5           # 16.2 km/h, includes signal delay
    bus_dwell_s: float = 25.0            # per intermediate stop
    bus_wait_s: float = 480.0            # 8 min headway/2, no timetable available

    # --- metro -------------------------------------------------------------
    metro_speed_mps: float = 9.5         # 34.2 km/h
    metro_dwell_s: float = 35.0
    metro_wait_fallback_s: float = 240.0  # used when a line has no schedule row

    # --- transfer ----------------------------------------------------------
    transfer_penalty_s: float = 90.0     # extra friction when changing route

    # --- rendering ---------------------------------------------------------
    hull_buffer_m: float = 60.0
    hull_simplify_m: float = 40.0
    hull_max_points: int = 80_000        # sample for the concave hull

    def ride_time(self, mode: str, distance_m: float) -> float:
        """Seconds spent inside the vehicle for one leg."""
        if mode == "bus":
            return distance_m / self.bus_speed_mps + self.bus_dwell_s
        if mode == "metro":
            return distance_m / self.metro_speed_mps + self.metro_dwell_s
        raise ValueError(f"unknown ride mode: {mode}")

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT = Params()
