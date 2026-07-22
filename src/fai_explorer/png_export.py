"""Deelbare PNG-kaarten met een vast gegevenspaneel."""

from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile

from .coordinates import wgs84_to_maidenhead
from .dual_station import DualSearchResult
from .map_export import _load_land_polygons
from .single_station import SingleSearchResult, geometry_rating

DEFAULT_MIN_ABSOLUTE_SCORE = 0.70
SEA_COLOR = "#dceff7"
LAND_COLOR = "#e5e7eb"
BORDER_COLOR = "#94a3b8"


def write_dual_station_png(
    result: DualSearchResult,
    locator_1: str,
    locator_2: str,
    output_path: str | Path,
    min_absolute_score: float = DEFAULT_MIN_ABSOLUTE_SCORE,
) -> Path:
    """Schrijf een vaste Dual Station-kaart met data rechts als PNG."""

    plt, patches, colors = _matplotlib()
    path = _prepare_path(output_path)
    selected = _selected(result.candidates, min_absolute_score)
    best = result.best
    locations = [
        (result.station_1.latitude_deg, result.station_1.longitude_deg),
        (result.station_2.latitude_deg, result.station_2.longitude_deg),
        *((point.latitude_deg, point.longitude_deg) for point in selected),
    ]
    bounds = _bounds(locations)
    boundary_source, land = _load_land_polygons(bounds)
    figure, axis, panel = _figure_layout(plt)
    _base_map(axis, bounds, land, patches)
    if selected:
        scatter = axis.scatter(
            [point.longitude_deg for point in selected],
            [point.latitude_deg for point in selected],
            c=[point.score_total for point in selected],
            cmap=_score_colormap(colors),
            norm=colors.Normalize(min_absolute_score, 1.0),
            s=18,
            alpha=0.78,
            linewidths=0,
            zorder=4,
        )
        _compact_colorbar(
            figure,
            panel,
            scatter,
            "Bistatic geometry match",
        )
    _station(axis, result.station_1.latitude_deg, result.station_1.longitude_deg, locator_1, "#15803d", "1")
    _station(axis, result.station_2.latitude_deg, result.station_2.longitude_deg, locator_2, "#7e22ce", "2")
    axis.plot(
        [result.station_1.longitude_deg, result.station_2.longitude_deg],
        [result.station_1.latitude_deg, result.station_2.latitude_deg],
        color="#475569", linestyle=":", linewidth=1.3, zorder=3,
    )
    if best is not None:
        axis.plot(
            [result.station_1.longitude_deg, best.longitude_deg],
            [result.station_1.latitude_deg, best.latitude_deg],
            color="#15803d", linestyle="--", linewidth=1.7, zorder=5,
        )
        axis.plot(
            [result.station_2.longitude_deg, best.longitude_deg],
            [result.station_2.latitude_deg, best.latitude_deg],
            color="#7e22ce", linestyle="--", linewidth=1.7, zorder=5,
        )
        axis.scatter([best.longitude_deg], [best.latitude_deg], marker="*", s=220,
                     color="#111827" if best.score_total >= min_absolute_score else "#d97706",
                     edgecolor="white", linewidth=1.2, zorder=7)
    axis.set_title(f"FAI scatter region {locator_1.upper()} ↔ {locator_2.upper()}", fontsize=15, weight="bold")
    _north_arrow(axis)
    lines = [
        "DUAL-STATION MODE",
        "",
        f"Station 1: {locator_1.upper()}",
        f"Station 2: {locator_2.upper()}",
        f"Height: {result.config.heights_km[0]:.1f} km",
        f"Grid step: {result.config.grid_step_km:.1f} km",
        f"Minimum elevation: {result.config.min_elevation_deg:.1f}°",
        f"Model date: {result.model_date.isoformat()}",
        f"Model: {result.model_version}",
        "",
        f"Visible grid points: {result.visible_candidate_count}",
        f"Within bistatic limits: {result.accepted_candidate_count}",
        f"Shown (geometry match ≥ {min_absolute_score:.2f}): {len(selected)}",
        "",
        "BEST GEOMETRIC GRID POINT",
        *_dual_best_lines(best, min_absolute_score),
        "",
        "Colours show absolute bistatic geometry match.",
        "Geometric suitability does not predict",
        "the actual presence of FAI.",
        "",
        f"Boundaries: {boundary_source}",
    ]
    _data_panel(panel, lines)
    return _save(figure, path, plt)


def write_single_station_png(
    result: SingleSearchResult,
    locator: str,
    output_path: str | Path,
    min_absolute_score: float = DEFAULT_MIN_ABSOLUTE_SCORE,
) -> Path:
    """Schrijf Single Station-bereikbaarheid met data rechts als PNG."""

    plt, patches, colors = _matplotlib()
    path = _prepare_path(output_path)
    selected = _selected(result.reachable_points, min_absolute_score)
    locations = [(result.station.latitude_deg, result.station.longitude_deg)]
    locations.extend((point.latitude_deg, point.longitude_deg) for point in selected)
    if result.best is not None:
        locations.append((result.best.latitude_deg, result.best.longitude_deg))
    if result.sked_validation is not None:
        locations.append(
            (result.sked_validation.latitude_deg, result.sked_validation.longitude_deg)
        )
    elif result.best is not None:
        locations.append((result.best.scatter_latitude_deg, result.best.scatter_longitude_deg))
    bounds = _bounds(locations)
    boundary_source, land = _load_land_polygons(bounds)
    figure, axis, panel = _figure_layout(plt)
    _base_map(axis, bounds, land, patches)
    best = result.best
    validation = result.sked_validation
    if selected:
        scatter = axis.scatter(
            [point.longitude_deg for point in selected],
            [point.latitude_deg for point in selected],
            c=[point.score_total for point in selected],
            cmap=_score_colormap(colors),
            norm=colors.Normalize(min_absolute_score, 1.0),
            s=20,
            alpha=0.8,
            linewidths=0,
            zorder=4,
        )
        _compact_colorbar(figure, panel, scatter)
    _station(axis, result.station.latitude_deg, result.station.longitude_deg, locator, "#15803d", "A")
    if result.config.antenna_azimuth_deg is not None:
        _antenna_sector(axis, result, patches)
    if (
        best is not None
        and validation is not None
        and validation.score_total >= min_absolute_score
    ):
        axis.plot(
            [result.station.longitude_deg, validation.longitude_deg],
            [result.station.latitude_deg, validation.latitude_deg],
            color="#15803d", linestyle="--", linewidth=1.8, zorder=5,
        )
        axis.plot(
            [validation.longitude_deg, best.longitude_deg],
            [validation.latitude_deg, best.latitude_deg],
            color="#7e22ce", linestyle="--", linewidth=1.8, zorder=5,
        )
        axis.scatter([validation.longitude_deg], [validation.latitude_deg], marker="*",
                     s=220, color="#111827", edgecolor="white", linewidth=1.2, zorder=7)
        axis.scatter([best.longitude_deg], [best.latitude_deg], s=90, color="#7e22ce",
                     edgecolor="white", linewidth=1.2, zorder=7)
    axis.set_title(f"FAI reachability from {locator.upper()}", fontsize=15, weight="bold")
    _north_arrow(axis)
    azimuth_text = "all directions" if result.config.antenna_azimuth_deg is None else (
        f"{result.config.antenna_azimuth_deg:.1f}° ± {result.config.azimuth_tolerance_deg:.1f}°"
    )
    lines = [
        "SINGLE-STATION MODE",
        "",
        f"Station A: {locator.upper()}",
        f"Azimuth sector: {azimuth_text}",
        f"Height: {result.config.heights_km[0]:.1f} km",
        f"Grid step: {result.config.grid_step_km:.1f} km",
        f"Minimum elevation: {result.config.min_elevation_deg:.1f}°",
        f"Model date: {result.model_date.isoformat()}",
        f"Model: {result.model_version}",
        "",
        f"Reverse-search scatter points: {result.accepted_scatter_count}",
        f"Reachable ground cells: {len(result.reachable_points)}",
        f"Shown (absolute score ≥ {min_absolute_score:.2f}): {len(selected)}",
        "",
        "BEST REACH LOCATION – SKED CHECK",
        *_single_best_lines(best, validation),
        "",
        "Coloured points are possible",
        "counter-station areas on the ground.",
        "The best location is re-run as a fixed sked",
        "using the same antenna sector for station A.",
        "Geometric suitability does not predict",
        "the actual presence of FAI.",
        "",
        f"Boundaries: {boundary_source}",
    ]
    _data_panel(panel, lines)
    return _save(figure, path, plt)


def _matplotlib():
    cache = Path(tempfile.gettempdir()) / "fai-explorer-matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import colors, patches, pyplot as plt

    return plt, patches, colors


def _prepare_path(output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _figure_layout(plt):
    figure = plt.figure(figsize=(16, 10), constrained_layout=True)
    layout = figure.add_gridspec(1, 2, width_ratios=[4.3, 1.15], wspace=0.06)
    return (
        figure,
        figure.add_subplot(layout[0, 0]),
        figure.add_subplot(layout[0, 1]),
    )


def _compact_colorbar(figure, panel, scatter, title: str = "Bistatic geometry match") -> None:
    color_axis = panel.inset_axes([0.06, 0.08, 0.82, 0.024])
    color_axis.set_facecolor("white")
    colorbar = figure.colorbar(scatter, cax=color_axis, orientation="horizontal")
    colorbar.set_ticks([DEFAULT_MIN_ABSOLUTE_SCORE, 0.85, 1.0])
    colorbar.ax.tick_params(labelsize=7, length=2, pad=1)
    colorbar.ax.set_title(title, fontsize=7, pad=2)


def _selected(points, threshold: float):
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("min_absolute_score must be in [0, 1]")
    return [point for point in points if point.score_total >= threshold]


def _bounds(locations: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    latitudes = [latitude for latitude, _ in locations]
    longitudes = [longitude for _, longitude in locations]
    min_lat, max_lat = min(latitudes), max(latitudes)
    min_lon, max_lon = min(longitudes), max(longitudes)
    lat_pad = max((max_lat - min_lat) * 0.08, 0.5)
    lon_pad = max((max_lon - min_lon) * 0.08, 0.5)
    return min_lat - lat_pad, max_lat + lat_pad, min_lon - lon_pad, max_lon + lon_pad


def _base_map(axis, bounds, land, patches) -> None:
    min_lat, max_lat, min_lon, max_lon = bounds
    axis.set_facecolor(SEA_COLOR)
    for polygon in land:
        axis.add_patch(
            patches.Polygon(
                polygon["ring"], closed=True, facecolor=LAND_COLOR,
                edgecolor=BORDER_COLOR, linewidth=0.55, zorder=1,
            )
        )
    axis.set_xlim(min_lon, max_lon)
    axis.set_ylim(min_lat, max_lat)
    axis.set_aspect(1.0 / max(math.cos(math.radians((min_lat + max_lat) / 2.0)), 0.1))
    longitude_lines = _aligned_values(min_lon, max_lon, 2.0)
    latitude_lines = _aligned_values(min_lat, max_lat, 1.0)
    axis.set_xticks(longitude_lines)
    axis.set_yticks(latitude_lines)
    axis.grid(color="#8796a8", linewidth=0.55, alpha=0.72, zorder=2)
    _draw_maidenhead_labels(axis, bounds)
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")


def _aligned_values(minimum: float, maximum: float, step: float) -> list[float]:
    value = math.ceil(minimum / step) * step
    values: list[float] = []
    while value <= maximum + 1e-10:
        values.append(value)
        value += step
    return values


def _draw_maidenhead_labels(axis, bounds) -> None:
    min_lat, max_lat, min_lon, max_lon = bounds
    latitude = math.floor(min_lat)
    while latitude < max_lat:
        longitude = math.floor(min_lon / 2.0) * 2.0
        while longitude < max_lon:
            centre_latitude = latitude + 0.5
            centre_longitude = longitude + 1.0
            if (
                min_lat <= centre_latitude <= max_lat
                and min_lon <= centre_longitude <= max_lon
                and -90.0 <= centre_latitude <= 90.0
                and -180.0 <= centre_longitude <= 180.0
            ):
                locator = wgs84_to_maidenhead(
                    centre_latitude, centre_longitude, precision=4
                )
                axis.text(
                    centre_longitude,
                    centre_latitude,
                    locator,
                    ha="center",
                    va="center",
                    fontsize=7.0,
                    weight="bold",
                    color="#64748b",
                    alpha=0.52,
                    zorder=2.5,
                )
            longitude += 2.0
        latitude += 1.0


def _station(axis, latitude, longitude, locator, color, prefix) -> None:
    axis.scatter([longitude], [latitude], s=105, color=color, edgecolor="white",
                 linewidth=1.5, zorder=8)
    right_side = longitude > sum(axis.get_xlim()) / 2.0
    offset = (-7, 7) if right_side else (7, 7)
    alignment = "right" if right_side else "left"
    axis.annotate(f"{prefix}: {locator.upper()}", (longitude, latitude), xytext=offset,
                  textcoords="offset points", ha=alignment, fontsize=9, weight="bold", zorder=9,
                  bbox={"boxstyle": "round,pad=.18", "facecolor": "white", "alpha": .78, "edgecolor": "none"})


def _north_arrow(axis) -> None:
    axis.annotate("N", xy=(0.955, 0.92), xytext=(0.955, 0.82), xycoords="axes fraction",
                  ha="center", va="center", fontsize=11, weight="bold",
                  arrowprops={"arrowstyle": "-|>", "color": "#172033", "lw": 1.5})


def _score_colormap(colors):
    return colors.LinearSegmentedColormap.from_list(
        "fai_score", ["#2563eb", "#06b6d4", "#fde047", "#dc2626"]
    )


def _data_panel(panel, lines: list[str]) -> None:
    panel.set_facecolor("#f8fafc")
    panel.axis("off")
    panel.text(0.04, 0.97, "\n".join(lines), transform=panel.transAxes, va="top",
               ha="left", fontsize=9.2, linespacing=1.36, family="DejaVu Sans")


def _save(figure, path: Path, plt) -> Path:
    figure.savefig(path, dpi=150, facecolor="#e8edf2", metadata={"Software": "FAI Geometry Explorer"})
    plt.close(figure)
    return path


def _dual_best_lines(best, credible_score: float = DEFAULT_MIN_ABSOLUTE_SCORE) -> list[str]:
    if best is None:
        return ["No point within the configured limits."]
    warning = (
        [
            "LOW GEOMETRY MATCH – RESEARCH ONLY",
            "Not a validated propagation probability.",
        ]
        if best.score_total < credible_score
        else []
    )
    return [
        *warning,
        f"Geometry match: {best.score_total:.6f}",
        f"Geometry rating: {geometry_rating(best.score_total)}",
        f"Position: {best.latitude_deg:.4f}°, {best.longitude_deg:.4f}°",
        f"Station 1 az/el: {best.azimuth_1_deg:.2f}° / {best.elevation_1_deg:.2f}°",
        f"Distance 1: {best.distance_1_km:.1f} km",
        f"Bistatic aspect error: {best.bistatic_aspect_error_deg:.2f}°",
        f"Propagation deflection: {best.scatter_angle_deg:.2f}°",
        f"Deflection score: {best.score_scatter_angle:.4f}",
        f"Station 2 az/el: {best.azimuth_2_deg:.2f}° / {best.elevation_2_deg:.2f}°",
        f"Distance 2: {best.distance_2_km:.1f} km",
    ]


def _single_best_lines(best, validation) -> list[str]:
    if best is None or validation is None:
        return ["No route within the configured limits."]
    if validation.score_total < DEFAULT_MIN_ABSOLUTE_SCORE:
        return [
            "No sufficient bistatic geometry match.",
            f"Best sked match {validation.score_total:.6f} is below {DEFAULT_MIN_ABSOLUTE_SCORE:.2f}.",
            "No antenna direction is advised.",
        ]
    return [
        f"Bistatic sked match: {validation.score_total:.6f}",
        f"Geometry rating: {geometry_rating(validation.score_total)}",
        f"Counter-station: {best.latitude_deg:.4f}°, {best.longitude_deg:.4f}°",
        f"Scatter point: {validation.latitude_deg:.4f}°, {validation.longitude_deg:.4f}°",
        f"Station A az/el: {validation.azimuth_1_deg:.2f}° / {validation.elevation_1_deg:.2f}°",
        f"Distance A: {validation.distance_1_km:.1f} km",
        f"Bistatic aspect error: {validation.bistatic_aspect_error_deg:.2f}°",
        f"Propagation deflection: {validation.scatter_angle_deg:.2f}°",
        f"Counter-station az/el: {validation.azimuth_2_deg:.2f}° / {validation.elevation_2_deg:.2f}°",
        f"Counter-station distance: {validation.distance_2_km:.1f} km",
    ]
def _antenna_sector(axis, result: SingleSearchResult, patches) -> None:
    azimuth = result.config.antenna_azimuth_deg
    assert azimuth is not None
    bearings = [
        azimuth - result.config.azimuth_tolerance_deg
        + index * (2.0 * result.config.azimuth_tolerance_deg / 24.0)
        for index in range(25)
    ]
    coordinates = [(result.station.longitude_deg, result.station.latitude_deg)]
    coordinates.extend(
        (longitude, latitude)
        for latitude, longitude in (_destination(result.station.latitude_deg, result.station.longitude_deg, bearing, 1200.0) for bearing in bearings)
    )
    axis.add_patch(patches.Polygon(coordinates, closed=True, facecolor="#f59e0b22",
                                  edgecolor="#d97706", linestyle="--", linewidth=1.0, zorder=3))


def _destination(latitude_deg, longitude_deg, bearing_deg, distance_km):
    angular = distance_km / 6_371.0088
    latitude = math.radians(latitude_deg)
    longitude = math.radians(longitude_deg)
    bearing = math.radians(bearing_deg)
    target_latitude = math.asin(
        math.sin(latitude) * math.cos(angular)
        + math.cos(latitude) * math.sin(angular) * math.cos(bearing)
    )
    target_longitude = longitude + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(latitude),
        math.cos(angular) - math.sin(latitude) * math.sin(target_latitude),
    )
    return math.degrees(target_latitude), math.degrees(target_longitude)
