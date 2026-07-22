"""Rasterzoeker voor geometrisch gunstige bistatische FAI-punten."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

from .coordinates import GeodeticCoordinate, ecef_to_enu, wgs84_to_ecef
from .geomagnetic import GeomagneticModel
from .geometry import LookAngle, look_angle

MEAN_EARTH_RADIUS_KM = 6_371.0088
KM_PER_LATITUDE_DEGREE = math.pi * MEAN_EARTH_RADIUS_KM / 180.0


@dataclass(frozen=True, slots=True)
class DualSearchConfig:
    """Expliciete onderzoeksparameters voor een Dual Station-search."""

    heights_km: tuple[float, ...] = (110.0,)
    grid_step_km: float = 25.0
    min_elevation_deg: float = 0.0
    aspect_sigma_deg: float = 5.0
    max_aspect_error_deg: float = 20.0
    scatter_angle_sigma_deg: float | None = None
    max_scatter_angle_deg: float = 180.0

    def __post_init__(self) -> None:
        if not self.heights_km or any(height <= 0.0 for height in self.heights_km):
            raise ValueError("heights_km must contain positive heights")
        if self.grid_step_km <= 0.0:
            raise ValueError("grid_step_km must be positive")
        if self.min_elevation_deg < 0.0:
            raise ValueError("min_elevation_deg must be at least 0 degrees")
        if self.aspect_sigma_deg <= 0.0:
            raise ValueError("aspect_sigma_deg must be positive")
        if not 0.0 < self.max_aspect_error_deg <= 90.0:
            raise ValueError("max_aspect_error_deg must be in (0, 90]")
        if self.scatter_angle_sigma_deg is not None and self.scatter_angle_sigma_deg <= 0.0:
            raise ValueError("scatter_angle_sigma_deg must be positive when set")
        if not 0.0 < self.max_scatter_angle_deg <= 180.0:
            raise ValueError("max_scatter_angle_deg must be in (0, 180]")


@dataclass(frozen=True, slots=True)
class CandidateResult:
    latitude_deg: float
    longitude_deg: float
    height_km: float
    score_total: float
    score_aspect: float
    score_elevation: float
    score_scatter_angle: float
    bistatic_aspect_error_deg: float
    scatter_angle_deg: float
    azimuth_1_deg: float
    elevation_1_deg: float
    distance_1_km: float
    aspect_error_1_deg: float
    azimuth_2_deg: float
    elevation_2_deg: float
    distance_2_km: float
    aspect_error_2_deg: float
    magnetic_field_enu_nt: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class DualSearchResult:
    station_1: GeodeticCoordinate
    station_2: GeodeticCoordinate
    model_date: date
    model_version: str
    config: DualSearchConfig
    visible_candidate_count: int
    accepted_candidate_count: int
    candidates: tuple[CandidateResult, ...]

    @property
    def best(self) -> CandidateResult | None:
        return self.candidates[0] if self.candidates else None


@dataclass(frozen=True, slots=True)
class _VisiblePoint:
    coordinate: GeodeticCoordinate
    from_1: LookAngle
    from_2: LookAngle


def aspect_error_deg(
    path_enu: tuple[float, float, float],
    magnetic_field_enu: tuple[float, float, float],
) -> float:
    """Return afwijking van loodrechte inval in graden.

    Beide vectoren staan in hetzelfde lokale ENU-stelsel bij het scatterpunt.
    De absolute dot-productwaarde behandelt het magnetische veld als een as:
    veldrichting omkeren verandert de aspectfout niet. Nul graden is ideaal.
    """

    path_norm = math.sqrt(sum(component * component for component in path_enu))
    field_norm = math.sqrt(sum(component * component for component in magnetic_field_enu))
    if path_norm == 0.0 or field_norm == 0.0:
        raise ValueError("aspect vectors must be non-zero")
    cosine = abs(
        sum(path * field for path, field in zip(path_enu, magnetic_field_enu, strict=True))
        / (path_norm * field_norm)
    )
    return math.degrees(math.asin(max(0.0, min(1.0, cosine))))


def bistatic_scattering_geometry(
    path_to_station_1_enu: tuple[float, float, float],
    path_to_station_2_enu: tuple[float, float, float],
    magnetic_field_enu: tuple[float, float, float],
) -> tuple[float, float]:
    """Return ``(aspect error, propagation deflection)`` in degrees.

    At the scatter point, ``u1`` and ``u2`` point towards the two stations.
    The incident propagation vector is ``-u1`` and the scattered propagation
    vector is ``u2``.  Therefore the bistatic scattering vector is
    ``K = u2 - (-u1) = u1 + u2``.  FAI requires K to be perpendicular to B.

    The deflection is the angle between the incident and scattered propagation
    vectors.  Zero degrees is forward propagation; large values require a
    progressively sharper turn.  An exactly zero K has no defined aspect and
    is rejected because it cannot select a finite irregularity wavelength.
    """

    u1 = _unit(path_to_station_1_enu)
    u2 = _unit(path_to_station_2_enu)
    scattering_vector = tuple(a + b for a, b in zip(u1, u2, strict=True))
    scattering_norm = math.sqrt(sum(value * value for value in scattering_vector))
    if scattering_norm < 1e-9:
        raise ValueError("bistatic scattering vector is zero")
    aspect_error = aspect_error_deg(scattering_vector, magnetic_field_enu)
    incident = tuple(-value for value in u1)
    cosine = sum(a * b for a, b in zip(incident, u2, strict=True))
    deflection = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    return aspect_error, deflection


def search_dual_station(
    station_1: GeodeticCoordinate,
    station_2: GeodeticCoordinate,
    config: DualSearchConfig,
    geomagnetic_model: GeomagneticModel,
    model_date: date,
) -> DualSearchResult:
    """Zoek zichtbare rasterpunten met gunstige FAI-aspectgeometrie.

    Het raster bestrijkt de conservatieve overlap van de horizongebieden van
    beide stations en ligt niet vast aan grootcirkel of middenpunt. Per punt
    worden de twee paden ter plaatse naar ENU omgezet. De som van de twee
    eenheidsvectoren is de bistatische scattering-vector; die wordt met het
    lokale magnetische veld vergeleken. Grote richtingsveranderingen krijgen
    daarnaast een afzonderlijke, configureerbare straf.
    """

    visible_points: list[_VisiblePoint] = []
    for height_km in config.heights_km:
        for latitude_deg, longitude_deg in _candidate_grid(
            station_1, station_2, height_km, config.grid_step_km
        ):
            point = GeodeticCoordinate(latitude_deg, longitude_deg, height_km * 1_000.0)
            from_1 = look_angle(station_1, point)
            from_2 = look_angle(station_2, point)
            if (
                from_1.elevation_deg >= config.min_elevation_deg
                and from_2.elevation_deg >= config.min_elevation_deg
            ):
                visible_points.append(_VisiblePoint(point, from_1, from_2))

    fields = geomagnetic_model.field_enu_nt(
        [point.coordinate.latitude_deg for point in visible_points],
        [point.coordinate.longitude_deg for point in visible_points],
        [point.coordinate.altitude_m / 1_000.0 for point in visible_points],
        model_date,
    )
    station_1_ecef = wgs84_to_ecef(station_1)
    station_2_ecef = wgs84_to_ecef(station_2)
    results: list[CandidateResult] = []

    for visible, field_enu in zip(visible_points, fields, strict=True):
        path_1_enu = ecef_to_enu(station_1_ecef, visible.coordinate)
        path_2_enu = ecef_to_enu(station_2_ecef, visible.coordinate)
        error_1 = aspect_error_deg(path_1_enu, field_enu)
        error_2 = aspect_error_deg(path_2_enu, field_enu)
        try:
            bistatic_error, scatter_angle = bistatic_scattering_geometry(
                path_1_enu, path_2_enu, field_enu
            )
        except ValueError:
            continue
        if (
            bistatic_error > config.max_aspect_error_deg
            or scatter_angle > config.max_scatter_angle_deg
        ):
            continue

        aspect_score = math.exp(
            -((bistatic_error / config.aspect_sigma_deg) ** 2)
        )
        scatter_angle_score = (
            1.0
            if config.scatter_angle_sigma_deg is None
            else math.exp(-((scatter_angle / config.scatter_angle_sigma_deg) ** 2))
        )
        elevation_score = _elevation_score(
            visible.from_1.elevation_deg, visible.from_2.elevation_deg
        )
        results.append(
            CandidateResult(
                latitude_deg=visible.coordinate.latitude_deg,
                longitude_deg=visible.coordinate.longitude_deg,
                height_km=visible.coordinate.altitude_m / 1_000.0,
                score_total=aspect_score * scatter_angle_score,
                score_aspect=aspect_score,
                score_elevation=elevation_score,
                score_scatter_angle=scatter_angle_score,
                bistatic_aspect_error_deg=bistatic_error,
                scatter_angle_deg=scatter_angle,
                azimuth_1_deg=visible.from_1.azimuth_deg,
                elevation_1_deg=visible.from_1.elevation_deg,
                distance_1_km=visible.from_1.distance_m / 1_000.0,
                aspect_error_1_deg=error_1,
                azimuth_2_deg=visible.from_2.azimuth_deg,
                elevation_2_deg=visible.from_2.elevation_deg,
                distance_2_km=visible.from_2.distance_m / 1_000.0,
                aspect_error_2_deg=error_2,
                magnetic_field_enu_nt=field_enu,
            )
        )

    results.sort(key=lambda candidate: candidate.score_total, reverse=True)
    return DualSearchResult(
        station_1=station_1,
        station_2=station_2,
        model_date=model_date,
        model_version=geomagnetic_model.version,
        config=config,
        visible_candidate_count=len(visible_points),
        accepted_candidate_count=len(results),
        candidates=tuple(results),
    )


def _candidate_grid(
    station_1: GeodeticCoordinate,
    station_2: GeodeticCoordinate,
    height_km: float,
    grid_step_km: float,
):
    """Yield a conservative lat/lon grid over both spherical horizon caps."""

    horizon_deg = math.degrees(
        math.acos(MEAN_EARTH_RADIUS_KM / (MEAN_EARTH_RADIUS_KM + height_km))
    )
    lat_min = max(-89.9, station_1.latitude_deg - horizon_deg, station_2.latitude_deg - horizon_deg)
    lat_max = min(89.9, station_1.latitude_deg + horizon_deg, station_2.latitude_deg + horizon_deg)
    if lat_min > lat_max:
        return

    max_abs_lat = max(abs(lat_min), abs(lat_max))
    lon_scale = max(math.cos(math.radians(max_abs_lat)), 0.05)
    longitude_radius_deg = horizon_deg / lon_scale
    lon_min = max(
        station_1.longitude_deg - longitude_radius_deg,
        station_2.longitude_deg - longitude_radius_deg,
    )
    lon_max = min(
        station_1.longitude_deg + longitude_radius_deg,
        station_2.longitude_deg + longitude_radius_deg,
    )
    if lon_min > lon_max or lon_min < -180.0 or lon_max > 180.0:
        return

    latitude_step_deg = grid_step_km / KM_PER_LATITUDE_DEGREE
    latitude = lat_min
    while latitude <= lat_max + latitude_step_deg * 0.01:
        longitude_step_deg = grid_step_km / (
            KM_PER_LATITUDE_DEGREE * max(math.cos(math.radians(latitude)), 0.05)
        )
        longitude = lon_min
        while longitude <= lon_max + longitude_step_deg * 0.01:
            yield latitude, longitude
            longitude += longitude_step_deg
        latitude += latitude_step_deg


def _elevation_score(elevation_1_deg: float, elevation_2_deg: float) -> float:
    """Zachte, verklaarbare voorkeur voor elevaties boven circa 2 graden."""

    def leg_score(elevation_deg: float) -> float:
        return 0.25 + 0.75 / (1.0 + math.exp(-(elevation_deg - 2.0) / 2.0))

    return leg_score(elevation_1_deg) * leg_score(elevation_2_deg)


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0.0:
        raise ValueError("vector must be non-zero")
    return tuple(value / length for value in vector)
