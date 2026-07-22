"""Bouw het compacte runtimebestand uit Natural Earth Admin-0 Countries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas
from shapely.geometry import MultiPolygon, Polygon


def polygon_rings(geometry: Polygon | MultiPolygon) -> list[list[list[float]]]:
    polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    return [
        [[round(float(lon), 4), round(float(lat), 4)] for lon, lat in polygon.exterior.coords]
        for polygon in polygons
        if not polygon.is_empty
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    frame = geopandas.read_file(args.source)
    countries = []
    for _, row in frame.iterrows():
        geometry = row.geometry.simplify(0.025, preserve_topology=True)
        rings = polygon_rings(geometry)
        if rings:
            countries.append({"name": str(row["NAME"]), "polygons": rings})

    payload = {
        "source": "Natural Earth Admin-0 Countries 1:50m, version 5.1.1",
        "simplification_tolerance_deg": 0.025,
        "countries": countries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
