"""Phase 18 (Reflex, ADR-012): plumbing only. Every event handler here
calls straight into `app/*` pipeline modules, in-process — no separate
API service, no business logic of its own (ARCHITECTURE.md §3's
dependency rule for `frontend/*`). Blocking calls (Postgres, the LLM
call) run via `asyncio.to_thread` so a slow `/analyze` request doesn't
freeze the whole app for other pages.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import plotly.graph_objects as go
import reflex as rx

from app.analysis import trending
from app.analysis.analysis_store import add_to_monitor, insert_analysis, remove_from_monitor
from app.analysis.augmentation import assemble_context
from app.analysis.synthesis import aggregate_evidence
from app.guardrails.analysis_guard import check_input_relevance, guard_analysis
from app.retrieval import sql_retriever
from app.retrieval.vector_retriever import retrieve
from app.services.db import get_connection
from app.services.llm_service import generate_synthesis

# Discovery ("Extension — Discovery", D6) reads only — no LLM/guardrail
# imports here; the scan itself runs in refresh_worker (D5), never
# triggered from the UI.
from app.retrieval.sql_retriever import get_general_news_by_ids, get_latest_suggestions


def _f(value) -> Optional[float]:
    """Decimal (from psycopg) isn't JSON-serializable as a Reflex var —
    every numeric field crossing into state must be cast to plain float."""
    return float(value) if value is not None else None


def _money(value) -> str:
    v = _f(value)
    return f"${v:,.2f}" if v is not None else "—"


def _pct(value) -> str:
    """A signed percent, for values that move relative to a baseline
    (price change, margins). A leading "+" reads as "up from something" —
    correct for those, wrong for a plain magnitude like confidence."""
    v = _f(value)
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v:.2f}%"


def _pct_plain(value) -> str:
    """An unsigned percent — for magnitudes with no baseline to move
    from, like a confidence score. `_pct`'s leading "+" would misleadingly
    imply "up from X%", which confidence has no meaning being up from."""
    v = _f(value)
    return f"{v:.2f}%" if v is not None else "—"


def _num(value, decimals: int = 2) -> str:
    v = _f(value)
    return f"{v:,.{decimals}f}" if v is not None else "—"


def _observation_dict(obs) -> dict:
    if obs is None:
        return {}
    change = None
    if obs.price is not None and obs.previous_close:
        change = (float(obs.price) - float(obs.previous_close)) / float(obs.previous_close) * 100
    return {
        "price_display": _money(obs.price),
        "previous_close_display": _money(obs.previous_close),
        "day_high_display": _money(obs.day_high),
        "day_low_display": _money(obs.day_low),
        "year_high_display": _money(obs.year_high),
        "year_low_display": _money(obs.year_low),
        "fifty_day_average_display": _money(obs.fifty_day_average),
        "two_hundred_day_average_display": _money(obs.two_hundred_day_average),
        "volume_display": _num(obs.volume, 0),
        "market_cap_display": _num(obs.market_cap, 0),
        "change_display": _pct(change) if change is not None else "—",
        "change_color": ("green" if change >= 0 else "red") if change is not None else "gray",
        "observed_at": obs.observed_at.isoformat() if obs.observed_at else "",
        "source_name": obs.source_name,
    }


def _instrument_dict(row) -> dict:
    if row is None:
        return {}
    return {
        "name": row.name or row.symbol,
        "exchange": row.exchange or "",
        "currency": row.currency or "",
        "sector": row.sector or "",
        "industry": row.industry or "",
        "country": row.country or "",
    }


def _fundamentals_dict(row) -> dict:
    if row is None:
        return {}
    return {
        "as_of": row.snapshot_date.isoformat() if row.snapshot_date else "",
        "pe_ratio_display": _num(row.pe_ratio),
        "pb_ratio_display": _num(row.pb_ratio),
        "ev_ebitda_display": _num(row.ev_ebitda),
        "dividend_yield_display": _pct(row.dividend_yield) if row.dividend_yield is not None else "—",
        "market_cap_display": _num(row.market_cap, 0),
        "revenue_display": _num(row.revenue, 0),
        "net_income_display": _num(row.net_income, 0),
        "eps_display": _num(row.eps),
        "gross_margin_display": _pct((row.gross_margin or 0) * 100) if row.gross_margin is not None else "—",
        "roe_display": _pct((row.roe or 0) * 100) if row.roe is not None else "—",
    }


def _rating_dict(row) -> dict:
    return {
        "rated_at": row.rated_at.isoformat() if row.rated_at else "",
        "firm": row.firm,
        "action": row.action,
        "from_grade": row.from_grade or "",
        "to_grade": row.to_grade or "",
    }


def _bar_dict(row) -> dict:
    return {
        "date": row.bar_date.isoformat(),
        "open": _f(row.open),
        "high": _f(row.high),
        "low": _f(row.low),
        "close": _f(row.close),
        "volume": _f(row.volume),
    }


def _analysis_dict(row) -> dict:
    return {
        "requested_at": row.requested_at.isoformat() if row.requested_at else "",
        "stance": row.stance,
        "confidence_display": _pct_plain((row.confidence or 0) * 100),
        "quality_status": row.quality_status,
        "rationale": row.rationale,
    }


class DashboardState(rx.State):
    """The dashboard/index page — trending, ranked by movement, over the
    monitor list (README §2's "what's trending among the stuff I'm
    watching?"). Entries are plain dicts (`list[dict]` is a Reflex var
    type stable across versions), not a custom struct class — this
    version's custom-model API (`rx.Base` et al.) was restructured and
    isn't worth pinning code to from memory when a dict does the job."""

    entries: list[dict] = []
    is_loading: bool = False
    error: str = ""

    @rx.event(background=True)
    async def load(self):
        async with self:
            self.is_loading = True
            self.error = ""
        try:
            entries = await asyncio.to_thread(self._load_sync)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI, not swallowed
            async with self:
                self.error = f"Failed to load dashboard: {exc}"
                self.is_loading = False
            return
        async with self:
            self.entries = entries
            self.is_loading = False

    @staticmethod
    def _load_sync() -> list[dict]:
        with get_connection() as conn:
            monitored = sql_retriever.get_monitored_symbols(active_only=True, conn=conn)
            observations = {}
            thesis_by_symbol = {}
            for m in monitored:
                obs = sql_retriever.get_recent_observations(m.symbol, limit=1, conn=conn)
                if obs:
                    observations[m.symbol] = obs[0]
                thesis_by_symbol[m.symbol] = m.thesis or ""
        ranked = trending.rank_by_movement(observations)
        return [
            {
                "symbol": e.symbol,
                # Pre-formatted display strings, not raw floats: Reflex Var
                # format-spec behavior (f"{var:.2f}") varies enough across
                # versions that formatting server-side, once, is the safer
                # bet than depending on it inside a page template.
                "price_display": f"${e.price:,.2f}" if e.price is not None else "—",
                "change_display": (
                    f"{'+' if e.percent_change >= 0 else ''}{e.percent_change:.2f}%"
                    if e.percent_change is not None
                    else "—"
                ),
                "change_color": (
                    "green" if (e.percent_change or 0) >= 0 else "red"
                ) if e.percent_change is not None else "gray",
                "volume_display": f"{e.volume:,.0f}" if e.volume is not None else "—",
                "thesis": thesis_by_symbol.get(e.symbol, ""),
            }
            for e in ranked
        ]

    @rx.event(background=True)
    async def remove_symbol(self, symbol: str):
        await asyncio.to_thread(remove_from_monitor, symbol)
        async with self:
            pass
        await self.load()


class SymbolState(rx.State):
    """Symbol detail page — current status, a real candlestick chart from
    `daily_bars`, and analysis history."""

    # Named current_symbol, not symbol: Reflex reserves the dynamic route
    # arg name ([symbol] on this page's own route) globally — no state,
    # including this page's own, may declare a plain field with that
    # exact name (`DynamicRouteArgShadowsStateVarError`). The route value
    # is still read via `self.router.page.params` in `load()` below.
    current_symbol: str = ""
    instrument: dict = {}
    observation: dict = {}
    bars: list[dict] = []
    analyses: list[dict] = []
    is_loading: bool = False
    error: str = ""
    is_monitored: bool = False

    @rx.var
    def candlestick_figure(self) -> go.Figure:
        """`reflex_components_plotly.Plotly`'s `data` prop expects a real
        `plotly.graph_objs.Figure`, not a plain data/layout dict pair —
        confirmed only by actually compiling the app (it raised a
        `TypeError` naming the expected type), not assumed from memory."""
        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=[b["date"] for b in self.bars],
                    open=[b["open"] for b in self.bars],
                    high=[b["high"] for b in self.bars],
                    low=[b["low"] for b in self.bars],
                    close=[b["close"] for b in self.bars],
                )
            ]
        )
        fig.update_layout(
            margin={"t": 20, "b": 40, "l": 50, "r": 20},
            xaxis_rangeslider_visible=False,
            height=400,
        )
        return fig

    @rx.event(background=True)
    async def load(self):
        # `router.page` is deprecated (0.8.1, removed at 1.0) in favor of
        # `router.url` — but `router.url` only exposes query-string
        # parameters (`.query_parameters`), not dynamic PATH segments like
        # this page's own `[symbol]`. There is no documented replacement
        # for path-segment params yet, so this stays on the deprecated
        # (still functional) property rather than reaching for a private
        # API; revisit once Reflex ships one.
        symbol = self.router.page.params.get("symbol", "").upper()
        if not symbol:
            return
        async with self:
            self.current_symbol = symbol
            self.is_loading = True
            self.error = ""
        try:
            data = await asyncio.to_thread(self._load_sync, symbol)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.error = f"Failed to load {symbol}: {exc}"
                self.is_loading = False
            return
        async with self:
            self.instrument = data["instrument"]
            self.observation = data["observation"]
            self.bars = data["bars"]
            self.analyses = data["analyses"]
            self.is_monitored = data["is_monitored"]
            self.is_loading = False

    @staticmethod
    def _load_sync(symbol: str) -> dict:
        with get_connection() as conn:
            instrument = sql_retriever.get_instrument(symbol, conn=conn)
            observations = sql_retriever.get_recent_observations(symbol, limit=1, conn=conn)
            bars = sql_retriever.get_recent_daily_bars(symbol, limit=90, conn=conn)
            analyses = sql_retriever.get_recent_analyses(symbol, limit=10, conn=conn)
            monitored = sql_retriever.get_monitored_symbols(active_only=True, conn=conn)
        is_monitored = any(m.symbol == symbol for m in monitored)
        return {
            "instrument": _instrument_dict(instrument),
            "observation": _observation_dict(observations[0] if observations else None),
            "bars": [_bar_dict(b) for b in reversed(bars)],  # oldest-first for a left-to-right chart
            "analyses": [_analysis_dict(a) for a in analyses],
            "is_monitored": is_monitored,
        }

    @rx.event(background=True)
    async def toggle_monitor(self):
        symbol = self.current_symbol
        if not symbol:
            return
        is_monitored = self.is_monitored
        if is_monitored:
            await asyncio.to_thread(remove_from_monitor, symbol)
        else:
            await asyncio.to_thread(add_to_monitor, symbol)
        async with self:
            self.is_monitored = not is_monitored


class AnalyzeState(rx.State):
    """The analyze form — the one path touching both retrieval types
    (ARCHITECTURE.md §4's "conductor" note): sql_retriever + vector
    retrieval -> augmentation -> synthesis -> generation -> the
    confidence gate -> persist."""

    # Named symbol_input, not symbol: a dynamic route var named `symbol`
    # ([symbol] on the symbol-detail page) is reserved across every
    # state — Reflex refused to compile with a same-named field here,
    # correctly flagging the collision (`DynamicRouteArgShadowsStateVarError`).
    symbol_input: str = ""
    query: str = ""
    is_loading: bool = False
    out_of_scope_reason: str = ""
    error: str = ""
    is_monitored: bool = False

    # Flattened, not one nested `result: dict` blob: subscripting a plain
    # `dict` var loses type information (`typing.Any`), so calling a
    # method like `.length()` on `result["citations"]` raised a real
    # `UntypedVarError` — caught by compiling, not assumed from memory.
    # Individual typed fields sidestep the issue entirely.
    has_result: bool = False
    result_stance: str = ""
    result_confidence_display: str = ""
    result_quality_status: str = ""
    result_rationale: str = ""
    result_citations: list[dict] = []
    result_reliability_rule_passed: bool = True
    result_low_confidence: bool = False

    def set_symbol(self, value: str):
        self.symbol_input = value.upper()

    def set_query(self, value: str):
        self.query = value

    def load_from_query(self):
        """A suggestion on `/feeds` links here as `/analyze?symbol=...` —
        a suggestion is a lead, never a grounded analysis, so it routes
        into the real guardrailed pipeline rather than straight to
        monitor (CLAUDE.md's "Extension — Discovery" design). Query
        params, not a path segment, so `router.url.query_parameters`
        (state.py's existing note on why path params can't cover this).
        """
        symbol = self.router.url.query_parameters.get("symbol", "")
        if symbol:
            self.symbol_input = symbol.upper()

    @rx.event(background=True)
    async def run_analysis(self):
        symbol = self.symbol_input.strip().upper()
        query = self.query.strip()
        if not symbol or not query:
            async with self:
                self.error = "Enter both a symbol and a question."
            return

        relevance = check_input_relevance(query)
        if not relevance.in_scope:
            async with self:
                self.out_of_scope_reason = relevance.reason or ""
                self.has_result = False
                self.error = ""
            return

        async with self:
            self.is_loading = True
            self.error = ""
            self.out_of_scope_reason = ""
            self.has_result = False

        try:
            result = await asyncio.to_thread(self._run_sync, symbol, query)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.error = f"Analysis failed: {exc}"
                self.is_loading = False
            return

        async with self:
            self.result_stance = result["stance"]
            self.result_confidence_display = result["confidence_display"]
            self.result_quality_status = result["quality_status"]
            self.result_rationale = result["rationale"]
            self.result_citations = result["citations"]
            self.result_reliability_rule_passed = result["reliability_rule_passed"]
            self.result_low_confidence = result["low_confidence"]
            self.has_result = True
            self.is_monitored = False
            self.is_loading = False

    @staticmethod
    def _run_sync(symbol: str, query: str) -> dict:
        with get_connection() as conn:
            instrument = sql_retriever.get_instrument(symbol, conn=conn)
            observations = sql_retriever.get_recent_observations(symbol, limit=1, conn=conn)
            daily_bars = sql_retriever.get_recent_daily_bars(symbol, limit=60, conn=conn)
            fundamentals = sql_retriever.get_latest_fundamentals(symbol, conn=conn)
            ratings = sql_retriever.get_recent_analyst_ratings(symbol, limit=5, conn=conn)
            econ = sql_retriever.get_recent_economic_indicators(
                sql_retriever.country_for_symbol(symbol), limit=5, conn=conn
            )
            retrieval = retrieve(symbol, query, conn=conn)
            observation = observations[0] if observations else None

            ctx = assemble_context(
                symbol, instrument=instrument, observation=observation, daily_bars=daily_bars,
                fundamentals=fundamentals, analyst_ratings=ratings, economic_indicators=econ,
                retrieval=retrieval,
            )
            aggregate = aggregate_evidence(retrieval)
            synthesis = generate_synthesis(symbol, query, ctx.context, aggregate, ctx.low_confidence)
            guarded = guard_analysis(synthesis, retrieval, aggregate, observation, daily_bars, fundamentals, econ)
            insert_analysis(symbol, query, synthesis, guarded, conn=conn)
            conn.commit()

        return {
            "stance": guarded.stance,
            "confidence_display": _pct_plain(guarded.confidence * 100),
            "quality_status": guarded.quality_status,
            "rationale": guarded.rationale,
            "citations": [{"chunk_id": c.chunk_id, "claim": c.claim} for c in synthesis.citations],
            "resolved_citations": guarded.resolved_citations,
            "dangling_citations": guarded.dangling_citations,
            "reliability_rule_passed": guarded.reliability_rule_passed,
            "low_confidence": retrieval.low_confidence,
        }

    @rx.event(background=True)
    async def add_result_to_monitor(self):
        symbol = self.symbol_input.strip().upper()
        if not symbol:
            return
        await asyncio.to_thread(add_to_monitor, symbol)
        async with self:
            self.is_monitored = True


def _suggestion_dict(row, articles_by_id: dict) -> dict:
    # A pre-rendered markdown string, not a nested list[dict]: a second
    # rx.foreach over entry["sources"] (entry itself already an iteration
    # var from the outer foreach) raised a real ForeachVarError — Reflex
    # loses type information on a subscript of a subscript, the same
    # family of issue as AnalyzeState.result's own flattening fix, just
    # one level deeper here. A single string field sidesteps it entirely;
    # rx.markdown renders the links.
    sources_markdown = "\n".join(
        f"- [{articles_by_id[a].headline}]({articles_by_id[a].url})"
        for a in row.source_article_ids
        if a in articles_by_id
    )
    return {
        "symbol": row.symbol,
        "company_name": row.company_name,
        "reasoning": row.reasoning,
        "generated_at": row.generated_at.isoformat() if row.generated_at else "",
        "sources_markdown": sources_markdown,
    }


class FeedsState(rx.State):
    """`/feeds` (D6) — reads the latest scheduled-only discovery batch
    (`refresh_worker`'s daily job, D5); this page never triggers a scan
    itself, matching CLAUDE.md's "the UI only ever reads the latest
    persisted batch" design."""

    suggestions: list[dict] = []
    is_loading: bool = False
    error: str = ""

    @rx.event(background=True)
    async def load(self):
        async with self:
            self.is_loading = True
            self.error = ""
        try:
            suggestions = await asyncio.to_thread(self._load_sync)
        except Exception as exc:  # noqa: BLE001
            async with self:
                self.error = f"Failed to load suggestions: {exc}"
                self.is_loading = False
            return
        async with self:
            self.suggestions = suggestions
            self.is_loading = False

    @staticmethod
    def _load_sync() -> list[dict]:
        with get_connection() as conn:
            rows = get_latest_suggestions(limit=20, conn=conn)
            all_article_ids = {a for row in rows for a in row.source_article_ids}
            articles = get_general_news_by_ids(list(all_article_ids), conn=conn)
        articles_by_id = {a.id: a for a in articles}
        return [_suggestion_dict(row, articles_by_id) for row in rows]
