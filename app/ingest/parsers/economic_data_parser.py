"""Official macro/economic series — Banxico SIE (Mexico) and FRED (US) —
into intermediate RawEconomicObservation records. Axis 2 (SQL-retrieval):
structured, exact entity+timestamp series, never embedded. Feeds a new
economic_indicators table (Phase 9), never market_observations — these
series aren't tied to a monitored symbol (articles/s10-05's schema-
divergence rule: a price tick and a named macro series are different
entities, not variations of one thing).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.ingest.loaders.http import fetch_json

BANXICO_SERIES_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/{series_id}/datos/oportuno"
FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"


@dataclass
class RawEconomicObservation:
    series_id: str
    series_name: str
    value: float
    observed_on: date
    source_name: str  # "banxico_sie" or "fred_economic_data"
    country: str  # "MX" or "US"


def fetch_banxico_series(series_id: str, token: str) -> dict:
    """series_id: a Banxico SIE series identifier — look one up via
    https://www.banxico.org.mx/SieInternet/ (the overnight target rate,
    INPC, etc.). Not hardcoded here: unlike FRED's iconic FEDFUNDS/
    CPIAUCSL ids, Banxico's own series ids are less universally memorable,
    and getting one wrong fails silently (an empty but valid-looking
    response) rather than erroring loudly — confirm the real id once a
    token exists, don't guess it into config from memory.
    """
    url = BANXICO_SERIES_URL.format(series_id=series_id)
    return fetch_json(url, headers={"Bmx-Token": token})


def parse_banxico_series(raw: dict, series_name: str) -> list[RawEconomicObservation]:
    """raw is Banxico's own shape:
    {"bmx": {"series": [{"idSerie": "...", "datos": [{"fecha": "DD/MM/YYYY", "dato": "8.2500"}]}]}}
    """
    observations = []
    for series in raw.get("bmx", {}).get("series", []):
        series_id = series.get("idSerie", "")
        for point in series.get("datos", []):
            raw_value = point.get("dato", "").strip()
            if raw_value in ("", "N/E"):
                # Banxico's own disguised-null marker for "not available"
                # (articles/s06-04) — not a real zero, don't coerce it to one.
                continue
            observations.append(
                RawEconomicObservation(
                    series_id=series_id,
                    series_name=series_name,
                    value=float(raw_value),
                    observed_on=datetime.strptime(point["fecha"], "%d/%m/%Y").date(),
                    source_name="banxico_sie",
                    country="MX",
                )
            )
    return observations


def fetch_fred_series(series_id: str, api_key: str, observation_start: str | None = None) -> dict:
    """observation_start (YYYY-MM-DD) bounds the pull to recent history.
    FRED's default with no bound returns the ENTIRE series — for CPIAUCSL
    that's back to 1947 (1823 rows landed on a live, unbounded first poll,
    2026-09-11) — far more than a grounding-context tool needs, and it
    re-pulls the same full history on every scheduled refresh.
    refresh_worker.py passes a bounded lookback by default; Banxico's own
    /datos/oportuno endpoint (economic_data_parser's other fetch function)
    already returns only the latest observation, so this asymmetry was
    FRED-specific.
    """
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    if observation_start:
        params["observation_start"] = observation_start
    return fetch_json(FRED_SERIES_URL, params=params)


def parse_fred_series(raw: dict, series_id: str, series_name: str) -> list[RawEconomicObservation]:
    """raw is FRED's own shape: {"observations": [{"date": "YYYY-MM-DD", "value": "4.33"}]}."""
    observations = []
    for point in raw.get("observations", []):
        raw_value = point.get("value", "").strip()
        if raw_value == ".":
            # FRED's own disguised-null marker for a missing observation.
            continue
        observations.append(
            RawEconomicObservation(
                series_id=series_id,
                series_name=series_name,
                value=float(raw_value),
                observed_on=date.fromisoformat(point["date"]),
                source_name="fred_economic_data",
                country="US",
            )
        )
    return observations
