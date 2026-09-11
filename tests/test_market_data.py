from app.services.market_data import _fast_info_float, _fast_info_str, get_quote_yfinance


class _FakeFastInfo(dict):
    """Mimics yfinance's real FastInfo quirk (confirmed live 2026-09-10):
    bracket access works for every real key, but .get() silently returns
    None for several of them (day_high, year_high, market_cap, quote_type
    reproduced) even though the key genuinely has a value. _fast_info_*
    must never rely on .get() — this fixture makes .get() always lie, so
    any regression back to .get() fails loudly.
    """

    def get(self, key, default=None):
        return default  # deliberately broken, matching the real quirk


def test_fast_info_float_uses_bracket_access_not_get():
    fast = _FakeFastInfo(day_high=326.68)
    assert _fast_info_float(fast, "day_high") == 326.68


def test_fast_info_float_missing_key_returns_none():
    fast = _FakeFastInfo(day_high=326.68)
    assert _fast_info_float(fast, "year_high") is None


def test_fast_info_str_uses_bracket_access_not_get():
    fast = _FakeFastInfo(quote_type="EQUITY")
    assert _fast_info_str(fast, "quote_type") == "EQUITY"


def test_get_quote_yfinance_populates_full_fast_info_set(monkeypatch):
    fast = _FakeFastInfo(
        last_price=326.57,
        previous_close=318.0,
        last_volume=69_820_744.0,
        open=316.79,
        day_high=326.68,
        day_low=316.57,
        year_high=344.57,
        year_low=226.65,
        fifty_day_average=316.47,
        two_hundred_day_average=284.35,
        market_cap=4_766_021_362_600.0,
        exchange="NMS",
        currency="USD",
        quote_type="EQUITY",
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.fast_info = fast

    monkeypatch.setattr("app.services.market_data.yf.Ticker", FakeTicker)

    quote = get_quote_yfinance("AAPL")

    assert quote.price == 326.57
    assert quote.previous_close == 318.0
    assert quote.day_high == 326.68
    assert quote.year_high == 344.57
    assert quote.fifty_day_average == 316.47
    assert quote.market_cap == 4_766_021_362_600.0
    assert quote.exchange == "NMS"
    assert quote.quote_type == "EQUITY"
