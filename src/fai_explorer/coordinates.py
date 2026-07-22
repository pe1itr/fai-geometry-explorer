"""Coordinatentransformaties voor de FAI-rekenkern."""

from __future__ import annotations

from dataclasses import dataclass
import math

WGS84_SEMI_MAJOR_AXIS_M = 6_378_137.0
WGS84_INVERSE_FLATTENING = 298.257_223_563
WGS84_FLATTENING = 1.0 / WGS84_INVERSE_FLATTENING
WGS84_ECCENTRICITY_SQUARED = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)


@dataclass(frozen=True, slots=True)
class GeodeticCoordinate:
    """WGS84-coordinate in degrees and ellipsoid altitude in metres."""

    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("latitude_deg must be between -90 and 90")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("longitude_deg must be between -180 and 180")
        if not all(
            math.isfinite(value)
            for value in (self.latitude_deg, self.longitude_deg, self.altitude_m)
        ):
            raise ValueError("coordinate values must be finite")


def maidenhead_to_wgs84(locator: str, altitude_m: float = 0.0) -> GeodeticCoordinate:
    """Return the WGS84 centre of a 2, 4, 6 or 8 character locator.

    Longitude is subdivided before latitude in every Maidenhead pair. Letter
    pairs use 18 fields for the first pair and 24 subdivisions thereafter;
    numeric pairs use 10 subdivisions. Altitude is passed through in metres.
    """

    value = locator.strip()
    if len(value) not in (2, 4, 6, 8):
        raise ValueError("Maidenhead locator must contain 2, 4, 6 or 8 characters")

    lon_deg = -180.0
    lat_deg = -90.0
    lon_size_deg = 20.0
    lat_size_deg = 10.0

    for pair_index in range(len(value) // 2):
        lon_char, lat_char = value[2 * pair_index : 2 * pair_index + 2]
        if pair_index == 0:
            lon_index = _letter_index(lon_char, 18, "field")
            lat_index = _letter_index(lat_char, 18, "field")
        elif pair_index % 2 == 1:
            if not lon_char.isascii() or not lat_char.isascii() or not (
                lon_char.isdigit() and lat_char.isdigit()
            ):
                raise ValueError(f"pair {pair_index + 1} must contain ASCII digits")
            lon_index = int(lon_char)
            lat_index = int(lat_char)
            lon_size_deg /= 10.0
            lat_size_deg /= 10.0
        else:
            lon_index = _letter_index(lon_char, 24, "subsquare")
            lat_index = _letter_index(lat_char, 24, "subsquare")
            lon_size_deg /= 24.0
            lat_size_deg /= 24.0

        lon_deg += lon_index * lon_size_deg
        lat_deg += lat_index * lat_size_deg

    return GeodeticCoordinate(
        latitude_deg=lat_deg + lat_size_deg / 2.0,
        longitude_deg=lon_deg + lon_size_deg / 2.0,
        altitude_m=altitude_m,
    )


def wgs84_to_maidenhead(
    latitude_deg: float, longitude_deg: float, precision: int = 6
) -> str:
    """Encode WGS84 latitude/longitude as a Maidenhead locator.

    ``precision`` is the total character count and must be 2, 4, 6 or 8.
    Latitude/longitude are in degrees. Altitude has no Maidenhead encoding.
    """

    if precision not in (2, 4, 6, 8):
        raise ValueError("precision must be 2, 4, 6 or 8")
    if not math.isfinite(latitude_deg) or not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("latitude_deg must be finite and between -90 and 90")
    if not math.isfinite(longitude_deg) or not -180.0 <= longitude_deg <= 180.0:
        raise ValueError("longitude_deg must be finite and between -180 and 180")

    # The north/east edges belong to the final valid cell.
    lat = min(latitude_deg + 90.0, math.nextafter(180.0, 0.0))
    lon = min(longitude_deg + 180.0, math.nextafter(360.0, 0.0))
    result: list[str] = []
    lon_size_deg = 20.0
    lat_size_deg = 10.0

    for pair_index in range(precision // 2):
        if pair_index > 0:
            divisor = 10.0 if pair_index % 2 == 1 else 24.0
            lon_size_deg /= divisor
            lat_size_deg /= divisor

        lon_index = min(int(lon / lon_size_deg), 17 if pair_index == 0 else (9 if pair_index % 2 else 23))
        lat_index = min(int(lat / lat_size_deg), 17 if pair_index == 0 else (9 if pair_index % 2 else 23))
        lon -= lon_index * lon_size_deg
        lat -= lat_index * lat_size_deg

        if pair_index == 0:
            result.extend((chr(ord("A") + lon_index), chr(ord("A") + lat_index)))
        elif pair_index % 2 == 1:
            result.extend((str(lon_index), str(lat_index)))
        else:
            result.extend((chr(ord("a") + lon_index), chr(ord("a") + lat_index)))

    return "".join(result)


def wgs84_to_ecef(coordinate: GeodeticCoordinate) -> tuple[float, float, float]:
    """Convert WGS84 geodetic coordinates to ECEF ``(x, y, z)`` metres."""

    lat_rad = math.radians(coordinate.latitude_deg)
    lon_rad = math.radians(coordinate.longitude_deg)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    prime_vertical_radius_m = WGS84_SEMI_MAJOR_AXIS_M / math.sqrt(
        1.0 - WGS84_ECCENTRICITY_SQUARED * sin_lat * sin_lat
    )
    radial_m = prime_vertical_radius_m + coordinate.altitude_m
    x_m = radial_m * cos_lat * math.cos(lon_rad)
    y_m = radial_m * cos_lat * math.sin(lon_rad)
    z_m = (
        prime_vertical_radius_m * (1.0 - WGS84_ECCENTRICITY_SQUARED)
        + coordinate.altitude_m
    ) * sin_lat
    return x_m, y_m, z_m


def ecef_to_wgs84(x_m: float, y_m: float, z_m: float) -> GeodeticCoordinate:
    """Convert an ECEF position in metres to WGS84 geodetic coordinates.

    The inverse is iterated to sub-nanometre altitude convergence. Longitude
    and geodetic latitude are returned in degrees, altitude in metres.
    """

    if not all(math.isfinite(value) for value in (x_m, y_m, z_m)):
        raise ValueError("ECEF values must be finite")
    horizontal_m = math.hypot(x_m, y_m)
    if horizontal_m < 1e-12:
        if abs(z_m) < 1e-12:
            raise ValueError("ECEF origin has no geodetic coordinate")
        semi_minor_axis_m = WGS84_SEMI_MAJOR_AXIS_M * (1.0 - WGS84_FLATTENING)
        return GeodeticCoordinate(
            latitude_deg=90.0 if z_m > 0.0 else -90.0,
            longitude_deg=0.0,
            altitude_m=abs(z_m) - semi_minor_axis_m,
        )

    lon_rad = math.atan2(y_m, x_m)
    lat_rad = math.atan2(z_m, horizontal_m * (1.0 - WGS84_ECCENTRICITY_SQUARED))
    altitude_m = 0.0
    for _ in range(10):
        sin_lat = math.sin(lat_rad)
        radius_m = WGS84_SEMI_MAJOR_AXIS_M / math.sqrt(
            1.0 - WGS84_ECCENTRICITY_SQUARED * sin_lat * sin_lat
        )
        altitude_m = horizontal_m / math.cos(lat_rad) - radius_m
        next_lat_rad = math.atan2(
            z_m,
            horizontal_m
            * (1.0 - WGS84_ECCENTRICITY_SQUARED * radius_m / (radius_m + altitude_m)),
        )
        if abs(next_lat_rad - lat_rad) < 1e-14:
            lat_rad = next_lat_rad
            break
        lat_rad = next_lat_rad

    sin_lat = math.sin(lat_rad)
    radius_m = WGS84_SEMI_MAJOR_AXIS_M / math.sqrt(
        1.0 - WGS84_ECCENTRICITY_SQUARED * sin_lat * sin_lat
    )
    altitude_m = horizontal_m / math.cos(lat_rad) - radius_m
    return GeodeticCoordinate(
        latitude_deg=math.degrees(lat_rad),
        longitude_deg=math.degrees(lon_rad),
        altitude_m=altitude_m,
    )


def ecef_to_enu(
    target_ecef_m: tuple[float, float, float],
    origin: GeodeticCoordinate,
) -> tuple[float, float, float]:
    """Rotate an ECEF target into local ENU coordinates at ``origin``.

    The returned East, North and Up values are metres relative to the WGS84
    geodetic origin. Inputs and output share the Earth-fixed frame and epoch.
    """

    origin_x_m, origin_y_m, origin_z_m = wgs84_to_ecef(origin)
    dx_m = target_ecef_m[0] - origin_x_m
    dy_m = target_ecef_m[1] - origin_y_m
    dz_m = target_ecef_m[2] - origin_z_m
    lat_rad = math.radians(origin.latitude_deg)
    lon_rad = math.radians(origin.longitude_deg)
    sin_lat, cos_lat = math.sin(lat_rad), math.cos(lat_rad)
    sin_lon, cos_lon = math.sin(lon_rad), math.cos(lon_rad)

    east_m = -sin_lon * dx_m + cos_lon * dy_m
    north_m = (
        -sin_lat * cos_lon * dx_m
        - sin_lat * sin_lon * dy_m
        + cos_lat * dz_m
    )
    up_m = cos_lat * cos_lon * dx_m + cos_lat * sin_lon * dy_m + sin_lat * dz_m
    return east_m, north_m, up_m


def _letter_index(character: str, count: int, pair_name: str) -> int:
    if len(character) != 1 or not character.isascii() or not character.isalpha():
        raise ValueError(f"{pair_name} pair must contain ASCII letters")
    index = ord(character.upper()) - ord("A")
    if not 0 <= index < count:
        last = chr(ord("A") + count - 1)
        raise ValueError(f"{pair_name} letters must be between A and {last}")
    return index
