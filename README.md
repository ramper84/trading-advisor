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
- Provide a **discovery feed**: on a daily schedule, scan general
  (non-symbol-filtered) news from the already-configured professional
  sources and suggest companies worth a look, each with a plain-language
  reason and links to the source articles — never added to the monitor
  list directly; a suggestion routes into the analyze form so it passes
  through the same grounded, guardrailed pipeline as any other lookup.
  Added 2026-09-12, `CLAUDE.md`'s "Extension — Discovery" section.

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
- "What companies is the feed suggesting today, and why?" — the discovery
  capability; answered from a daily scan, not computed on demand.

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
- [x] All credentials set: `EDGAR_USER_AGENT`, `OPENAI_API_KEY`,
      `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `BANXICO_SIE_TOKEN`,
      `FRED_API_KEY`
- [x] Data-category audit against an 8-part market-data framework
      (2026-09-10, ADR-007) — scoped into Phase 9: OHLCV, instrument
      reference, fundamentals/valuation, analyst ratings, technical
      indicators (mostly free from data already fetched)
- [x] Phase 9 — scheduled refresh, 7 tables, 5 new parsers, `refresh_worker`
      wired end to end. Verified live twice against a real Postgres
      instance: once with `AAPL` only (1018 SEC filing chunks, 977 analyst
      ratings), once with `AAPL` + `WALMEX.MX` after all credentials were
      obtained — the BMV-coverage claim exercised for real, not just
      asserted. 5 real bugs found and fixed (`.env` comment-parsing, an
      embedding token-limit crash, a `yfinance` library quirk, a Finnhub
      routing bug, an unbounded FRED history pull). 76 tests passing.
- [x] `FINNHUB_API_KEY`, `BANXICO_SIE_TOKEN`, `FRED_API_KEY` obtained and
      set — all nine included sources now have real credentials where
      needed (Banxico series ids confirmed live too)
- [x] Phase 10 — retrieval layer: `sql_retriever.py` (Axis 2),
      `hybrid_search.py` + `temporal.py` + `vector_retriever.py` (Axis 3,
      hard filter → RRF-fused semantic+lexical → temporal weighting →
      distance-threshold soft-fail). 106 tests passing. Verified live
      against real embedded `AAPL` data — the soft-fail gate confirmed
      both ways (a paraphrased query correctly abstains, a near-verbatim
      one correctly answers). Four real bugs found and fixed: an
      unbounded SEC EDGAR refetch, a naive/aware `datetime` comparison, a
      missing `::vector` cast, and an `httpx`-logging gap that would have
      leaked `FRED_API_KEY` into container logs on every scheduled poll
      (see `ARCHITECTURE.md`'s ADR-008). The exposed `FRED_API_KEY` has
      been rotated.
- [x] Phase 11 — augmentation: `app/analysis/augmentation.py` assembles
      SQL + vector retrieval into one XML-delimited context — a
      deterministic `<market_data>` block (instrument, latest quote,
      fundamentals, technical indicators, analyst ratings, economic
      indicators) plus edge-loaded, budget-fit `<source>` blocks from the
      retrieved filing/news chunks. 119 tests passing. Verified live
      against real `AAPL` data: a full context assembled with nothing
      dropped at the default budget, then re-run at a deliberately tight
      budget to confirm the drop-and-log behavior fires on real retrieved
      chunks, not just a synthetic fixture. No router yet — `POST
      /analyze` isn't a coherent endpoint until Phase 12 (generation) and
      Phase 13 (the confidence gate) exist behind it.
- [x] Phase 12 — generation: `app/analysis/synthesis.py` computes a
      deterministic per-citation weight (fusion rank + temporal weight +
      reliability tier) and a weighted-median lean anchor with a corrected
      `contested` flag (strong citations only — a lone weak outlier can't
      manufacture a contradiction); `app/services/llm_service.py` makes
      the one generation call (`gpt-4o-mini` primary, Claude Haiku 4.5
      fallback) that reasons over it. 137 tests passing. Verified live
      with real `AAPL` data and **real LLM calls**: a genuine `gpt-4o-mini`
      run produced a correct `NEUTRAL` stance explaining a real contested
      signal, citing two chunk_ids independently confirmed present in the
      real retrieved set; the fallback path was live-verified twice,
      including through a forced-failure run of the real Instructor
      integration. No router or `analyses`-table persistence yet — Phase
      13's confidence gate is what computes the `quality_status` a
      persisted row needs.
- [x] Phase 13 — guardrails: `app/guardrails/analysis_guard.py` runs the
      confidence gate (citation integrity, numeric grounding against real
      retrieved values, the reliability-tier rule) plus an input-relevance
      check that separates real analysis questions from execution-shaped
      requests ("buy me 10 shares"). 162 tests passing. Verified live with
      a real `gpt-4o-mini` call: all citations resolved cleanly, no
      fabricated figures, `degraded` purely from thin retrieval (not
      forced to abstain on otherwise-clean evidence). One real UX gap
      found and fixed live: the model named raw source numbers in prose
      that didn't match its own structured citations — harmless to the
      guardrail (the structured field is authoritative) but misleading to
      a reader; fixed with a prompt tightening. Phases 10-13 now form a
      complete, independently-verified `/analyze` pipeline.
- [x] Frontend switched from Streamlit to **Reflex** (ADR-012) —
      explored Dash/Reflex/a React+Tremor stack, honest tradeoffs
      compared, Reflex chosen for a modern app feel without a second
      language for one user to maintain. A real architecture
      simplification came with it: no separate `api` service or
      `routers/*` layer — Reflex's own backend calls `app/*` directly.
- [x] Phase 18 — Reflex UI: dashboard (trending), symbol detail (a real
      Plotly-native candlestick chart), and the analyze form (citations,
      quality flags, "add to monitor"). Closed two backend gaps that had
      been open since Phase 1: `trending.py` and `analysis_store.py` (+
      the `analyses` table) were never built until now. 174 backend tests
      passing (the Reflex frontend itself has no pytest coverage of its
      own — compiling and running it live was the verification).
      Live-verified with a real headless browser against real
      `AAPL` data and a real `gpt-4o-mini` call — five real bugs found by
      actually compiling/running the app (two dynamic-route/state-var
      name collisions, an unsupported Var operation, a Plotly prop
      type mismatch, an untyped-Var method call), all fixed. Docker
      packaging attempted early: one bug fixed (`unzip` missing for
      Reflex's bundled `bun`), **one left open for Phase 19-20**: dynamic
      routes 404 under `reflex run --env prod --single-port` in a real
      container.
- [x] Phase 14-15 skipped (no agentic loop, no orchestration trigger).
- [x] Phase 19-20 — local validation: `docker compose up` run for real,
      end to end, not just individual containers. Fixed the dynamic-route
      404 left open by Phase 18 (Reflex's static export already builds a
      `__spa-fallback.html` shell for exactly this case; the built-in
      server just never served it — wired up by hand via `api_transformer`)
      and a second bug found only by clicking through the full user
      journey against the real stack: the dashboard/symbol-detail pages
      used `on_mount`, which doesn't refire on revisiting an
      already-mounted SPA route, so a newly-monitored symbol never
      appeared without a hard refresh — fixed by switching to `add_page`'s
      `on_load`. Confirmed live: a genuinely unknown symbol correctly
      abstains (`insufficient`/`NEUTRAL`), even catching a hallucinated
      citation along the way. 174 tests passing. **A real credential
      exposure happened during this pass** (a debugging `docker compose
      config` call printed all four API keys/tokens in plaintext) — all
      four were rotated. Full `evals/golden_queries.json` harness stays
      Phase 17's own separate, not-yet-built deliverable, deliberately
      not built early as scope creep.
- [ ] Phase 16 (reranking) and Phase 17 (evals) remain — both reserved,
      not gaps; build when asked for
- [x] Discovery D1-D5 (`CLAUDE.md`'s "Extension — Discovery", 2026-09-13):
      general news ingestion, the Actor (`gpt-4o-mini`/Haiku, an
      experienced-trader persona), the Critic (citation integrity, symbol
      resolution, and — added live, a real gap found in testing — a
      second LLM call verifying a resolved ticker is the *right* company,
      not just *a* real one), the Boss (retry with feedback, accepted
      suggestions now survive a retry after a real bug showed they
      didn't), persistence, and a daily `refresh_worker` job that runs
      regardless of whether any symbol is monitored yet. 218 tests
      passing. Live-verified with real news and real LLM calls: a correct
      suggestion accepted, wrong-ticker attempts (including one that
      surfaced organically through `refresh_worker` itself, not staged)
      rejected, a run that correctly abstained entirely, and
      `refresh_worker.run_once()` confirmed to dispatch discovery with
      zero monitored symbols while correctly respecting its own 24-hour
      cadence on a second, immediate call. D6 (`/feeds` page) remains.
