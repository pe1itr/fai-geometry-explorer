"""Verwisselbare geomagnetische modellen voor FAI-aspectberekeningen."""

from __future__ import annotations

from datetime import date, datetime
import math
from typing import Protocol, Sequence


class GeomagneticModel(Protocol):
    """Interface voor magnetische veldvectoren in lokaal ENU."""

    @property
    def version(self) -> str:
        """Menselijk leesbare modelversie voor resultaatmetadata."""

    def field_enu_nt(
        self,
        latitude_deg: Sequence[float],
        longitude_deg: Sequence[float],
        altitude_km: Sequence[float],
        model_date: date,
    ) -> list[tuple[float, float, float]]:
        """Geef ``(east, north, up)`` in nanotesla voor ieder invoerpunt."""


class PpigrfModel:
    """IGRF-14-adapter rond het vectoriseerbare pakket ``ppigrf``."""

    @property
    def version(self) -> str:
        return "IGRF-14 via ppigrf 2.1.0"

    def field_enu_nt(
        self,
        latitude_deg: Sequence[float],
        longitude_deg: Sequence[float],
        altitude_km: Sequence[float],
        model_date: date,
    ) -> list[tuple[float, float, float]]:
        """Bereken het IGRF-veld in geodetisch lokaal East-North-Up.

        Breedte en lengte zijn WGS84-graden, hoogte is kilometer boven de
        ellipsoide en de uitvoer is nanotesla. ``ppigrf`` retourneert per datum
        een rij; deze adapter accepteert precies een modeldatum.
        """

        try:
            import numpy as np
            import ppigrf
        except ImportError as exc:  # pragma: no cover - installatieprobleem
            raise RuntimeError(
                "IGRF-berekening vereist ppigrf; installeer het project opnieuw"
            ) from exc

        if not (len(latitude_deg) == len(longitude_deg) == len(altitude_km)):
            raise ValueError("geomagnetic coordinate arrays must have equal lengths")
        if not latitude_deg:
            return []

        east_nt, north_nt, up_nt = ppigrf.igrf(
            np.asarray(longitude_deg, dtype=float),
            np.asarray(latitude_deg, dtype=float),
            np.asarray(altitude_km, dtype=float),
            datetime.combine(model_date, datetime.min.time()),
        )
        east = np.asarray(east_nt)[0]
        north = np.asarray(north_nt)[0]
        up = np.asarray(up_nt)[0]
        fields = [
            (float(e_value), float(n_value), float(u_value))
            for e_value, n_value, u_value in zip(east, north, up, strict=True)
        ]
        if any(not all(math.isfinite(component) for component in field) for field in fields):
            raise RuntimeError("IGRF returned a non-finite magnetic field")
        return fields
