# Trading Advisor

## 1. What this is

A personal market-analysis and monitoring tool. **No brokerage account, no
order execution, of any kind** — this is not a trading bot and never was
going to place a trade in this version. **No social or community feed of
any kind, ever** — not Reddit, not chart-site comment sections; every
source is either an official/regulatory data provider or a
professional-newsroom outlet. Given a company/symbol, it reads from
several independently **configured** data sources — structured
quotes/OHLCV (`yfinance`, Finnhub, covering both US/global markets and the
Bolsa Mexicana de Valores via `.MX` tickers), official economic data
(Banxico's SIE, the St. Louis Fed's FRED), and professional news (SEC
filings, Finnhub, Yahoo Finance, El Financiero, El Economista) — persists
what it reads, and can produce a plain-language analysis grounded in that
data on request. It also keeps a personal watchlist ("monitor list") with a
dashboard showing every watched symbol at a glance and a per-symbol
drill-down. Which sources are active is a config-file decision
(`data_catalog.yaml`), not a code change.

This replaces two earlier versions of this project's scope: an Alpaca
paper-trading execution advisor, and a TradingView-only version depending
on a locally-run TradingView Desktop app. Both are gone, not paused — see
`ARCHITECTURE.md`'s Appendix for the ADRs.

## 2. Functional requirements

- Retrieve and persist market data from several independently configured
  sources for every monitored symbol, on each source's own cadence
  (`data_catalog.yaml`): quote ticks and adjusted-close daily OHLCV bars,
  instrument reference data (exchange, sector, industry, currency),
  valuation and fundamentals snapshots (P/E, market cap, revenue, margins),
  analyst rating changes, official macro/economic series (Banxico, FRED),
  and professional news (SEC filings, Finnhub, Yahoo Finance, El
  Financiero, El Economista) — see `ARCHITECTURE.md`'s ADR-007 for the
  full data-category audit this was scoped from.
- Show a **trending** view: which monitored symbols moved the most (price %
  change, volume) over the persisted history.
- Let the user pick a monitored symbol and see its **current live status**
  (price, quote) and recent trend, refreshed within a stated freshness
  budget — not just the last scheduled reading.
- Provide an **input form to look up any company/symbol**, monitored or not,
  and run an on-demand analysis: a plain-language read of its current status
  and trend, grounded in persisted price/fundamentals/valuation history,
  official economic data, and professional news/filings actually retrieved
  for it — with per-claim source citations. Every analysis is persisted,
  whether or not the user acts on it.
- Provide a button on a finished analysis to **add that symbol to the
  monitor list**, so it starts appearing in the trending view and dashboard
  going forward.
- Provide a **consolidated dashboard**: one chart of every monitored
  symbol together, with the ability to select one and see its full detail
  (chart, past analyses, and the sources cited in each).

## 2a. Example queries

- "What's trending among the stuff I'm watching?"
- "Show me NVDA's current price and trend."
- "Run an analysis on a company I don't currently track — say, PLTR."
- "Add PLTR to my monitor dashboard."
- "Show me the consolidated chart of everything I'm watching."
- "What did the last analysis on AAPL actually say, and when did I run it?"
- "Has SPY moved more than 5% today?"
- "Why did NVDA move today?" — grounded in retrieved news/filings, not just
  price history; the case that specifically needs Axis 3, not Axis 2 alone.
- "Show me WALMEX on the BMV." — Mexican-market coverage, not just US/global.
- "Has Banxico signaled anything about the next rate decision?" — grounded
  in official Banxico/FRED economic data, not scraped or guessed.
- "Buy me 10 shares of TSLA." — explicitly **out of scope**: the system has
  no way to act on this and must say so, not quietly reinterpret it as an
  analysis request.

## 3. User profile

- **Who uses this**: a single person, personal use only.
- **Expected users at MVP**: 1.
- **How they interact with it**: a local Streamlit UI (per `PLAYBOOK.md`
  §4a) — a trending list, a symbol detail view, an "analyze a company" form,
  and the consolidated monitor dashboard.

## 4. Source material

- [`data_catalog.yaml`](data_catalog.yaml) — the nine configured sources,
  per `production-rag-handbook`'s `articles/s06-02` audit format: two
  structured quote vendors, two official economic-data APIs (Banxico,
  FRED), and five news sources (SEC filings, Finnhub, Yahoo Finance, El
  Financiero, El Economista) — each with its own refresh cadence and
  quality scoring. Plus three deliberately-excluded-with-a-written-reason
  candidates (TradingView, Google Finance, Investing.com — see
  `ARCHITECTURE.md`'s ADR-006). Toggling a source on/off is an edit to this
  file, not a code change.
- The observation history, analysis history, and vector chunk store
  (Postgres tables, schema in `ARCHITECTURE.md`) don't exist yet —
  generated by the running system, not supplied as source files.
- [`examples/thesis-v1-archived-alpaca-execution.md`](examples/thesis-v1-archived-alpaca-execution.md)
  — the original execution-era risk-rules document. Retired, kept for
  history only; no code in this version reads it.

## 5. Other key points

- **No brokerage account, no order execution, no position sizing or
  portfolio risk rules — and no cost-basis/P&L tracking either.** This
  version manages no real or paper capital in any way, and never will;
  `alpaca-core` and `alpaca-mcp` (sibling repos built for the original
  scope) have been deleted — they had no purpose left once execution was
  dropped; see `ARCHITECTURE.md`'s ADR-001. The one personal-tracking
  feature that *is* in scope: a one-line `thesis` note on why a symbol is
  being watched — an annotation, not a position (ADR-007).
- **Individual-stock lookups are in scope.** The original "diversified funds
  only" constraint existed to bound *execution* risk; with no execution
  path, it no longer applies.
- **No single external dependency the whole system hinges on.** Unlike the
  retired TradingView-only version, every source is a plain HTTPS API — no
  desktop app, no CDP connection, nothing that must run on the operator's
  own machine outside `docker compose`.
- **No social or community content of any kind.** Reddit was tried and
  dropped entirely (2026-09-10, ADR-006) — not merely downweighted. Every
  remaining source is an official/regulatory data provider or a
  professional newsroom.
- **Covers the Bolsa Mexicana de Valores, not just US/global markets** —
  `yfinance` already supports `.MX` tickers, and Banxico/El Financiero/El
  Economista ground Mexico-specific analysis directly.
- **Analysis output is labeled BULLISH / BEARISH / NEUTRAL**, not
  BUY/SELL/HOLD — a deliberate wording choice now that nothing in this
  system can execute an order; see `ARCHITECTURE.md`'s ADR-002.
- **Not investment advice.** Personal-use tooling, same posture as both
  reference projects this design studied.

## 6. Status

- [x] README rewritten for the pivot away from execution and away from
      TradingView
- [x] CLAUDE.md rewritten — Axis 3 (vector RAG) now active
- [x] ARCHITECTURE.md rewritten — ADR-001 through ADR-006 recorded
- [x] `data_catalog.yaml` redesigned (2026-09-10, ADR-006) — Reddit and
      TradingView dropped, Banxico/FRED/Yahoo-news/El Financiero/El
      Economista added; 9 sources included, 3 excluded-with-reason
- [x] `alpaca-core` / `alpaca-mcp` — deleted; orphaned by the first pivot
- [x] Phase 1-8 done: repo scaffold, `data_catalog.yaml`, all parsers for
      the redesigned source list, `document_chunks` schema + embeddings
- [x] `EDGAR_USER_AGENT`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` set
- [ ] API keys/credentials still needed: `FINNHUB_API_KEY`,
      `BANXICO_SIE_TOKEN`, `FRED_API_KEY` — external prerequisites, no code
- [x] Data-category audit against an 8-part market-data framework
      (2026-09-10, ADR-007) — scoped into Phase 9: OHLCV, instrument
      reference, fundamentals/valuation, analyst ratings, technical
      indicators (mostly free from data already fetched)
- [ ] Phase 9 (scheduled refresh; 7 new/widened tables —
      `market_observations`, `instruments`, `daily_bars`, `fundamentals`,
      `analyst_ratings`, `economic_indicators`, `monitored_symbols`) —
      next up
