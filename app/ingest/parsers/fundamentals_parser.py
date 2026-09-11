"""Valuation metrics + reported financials merged into one snapshot table
(ADR-007, articles/s10-05's schema-divergence rule — both are "a company's
financial snapshot as of a date," not divergent enough to split). Sourced
from yfinance's Ticker.info (valuation ratios) plus quarterly_financials/
quarterly_balance_sheet (reported financials) — three calls, one record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from app.ingest.catalog import CatalogSource


@dataclass
class FundamentalsRecord:
    symbol: str
    snapshot_date: date
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    ev_ebitda: Optional[float]
    dividend_yield: Optional[float]
    fcf_yield: Optional[float]
    market_cap: Optional[float]
    revenue: Optional[float]
    net_income: Optional[float]
    eps: Optional[float]
    gross_margin: Optional[float]
    operating_margin: Optional[float]
    debt_to_equity: Optional[float]
    roe: Optional[float]  # single-quarter net income / equity — a v1 proxy, not an annualized TTM figure
    source_name: str
    reliability_tier: int


def _latest_value(df: pd.DataFrame, row_label: str) -> Optional[float]:
    if df.empty or row_label not in df.index:
        return None
    value = df.loc[row_label].iloc[0]
    return float(value) if pd.notna(value) else None


def parse_fundamentals(
    symbol: str,
    info: dict,
    quarterly_financials: pd.DataFrame,
    quarterly_balance_sheet: pd.DataFrame,
    catalog_source: CatalogSource,
) -> FundamentalsRecord:
    revenue = _latest_value(quarterly_financials, "Total Revenue")
    net_income = _latest_value(quarterly_financials, "Net Income")
    gross_profit = _latest_value(quarterly_financials, "Gross Profit")
    operating_income = _latest_value(quarterly_financials, "Operating Income")
    eps = _latest_value(quarterly_financials, "Diluted EPS")
    total_debt = _latest_value(quarterly_balance_sheet, "Total Debt")
    stockholders_equity = _latest_value(quarterly_balance_sheet, "Stockholders Equity")

    snapshot_date = (
        quarterly_financials.columns[0].date() if not quarterly_financials.empty else date.today()
    )

    market_cap = info.get("marketCap")
    free_cash_flow = info.get("freeCashflow")

    return FundamentalsRecord(
        symbol=symbol,
        snapshot_date=snapshot_date,
        pe_ratio=info.get("trailingPE"),
        pb_ratio=info.get("priceToBook"),
        ev_ebitda=info.get("enterpriseToEbitda"),
        dividend_yield=info.get("dividendYield"),
        fcf_yield=(free_cash_flow / market_cap) if free_cash_flow and market_cap else None,
        market_cap=market_cap,
        revenue=revenue,
        net_income=net_income,
        eps=eps,
        gross_margin=(gross_profit / revenue) if gross_profit is not None and revenue else None,
        operating_margin=(operating_income / revenue) if operating_income is not None and revenue else None,
        debt_to_equity=(total_debt / stockholders_equity) if total_debt is not None and stockholders_equity else None,
        roe=(net_income / stockholders_equity) if net_income is not None and stockholders_equity else None,
        source_name=catalog_source.name,
        reliability_tier=catalog_source.reliability_tier,
    )
