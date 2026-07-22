"""Lokale zichtlijngeometrie tussen een station en een 3D-punt."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .coordinates import GeodeticCoordinate, ecef_to_enu, wgs84_to_ecef


@dataclass(frozen=True, slots=True)
class LookAngle:
    """Slant range in metres and local azimuth/elevation in degrees."""

    distance_m: float
    azimuth_deg: float
    elevation_deg: float
    east_m: float
    north_m: float
    up_m: float

    @property
    def visible_above_geometric_horizon(self) -> bool:
        """Whether the target has a non-negative geometric elevation."""

        return self.elevation_deg >= 0.0


def look_angle(origin: GeodeticCoordinate, target: GeodeticCoordinate) -> LookAngle:
    """Calculate the local line of sight from ``origin`` to ``target``.

    Both positions are WGS84 geodetic coordinates with altitude in metres.
    The target difference vector is rotated from ECEF to local East-North-Up
    at the origin. Azimuth is clockwise from geodetic north in [0, 360),
    elevation is relative to the local ellipsoidal horizon, and distance is
    the straight three-dimensional slant range in metres.
    """

    east_m, north_m, up_m = ecef_to_enu(wgs84_to_ecef(target), origin)
    horizontal_m = math.hypot(east_m, north_m)
    distance_m = math.hypot(horizontal_m, up_m)
    if distance_m < 1e-9:
        raise ValueError("origin and target must be different positions")
    azimuth_deg = math.degrees(math.atan2(east_m, north_m)) % 360.0
    elevation_deg = math.degrees(math.atan2(up_m, horizontal_m))
    return LookAngle(
        distance_m=distance_m,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        east_m=east_m,
        north_m=north_m,
        up_m=up_m,
    )
