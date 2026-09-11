from datetime import date

from app.ingest.parsers.economic_data_parser import (
    parse_banxico_series,
    parse_fred_series,
)

BANXICO_RAW = {
    "bmx": {
        "series": [
            {
                "idSerie": "SF61745",
                "datos": [
                    {"fecha": "07/09/2026", "dato": "8.2500"},
                    {"fecha": "01/08/2026", "dato": "N/E"},
                    {"fecha": "01/07/2026", "dato": ""},
                ],
            }
        ]
    }
}

FRED_RAW = {
    "observations": [
        {"date": "2026-08-01", "value": "4.33"},
        {"date": "2026-07-01", "value": "."},
    ]
}


def test_parse_banxico_series_keeps_only_real_values():
    observations = parse_banxico_series(BANXICO_RAW, series_name="Tasa objetivo")

    assert len(observations) == 1  # the N/E and empty-string rows are dropped
    obs = observations[0]
    assert obs.series_id == "SF61745"
    assert obs.series_name == "Tasa objetivo"
    assert obs.value == 8.25
    assert obs.observed_on == date(2026, 9, 7)
    assert obs.source_name == "banxico_sie"
    assert obs.country == "MX"


def test_parse_banxico_series_empty_datos():
    assert parse_banxico_series({"bmx": {"series": []}}, series_name="x") == []


def test_parse_fred_series_drops_the_dot_null_marker():
    observations = parse_fred_series(FRED_RAW, series_id="FEDFUNDS", series_name="Federal Funds Rate")

    assert len(observations) == 1
    obs = observations[0]
    assert obs.series_id == "FEDFUNDS"
    assert obs.value == 4.33
    assert obs.observed_on == date(2026, 8, 1)
    assert obs.source_name == "fred_economic_data"
    assert obs.country == "US"
