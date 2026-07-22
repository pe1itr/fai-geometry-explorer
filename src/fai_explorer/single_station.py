"""Single Station FAI-search met geometrische reverse search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

from .coordinates import (
    GeodeticCoordinate,
    WGS84_FLATTENING,
    WGS84_SEMI_MAJOR_AXIS_M,
    ecef_to_enu,
    ecef_to_wgs84,
    wgs84_to_ecef,
)
from .dual_station import (
    CandidateResult,
    DualSearchConfig,
    KM_PER_LATITUDE_DEGREE,
    MEAN_EARTH_RADIUS_KM,
    aspect_error_deg,
    bistatic_scattering_geometry,
    search_dual_station,
)
from .geomagnetic import GeomagneticModel
from .geometry import LookAngle, look_angle


@dataclass(frozen=True, slots=True)
class SingleSearchConfig:
    heights_km: tuple[float, ...] = (110.0,)
    grid_step_km: float = 25.0
    min_elevation_deg: float = 0.0
    aspect_sigma_deg: float = 5.0
    max_aspect_error_deg: float = 20.0
    scatter_angle_sigma_deg: float | None = None
    max_scatter_angle_deg: float = 180.0
    antenna_azimuth_deg: float | None = None
    azimuth_tolerance_deg: float = 20.0
    reverse_ray_step_deg: float = 10.0

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
        if self.antenna_azimuth_deg is not None and not 0.0 <= self.antenna_azimuth_deg < 360.0:
            raise ValueError("antenna_azimuth_deg must be in [0, 360)")
        if not 0.0 < self.azimuth_tolerance_deg <= 180.0:
            raise ValueError("azimuth_tolerance_deg must be in (0, 180]")
        if not 1.0 <= self.reverse_ray_step_deg <= 45.0:
            raise ValueError("reverse_ray_step_deg must be in [1, 45]")


@dataclass(frozen=True, slots=True)
class ReachableRegionPoint:
    latitude_deg: float
    longitude_deg: float
    score_total: float
    scatter_latitude_deg: float
    scatter_longitude_deg: float
    scatter_height_km: float
    azimuth_1_deg: float
    elevation_1_deg: float
    distance_1_km: float
    aspect_error_1_deg: float
    counterstation_azimuth_deg: float
    counterstation_elevation_deg: float
    counterstation_distance_km: float
    counterstation_aspect_error_deg: float


@dataclass(frozen=True, slots=True)
class SingleSearchResult:
    station: GeodeticCoordinate
    model_date: date
    model_version: str
    config: SingleSearchConfig
    visible_scatter_count: int
    accepted_scatter_count: int
    reverse_endpoint_count: int
    reachable_points: tuple[ReachableRegionPoint, ...]
    sked_validation: CandidateResult | None

    @property
    def best(self) -> ReachableRegionPoint | None:
        return self.reachable_points[0] if self.reachable_points else None


@dataclass(frozen=True, slots=True)
class _ScatterPoint:
    coordinate: GeodeticCoordinate
    look: LookAngle
    field_enu: tuple[float, float, float]
    aspect_error_deg: float
    score: float
    path_to_station_enu: tuple[float, float, float]


def search_single_station(
    station: GeodeticCoordinate,
    config: SingleSearchConfig,
    geomagnetic_model: GeomagneticModel,
    model_date: date,
) -> SingleSearchResult:
    """Bereken scatterpunten en mogelijke tegenstationposities voor station A.

    Eerst worden zichtbare ionosferische rasterpunten geselecteerd. Voor elk
    punt worden uitgaande richtingen bemonsterd waarvoor de bistatische
    scattering-vector loodrecht op het lokale magnetische veld staat. Hun
    snijpunten met de WGS84-ellipsoide vormen het geometrisch bereikbare
    tegenstationgebied.
    """

    visible: list[tuple[GeodeticCoordinate, LookAngle]] = []
    for height_km in config.heights_km:
        for latitude_deg, longitude_deg in _single_candidate_grid(
            station, height_km, config.grid_step_km
        ):
            point = GeodeticCoordinate(latitude_deg, longitude_deg, height_km * 1_000.0)
            direction = look_angle(station, point)
            if direction.elevation_deg < config.min_elevation_deg:
                continue
            if config.antenna_azimuth_deg is not None and _azimuth_difference_deg(
                direction.azimuth_deg, config.antenna_azimuth_deg
            ) > config.azimuth_tolerance_deg:
                continue
            visible.append((point, direction))

    fields = geomagnetic_model.field_enu_nt(
        [point.latitude_deg for point, _ in visible],
        [point.longitude_deg for point, _ in visible],
        [point.altitude_m / 1_000.0 for point, _ in visible],
        model_date,
    )
    station_ecef = wgs84_to_ecef(station)
    scatter_points: list[_ScatterPoint] = []
    for (point, direction), field in zip(visible, fields, strict=True):
        path_to_station = ecef_to_enu(station_ecef, point)
        error = aspect_error_deg(path_to_station, field)
        score = 1.0
        scatter_points.append(
            _ScatterPoint(point, direction, field, error, score, path_to_station)
        )

    best_per_cell: dict[tuple[int, int], ReachableRegionPoint] = {}
    raw_endpoint_count = 0
    for scatter in scatter_points:
        for endpoint in _reverse_endpoints(scatter, config.reverse_ray_step_deg):
            counter_look = look_angle(endpoint, scatter.coordinate)
            if counter_look.elevation_deg < config.min_elevation_deg:
                continue
            endpoint_ecef = wgs84_to_ecef(endpoint)
            counter_path_enu = ecef_to_enu(endpoint_ecef, scatter.coordinate)
            counter_error = aspect_error_deg(counter_path_enu, scatter.field_enu)
            try:
                bistatic_error, scatter_angle = bistatic_scattering_geometry(
                    ecef_to_enu(station_ecef, scatter.coordinate),
                    counter_path_enu,
                    scatter.field_enu,
                )
            except ValueError:
                continue
            if (
                bistatic_error > config.max_aspect_error_deg
                or scatter_angle > config.max_scatter_angle_deg
            ):
                continue
            raw_endpoint_count += 1
            scatter_angle_score = (
                1.0
                if config.scatter_angle_sigma_deg is None
                else math.exp(-((scatter_angle / config.scatter_angle_sigma_deg) ** 2))
            )
            score = (
                scatter.score
                * math.exp(-((bistatic_error / config.aspect_sigma_deg) ** 2))
                * scatter_angle_score
            )
            result = ReachableRegionPoint(
                latitude_deg=endpoint.latitude_deg,
                longitude_deg=endpoint.longitude_deg,
                score_total=score,
                scatter_latitude_deg=scatter.coordinate.latitude_deg,
                scatter_longitude_deg=scatter.coordinate.longitude_deg,
                scatter_height_km=scatter.coordinate.altitude_m / 1_000.0,
                azimuth_1_deg=scatter.look.azimuth_deg,
                elevation_1_deg=scatter.look.elevation_deg,
                distance_1_km=scatter.look.distance_m / 1_000.0,
                aspect_error_1_deg=scatter.aspect_error_deg,
                counterstation_azimuth_deg=counter_look.azimuth_deg,
                counterstation_elevation_deg=counter_look.elevation_deg,
                counterstation_distance_km=counter_look.distance_m / 1_000.0,
                counterstation_aspect_error_deg=counter_error,
            )
            cell = _ground_cell(endpoint, config.grid_step_km)
            previous = best_per_cell.get(cell)
            if previous is None or result.score_total > previous.score_total:
                best_per_cell[cell] = result

    reachable = sorted(best_per_cell.values(), key=lambda point: point.score_total, reverse=True)
    sked_validation = _validate_best_as_sked(
        station, reachable[0] if reachable else None, config, geomagnetic_model, model_date
    )
    return SingleSearchResult(
        station=station,
        model_date=model_date,
        model_version=geomagnetic_model.version,
        config=config,
        visible_scatter_count=len(visible),
        accepted_scatter_count=len(scatter_points),
        reverse_endpoint_count=raw_endpoint_count,
        reachable_points=tuple(reachable),
        sked_validation=sked_validation,
    )


def _validate_best_as_sked(
    station: GeodeticCoordinate,
    best_reachable: ReachableRegionPoint | None,
    config: SingleSearchConfig,
    geomagnetic_model: GeomagneticModel,
    model_date: date,
) -> CandidateResult | None:
    """Herbereken het beste grondpunt als vaste Dual Station-sked.

    De Dual Station-rasterzoeker wordt opnieuw uitgevoerd en daarna op
    dezelfde antennesector van station A gefilterd. Zo is de geometry-match
    rechtstreeks vergelijkbaar met een normale sked-berekening.
    """

    if best_reachable is None:
        return None
    counterstation = GeodeticCoordinate(
        best_reachable.latitude_deg, best_reachable.longitude_deg, 0.0
    )
    dual_result = search_dual_station(
        station,
        counterstation,
        config=DualSearchConfig(
            heights_km=config.heights_km,
            grid_step_km=config.grid_step_km,
            min_elevation_deg=config.min_elevation_deg,
            aspect_sigma_deg=config.aspect_sigma_deg,
            max_aspect_error_deg=config.max_aspect_error_deg,
            scatter_angle_sigma_deg=config.scatter_angle_sigma_deg,
            max_scatter_angle_deg=config.max_scatter_angle_deg,
        ),
        geomagnetic_model=geomagnetic_model,
        model_date=model_date,
    )
    for candidate in dual_result.candidates:
        if config.antenna_azimuth_deg is None or _azimuth_difference_deg(
            candidate.azimuth_1_deg, config.antenna_azimuth_deg
        ) <= config.azimuth_tolerance_deg:
            return candidate
    return None


def geometry_rating(score: float | None) -> str:
    """Transparante classificatie van de bistatische geometry-match."""

    if score is None:
        return "NO VALID ROUTE"
    if score >= 0.50:
        return "GOOD"
    if score >= 0.10:
        return "MODERATE"
    if score >= 0.01:
        return "WEAK"
    return "VERY LOW"


def _single_candidate_grid(
    station: GeodeticCoordinate, height_km: float, grid_step_km: float
):
    horizon_deg = math.degrees(
        math.acos(MEAN_EARTH_RADIUS_KM / (MEAN_EARTH_RADIUS_KM + height_km))
    )
    lat_min = max(-89.9, station.latitude_deg - horizon_deg)
    lat_max = min(89.9, station.latitude_deg + horizon_deg)
    max_abs_lat = max(abs(lat_min), abs(lat_max))
    lon_radius = horizon_deg / max(math.cos(math.radians(max_abs_lat)), 0.05)
    lon_min = max(-180.0, station.longitude_deg - lon_radius)
    lon_max = min(180.0, station.longitude_deg + lon_radius)
    latitude_step = grid_step_km / KM_PER_LATITUDE_DEGREE
    latitude = lat_min
    while latitude <= lat_max + latitude_step * 0.01:
        longitude_step = grid_step_km / (
            KM_PER_LATITUDE_DEGREE * max(math.cos(math.radians(latitude)), 0.05)
        )
        longitude = lon_min
        while longitude <= lon_max + longitude_step * 0.01:
            yield latitude, longitude
            longitude += longitude_step
        latitude += latitude_step


def _reverse_endpoints(scatter: _ScatterPoint, step_deg: float):
    field = _normalize(scatter.field_enu)
    reference = (0.0, 0.0, 1.0) if abs(field[2]) < 0.9 else (1.0, 0.0, 0.0)
    first = _normalize(_cross(field, reference))
    second = _cross(field, first)
    path_to_station = _normalize(scatter.path_to_station_enu)
    field_component = -sum(
        path * magnetic
        for path, magnetic in zip(path_to_station, field, strict=True)
    )
    field_component = max(-1.0, min(1.0, field_component))
    perpendicular_component = math.sqrt(max(0.0, 1.0 - field_component**2))
    origin_ecef = wgs84_to_ecef(scatter.coordinate)
    angle_deg = 0.0
    while angle_deg < 360.0:
        angle_rad = math.radians(angle_deg)
        direction_enu = tuple(
            field_component * field[index]
            + perpendicular_component
            * (
                math.cos(angle_rad) * first[index]
                + math.sin(angle_rad) * second[index]
            )
            for index in range(3)
        )
        direction_ecef = _enu_vector_to_ecef(direction_enu, scatter.coordinate)
        intersection = _ray_ellipsoid_intersection(origin_ecef, direction_ecef)
        if intersection is not None:
            yield ecef_to_wgs84(*intersection)
        angle_deg += step_deg


def _ray_ellipsoid_intersection(
    origin: tuple[float, float, float], direction: tuple[float, float, float]
) -> tuple[float, float, float] | None:
    semi_major = WGS84_SEMI_MAJOR_AXIS_M
    semi_minor = semi_major * (1.0 - WGS84_FLATTENING)
    x, y, z = origin
    dx, dy, dz = _normalize(direction)
    coefficient_a = (dx * dx + dy * dy) / semi_major**2 + dz * dz / semi_minor**2
    coefficient_b = 2.0 * (
        (x * dx + y * dy) / semi_major**2 + z * dz / semi_minor**2
    )
    coefficient_c = (x * x + y * y) / semi_major**2 + z * z / semi_minor**2 - 1.0
    discriminant = coefficient_b**2 - 4.0 * coefficient_a * coefficient_c
    if discriminant < 0.0:
        return None
    root = math.sqrt(discriminant)
    distances = [
        value
        for value in (
            (-coefficient_b - root) / (2.0 * coefficient_a),
            (-coefficient_b + root) / (2.0 * coefficient_a),
        )
        if value > 1.0
    ]
    if not distances:
        return None
    distance = min(distances)
    return x + distance * dx, y + distance * dy, z + distance * dz


def _enu_vector_to_ecef(
    vector: tuple[float, float, float], origin: GeodeticCoordinate
) -> tuple[float, float, float]:
    east, north, up = vector
    lat = math.radians(origin.latitude_deg)
    lon = math.radians(origin.longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    return (
        -sin_lon * east - sin_lat * cos_lon * north + cos_lat * cos_lon * up,
        cos_lon * east - sin_lat * sin_lon * north + cos_lat * sin_lon * up,
        cos_lat * north + sin_lat * up,
    )


def _ground_cell(coordinate: GeodeticCoordinate, step_km: float) -> tuple[int, int]:
    north_index = round(coordinate.latitude_deg * KM_PER_LATITUDE_DEGREE / step_km)
    east_index = round(
        coordinate.longitude_deg
        * KM_PER_LATITUDE_DEGREE
        * max(math.cos(math.radians(coordinate.latitude_deg)), 0.05)
        / step_km
    )
    return north_index, east_index


def _azimuth_difference_deg(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _leg_score(elevation_deg: float) -> float:
    return 0.25 + 0.75 / (1.0 + math.exp(-(elevation_deg - 2.0) / 2.0))


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length == 0.0:
        raise ValueError("vector must be non-zero")
    return tuple(component / length for component in vector)


def _cross(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )
