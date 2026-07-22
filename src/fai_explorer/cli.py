"""Opdrachtregelinterface voor Single en Dual Station FAI-kaarten."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .coordinates import maidenhead_to_wgs84
from .dual_station import DualSearchConfig, search_dual_station
from .geomagnetic import PpigrfModel
from .geometry import look_angle
from .map_export import write_scatter_map
from .png_export import write_dual_station_png, write_single_station_png
from .single_map_export import write_single_station_map
from .single_station import SingleSearchConfig, geometry_rating, search_single_station


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bereken FAI-geometrie voor een station, eventueel met een tweede "
            "Maidenhead-locator."
        )
    )
    parser.add_argument(
        "--locator1",
        required=True,
        help="Maidenhead-locator van station 1, bijvoorbeeld JO21QK",
    )
    parser.add_argument(
        "--locator2",
        help="Maidenhead-locator van station 2, bijvoorbeeld JN47FD",
    )
    parser.add_argument("--altitude-a-m", type=float, default=0.0)
    parser.add_argument("--altitude-b-m", type=float, default=0.0)
    parser.add_argument("--height-km", type=float, default=110.0)
    parser.add_argument("--grid-step-km", type=float, default=25.0)
    parser.add_argument(
        "--min-elevation-deg",
        type=float,
        default=0.0,
        help=(
            "Minimale geometrische elevatie voor beide trajectbenen; "
            "waarden onder 0 graden zijn niet toegestaan (standaard: 0)"
        ),
    )
    parser.add_argument("--aspect-sigma-deg", type=float, default=5.0)
    parser.add_argument("--max-aspect-error-deg", type=float, default=20.0)
    parser.add_argument(
        "--scatter-angle-sigma-deg",
        type=float,
        default=None,
        help="Experimentele Gaussische afbuigingsstraf; standaard uitgeschakeld",
    )
    parser.add_argument(
        "--max-scatter-angle-deg",
        type=float,
        default=180.0,
        help="Maximale richtingsverandering bij het scatterpunt (standaard: 180)",
    )
    parser.add_argument(
        "--azimuth",
        type=float,
        help="Optionele antenne-azimut voor Single Station Mode, in graden vanaf noord",
    )
    parser.add_argument(
        "--azimuth-tolerance",
        type=float,
        default=20.0,
        help="Halve breedte van de antennesector in graden (standaard: 20)",
    )
    parser.add_argument(
        "--output-map",
        default="fai_scatter_map.png",
        metavar="BESTAND.png|BESTAND.html",
        help="PNG- of interactieve HTML-uitvoer (standaard: fai_scatter_map.png)",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="Modeldatum voor IGRF (standaard: vandaag)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_cli_locator(parser, args.locator1, "--locator1")
    if args.locator2 is not None:
        _validate_cli_locator(parser, args.locator2, "--locator2")
    if args.locator2 is not None and args.azimuth is not None:
        parser.error("--azimuth wordt alleen gebruikt zonder --locator2")
    if args.min_elevation_deg < 0.0:
        parser.error("--min-elevation-deg mag niet lager zijn dan 0 graden")
    if args.locator2 is None:
        return _run_single(args)
    return _run_dual(args)


def _validate_cli_locator(
    parser: argparse.ArgumentParser, locator: str, option_name: str
) -> None:
    """Reject historical QRA/modern Maidenhead ambiguity at the CLI boundary."""

    length = len(locator.strip())
    if length == 2:
        parser.error(
            f"{option_name}: een tweelettercode zoals CK is ambigu tussen een "
            "Maidenhead-veld en het oude Europese QRA-systeem; gebruik voor een "
            "modern station een Maidenhead-locator van 4, 6 of 8 tekens"
        )
    if length not in (4, 6, 8):
        parser.error(
            f"{option_name}: verwacht een Maidenhead-locator van 4, 6 of 8 tekens; "
            "historische vijftekens-QRA-locators worden nog niet automatisch geconverteerd"
        )


def _run_single(args: argparse.Namespace) -> int:
    station = maidenhead_to_wgs84(args.locator1, args.altitude_a_m)
    config = SingleSearchConfig(
        heights_km=(args.height_km,),
        grid_step_km=args.grid_step_km,
        min_elevation_deg=args.min_elevation_deg,
        aspect_sigma_deg=args.aspect_sigma_deg,
        max_aspect_error_deg=args.max_aspect_error_deg,
        scatter_angle_sigma_deg=args.scatter_angle_sigma_deg,
        max_scatter_angle_deg=args.max_scatter_angle_deg,
        antenna_azimuth_deg=args.azimuth,
        azimuth_tolerance_deg=args.azimuth_tolerance,
    )
    result = search_single_station(
        station,
        config=config,
        geomagnetic_model=PpigrfModel(),
        model_date=args.date,
    )
    print(
        f"Station A {args.locator1.upper()} (vakmidden): "
        f"{station.latitude_deg:.6f}, {station.longitude_deg:.6f}, "
        f"{station.altitude_m:.1f} m"
    )
    sector = (
        "alle richtingen"
        if args.azimuth is None
        else f"{args.azimuth:.1f} +/- {args.azimuth_tolerance:.1f} graden"
    )
    print(f"Single Station Mode; antennesector: {sector}")
    print(
        f"Scatterraster: {result.visible_scatter_count} zichtbaar in sector; "
        f"{result.accepted_scatter_count} gebruikt voor bistatische reverse search"
    )
    print(
        f"Reverse search: {len(result.reachable_points)} bereikbare grondcellen "
        f"uit {result.reverse_endpoint_count} geometrische snijpunten"
    )
    if result.sked_validation is not None:
        print(
            f"Sked-controle beste locatie: geometry-match "
            f"{result.sked_validation.score_total:.6f} "
            f"({geometry_rating(result.sked_validation.score_total)})"
        )
    if Path(args.output_map).suffix.lower() == ".png":
        map_path = write_single_station_png(result, args.locator1, args.output_map)
        map_kind = "PNG-kaart"
    elif Path(args.output_map).suffix.lower() == ".html":
        map_path = write_single_station_map(result, args.locator1, args.output_map)
        map_kind = "Interactieve HTML-kaart"
    else:
        raise ValueError("--output-map must end in .png or .html")
    print(f"{map_kind}: {map_path}")
    if result.best is None:
        print("Geen bereikbaar tegenstationgebied gevonden binnen de ingestelde grenzen.")
        print("Dit is een geldige lege uitkomst; verruim alleen grenzen als onderzoekskeuze.")
        return 0
    if result.sked_validation is None or result.sked_validation.score_total < 0.50:
        print(
            "Geen voldoende bistatische geometry-match na de vaste sked-controle; "
            "er wordt geen antenneadvies gemarkeerd."
        )
        return 0
    print("De kaart toont bereikbare tegenstationgebieden en de beste geometrische route.")
    return 0


def _run_dual(args: argparse.Namespace) -> int:
    station_a = maidenhead_to_wgs84(args.locator1, args.altitude_a_m)
    station_b = maidenhead_to_wgs84(args.locator2, args.altitude_b_m)
    config = DualSearchConfig(
        heights_km=(args.height_km,),
        grid_step_km=args.grid_step_km,
        min_elevation_deg=args.min_elevation_deg,
        aspect_sigma_deg=args.aspect_sigma_deg,
        max_aspect_error_deg=args.max_aspect_error_deg,
        scatter_angle_sigma_deg=args.scatter_angle_sigma_deg,
        max_scatter_angle_deg=args.max_scatter_angle_deg,
    )
    result = search_dual_station(
        station_a,
        station_b,
        config=config,
        geomagnetic_model=PpigrfModel(),
        model_date=args.date,
    )

    print(
        f"Station 1 {args.locator1.upper()} (vakmidden): "
        f"{station_a.latitude_deg:.6f}, {station_a.longitude_deg:.6f}, "
        f"{station_a.altitude_m:.1f} m"
    )
    print(
        f"Station 2 {args.locator2.upper()} (vakmidden): "
        f"{station_b.latitude_deg:.6f}, {station_b.longitude_deg:.6f}, "
        f"{station_b.altitude_m:.1f} m"
    )
    print(
        f"Model: {result.model_version}; datum {result.model_date.isoformat()}; "
        f"hoogte {args.height_km:.1f} km"
    )
    print(
        f"Raster: {result.visible_candidate_count} punten zichtbaar vanaf beide stations; "
        f"{result.accepted_candidate_count} binnen de bistatische grenzen"
    )
    direct = look_angle(station_a, station_b)
    print(f"Directe richting station 1 naar 2: {direct.azimuth_deg:.2f} graden")
    if Path(args.output_map).suffix.lower() == ".png":
        map_path = write_dual_station_png(
            result, args.locator1, args.locator2, args.output_map
        )
        map_kind = "PNG-kaart"
    elif Path(args.output_map).suffix.lower() == ".html":
        map_path = write_scatter_map(result, args.locator1, args.locator2, args.output_map)
        map_kind = "Interactieve HTML-kaart"
    else:
        raise ValueError("--output-map must end in .png or .html")
    print(f"{map_kind}: {map_path}")
    if result.best is None:
        print("Geen kandidaat gevonden binnen de ingestelde grenzen.")
        print("Probeer een fijner raster of een ruimere --max-aspect-error-deg.")
        return 2

    print(
        f"Beste geometrische kandidaat: geometry-match {result.best.score_total:.6f}; "
        f"bistatische aspectfout {result.best.bistatic_aspect_error_deg:.2f} graden; "
        f"richtingsverandering {result.best.scatter_angle_deg:.2f} graden"
    )
    if result.best.score_total < 0.50:
        print(
            "Lage geometry-match (< 0.50): de kaart toont ter analyse het gebied "
            "binnen 50% van de beste kandidaat; dit is geen gevalideerde propagatiekans."
        )
        return 0
    print(
        "Het scattergebied staat op de kaart; de ster markeert slechts het rasterpunt "
        "met de kleinste mismatch, niet het werkelijk aanwezige scatterpunt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
