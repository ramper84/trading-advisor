# CLAUDE.md

Guidance for Claude Code when working in this repository. **This file is
frozen once its remaining placeholders are filled** — implementation follows
it and it is not rewritten as the build proceeds. A decision that changes
becomes an ADR in `ARCHITECTURE.md`, not an edit here.

This is this project's **third** architecture. The first (Alpaca execution)
and second (TradingView-only, no vector RAG) are both retired in full — see
the ADRs under §2 and `ARCHITECTURE.md`'s Appendix for the fuller record.

## 1. Description

A personal market-analysis and monitoring tool with no execution path of any
kind, and no social/community feed of any kind — every source is either an
official/regulatory data provider or a professional newsroom. It reads from
multiple **configured** market-data sources — structured quotes/OHLCV
(covering US/global markets and the Bolsa Mexicana de Valores), official
economic data (Banxico, FRED), and professional news/filings — persists
what it reads, and can produce a plain-language analysis grounded in that
data on request, always persisted. A monitor list drives a trending view
and a consolidated dashboard. Which sources are active is a config-file
decision (`data_catalog.yaml`), not a code change.

## 2. Architecture decision

Run against `PLAYBOOK.md` §2's axes, updated for real unstructured content
now being in scope:

| Axis | Outcome | Why |
|---|---|---|
| 1 — CAG | **Not selected for v1** | No stable rulebook grounds the analysis (unchanged from the prior architecture). Reserved slot: a personal "how I like analysis framed" doc. |
| 2 — SQL-retrieval RAG | **Yes — eight tables (ADR-007 widens this from three)** | `market_observations` (quote ticks, now carrying the full `fast_info` set — OHLC-today, 52w hi/lo, SMA50/200, market cap, exchange/currency/quote-type, all from the *same* call already made), `instruments` (a reference table, not a time series — sector/industry from the slower `Ticker.info`, refreshed on monitor-add not on every poll), `daily_bars` (adjusted-close OHLCV history — the real chart backbone, `s10-05`'s schema-divergence rule again: a tick and a daily bar are different grains, not variations of one thing), `fundamentals` (valuation + reported financials merged into one snapshot table — `s10-05`'s *other* direction: P/E and revenue are both "a company's financial snapshot as of a date," not divergent enough to split), `analyst_ratings` (rating-change events), `economic_indicators` (official macro series from `banxico_sie`/`fred_economic_data`), and `analyses` (persisted on-demand analyses). All name their entities exactly (symbol-or-series-id, timestamp) — no embedding needed for any. |
| 3 — Vector RAG | **Yes — newly activated, plus hybrid** | `sec_edgar_filings`, `finnhub_news`, `yfinance_news`, `elfinanciero_news`, and `el_economista_news` are genuinely paraphrastic — "does this article explain today's move" has no exact `WHERE` clause. This reverses the prior architecture's deferral, which held only because no real text corpus existed yet. **Hybrid search (semantic + lexical, `articles/s10-03`) is adopted from Phase 10, not deferred**: this domain is unusually identifier-heavy (tickers, filing Item numbers, exact dollar figures) — precisely the case `s10-03` names as lexical search's clear win over pure embeddings. **Multi-index/routing (`s10-05`) resolved to one table, not several**: the five unstructured sources' metadata is close enough (symbol, published_at, a `source_name` discriminator) and `/analyze` always wants all of them together — `s10-05`'s own decision rule ("diverging schemas → separate tables; variations of one thing → a discriminator column") points at the single `document_chunks` table already planned. **Query expansion/decomposition (`s10-04`) is explicitly not applied**: `/analyze`'s query is one ticker, not a rambling multi-topic transcript — `s10-04`'s own guidance is that a short, single-topic query needs neither technique. |
| 4 — Agentic (Critic) | **No — a plain output guardrail, now a real confidence gate** | No execution to gate, so no Actor-Critic loop — but `articles/s11-03`/`s11-04` still apply as deterministic code: `analysis_guard.py` computes a `confidence` score and a `quality_status` (`grounded`/`degraded`/`insufficient`) from cheap checks run in order — citation integrity (every cited chunk id was actually retrieved, `s11-03`), numeric grounding (cited price/indicator figures fall within the retrieved range — interpolation allowed, extrapolation flagged, `s11-04`'s `numeric_grounding`), and the reliability-tier rule (a `BULLISH`/`BEARISH` stance needs ≥1 citation with `reliability_tier>=3`). **Since ADR-006 dropped `reddit_mentions`, every remaining source now scores `reliability>=4` and clears `s06-02`'s own `is_rag_ready` bar on its own** — the rule currently has nothing to gate against; it's kept as defense-in-depth for any future lower-quality source, not because a current one needs it. `insufficient` **forces `stance=NEUTRAL`** as an enforced invariant, not a convention (`s11-04`'s abstention discipline) — this is the "does it pass for this session" gate. A model-based semantic judge (`s11-04`'s second layer) is a reserved, config-gated addition (`SEMANTIC_JUDGE_ENABLED`, default off) — added only if the cheap checks prove insufficient, never as day-one scaffolding. |
| 5 — Orchestration | **No** | One generation call per `/analyze` request. Fanning in two retrieval types (SQL + vector) before that call is augmentation (s09-04), not orchestration — nothing routes at runtime. |
| Live pass-through | **Yes — and scheduled refresh, both, per source** | Structured sources: live-read (cached) for `/symbols/{symbol}/status`, scheduled refresh (1-5 min) for `market_observations`; `economic_indicators` is scheduled-refresh only (daily — Banxico/FRED release on their own schedule, never continuously). Unstructured sources: scheduled refresh only, at the cadence `data_catalog.yaml` declares per source (hourly for filings, 30 min for news) — there is no "live status" reading for a news article. **Temporal weighting differs by source family (`articles/s10-06`'s domain-transfer note, not its "recency always wins" default)**: the news sources genuinely decay (exponential half-life — sentiment ages fast) since they're the "value erodes" case; `sec_edgar_filings` is closer to the "validity flips on a date" case (a 10-Q supersedes the prior quarter's, it doesn't fade beside it) — retrieval prefers the most recent filing per form type rather than smooth-decaying older ones out. |

Composition strategy: no conductor. Independent capabilities sharing
plumbing (`services/market_data.py`, the ingest pipeline, Postgres+pgvector,
Redis) — trending, symbol status, analyze, monitor. `analyze` is the one
path where SQL and vector retrieval both feed a single augmentation step;
that's still Lean-tier composition (`PLAYBOOK.md` §3), not a conductor,
because nothing routes between the two retrieval types at runtime — both
always run.

### ADR — drop TradingView entirely; multiple configured sources; Axis 3 activates (2026-09-06)

The second architecture (TradingView-only, via `tradingview-mcp-jarp`'s CDP
connection) is retired. It required a human-driven, locally running
TradingView Desktop app and delivered structured data only — no genuine
unstructured content, hence Axis 3 stayed deferred.

Replaced with: `data_catalog.yaml`, five sources, each independently
toggleable —

- `yfinance_quotes`, `finnhub_quotes` — structured (Axis 2), unchanged
  shape from before, different vendors.
- `sec_edgar_filings`, `finnhub_news`, `reddit_mentions` — unstructured
  (Axis 3, newly built): loaders → format-specific parsers → normalizer →
  canonical `Document`, chunked, embedded, retrieved top-k + threshold —
  the full `articles/s06-02`–`s06-04` pipeline this project's prior version
  never needed.

Consequences:
- `services/tv_connector.py` is gone; replaced by `services/market_data.py`
  (structured) and the `ingest/` pipeline (unstructured).
- ADR-003 (host-native ingest worker, forced by TradingView Desktop's CDP
  requirement) is **superseded** — every source here is a plain HTTPS API,
  so `refresh_worker.py` goes back into `docker-compose.yml` as a normal
  service. See `ARCHITECTURE.md` ADR-004.
- pgvector goes from "installed, unused" to **activated**.
- `TRADINGVIEW_MCP_PATH`/`TV_DEBUG_PORT` env vars are removed; replaced by
  `FINNHUB_API_KEY`, `EDGAR_USER_AGENT` (§6).

### ADR — drop Reddit entirely; drop TradingView-as-source; add official economic data + Mexican news (2026-09-10)

Before Phase 9 began, the operator asked to redesign the source list
around what they actually use day-to-day, with one hard rule: **no
social/community feed of any kind, ever** — a strengthening from "Reddit
specifically" to a permanent category exclusion. Full research and the
resulting catalog entries are in `data_catalog.yaml`; see
`ARCHITECTURE.md`'s ADR-006 for the complete record. Summary:

- **Dropped**: `reddit_mentions` (gone, not merely excluded-with-a-reason —
  no social source is even a candidate going forward).
  `tradingview_community` was considered and excluded-with-a-reason: no
  public API (same CDP/desktop constraint ADR-004 already removed), and
  its unique value — community-shared chart analysis — is the same
  "grain of salt" category Reddit was dropped for. `google_finance` (no
  API since 2012) and `investing_com_calendar` (no free/official API,
  confirmed against their own support docs) are also excluded-with-reason.
- **Added**: `yfinance_news` (Yahoo's own news aggregation, matching the
  operator's actual habit), `banxico_sie` and `fred_economic_data`
  (official central-bank economic series, replacing the Investing.com
  economic-calendar idea with the real official sources for the same
  data), `elfinanciero_news` and `el_economista_news` (both confirmed-live
  Mexican financial news RSS feeds).
- **Kept**: `yfinance_quotes` (confirmed to cover BMV via `.MX` tickers —
  this is what actually solves the Mexican-market-coverage need, not
  TradingView), `finnhub_quotes`/`finnhub_news` (kept as vendor redundancy
  per the operator's explicit choice, even though not in their original
  day-to-day list), `sec_edgar_filings` (unchanged, still the strongest
  single source for US-listed companies).

### ADR — widen Axis 2 to a full market-data framework: instrument reference, OHLCV, fundamentals, technical indicators, analyst ratings (2026-09-10)

An operator-provided 8-category framework (instrument ID, price/volume,
valuation, fundamentals, technical indicators, macro context, sentiment,
portfolio tracking) was audited against what the parsers actually
persisted. Findings and the resulting scope: full record in
`ARCHITECTURE.md`'s ADR-007.

- **Real gap, fixed at the source**: `MarketObservationRecord` only
  captured a live tick (`price`/`bid`/`ask`/`volume`) — no OHLC, no 52-week
  range, no moving averages, despite `yfinance`'s own `fast_info` already
  returning `open`/`dayHigh`/`dayLow`/`yearHigh`/`yearLow`/
  `fiftyDayAverage`/`twoHundredDayAverage`/`marketCap`/`exchange`/
  `currency`/`quoteType` in the **same call** already being made. Widened
  `market_observations` to carry all of it — zero new API calls.
- **New reference table**: `instruments` (exchange, currency, asset type,
  sector, industry) — sector/industry need the slower `Ticker.info` call,
  fetched once when a symbol is added to `monitored_symbols`, not on every
  5-minute poll.
- **New history table**: `daily_bars` (adjusted-close OHLCV) — the actual
  chart backbone; a different grain from `market_observations`'s ticks,
  not a duplicate of it.
- **New snapshot table**: `fundamentals`, merging valuation metrics (P/E,
  P/B, EV/EBITDA, dividend yield, FCF yield) with reported financials
  (revenue, net income, EPS, margins, debt/equity, ROE) into one table —
  both are "a company's financial snapshot as of a date," not divergent
  enough to split per `s10-05`'s own rule.
- **New event table**: `analyst_ratings` (upgrade/downgrade + firm),
  sourced from `yfinance`'s `Ticker.upgrades_downgrades` — no new
  dependency or key.
- **Technical indicators, mostly free, rest computed on read, never
  persisted as a table**: SMA50/SMA200/52-week hi-lo are already columns
  on `market_observations` (see above). Only RSI and volatility need real
  computation — done in `analysis/technical_indicators.py` from
  `daily_bars` at query time (cheap over a bounded window), deterministic,
  no LLM import, matching `trending.py`'s own existing rule.
- **Macro context**: `FEDFUNDS`/`CPIAUCSL` (FRED) confirmed. Banxico's own
  series ids — `SF61745` (overnight target rate), `SF43718` (USD/MXN FIX,
  the authoritative daily reference, not the settlement-date variant),
  `SP30578` (INPC annual inflation %, not the raw index level — directly
  interpretable) — confirmed live against the real SIE API with a real
  token, 2026-09-11, and wired into `refresh_worker.py`'s `BANXICO_SERIES`.
  A FRED-side GDP series remains unidentified — reserved, not blocking.
- **Explicitly not built**: per-article sentiment tagging (would add an
  LLM call per ingested article — cost multiplier, deferred, reserved
  slot). Portfolio tracking (buy price/cost basis/P&L) stays fully out of
  scope per ADR-001 — this project never holds a position. A `thesis` text
  column on `monitored_symbols` (a personal one-line note on *why* a
  symbol is being watched) is added since it doesn't reopen that decision.

### ADR — switch frontend from Streamlit to Reflex (2026-09-11)

Before Phase 18 began, the operator asked to explore alternatives to
Streamlit for a more modern, configurable dashboard with real charting —
Streamlit's linear-script rerun model and limited layout control were the
stated concerns. Three alternatives were researched and compared (Plotly
Dash, Reflex, a full React+Tremor+FastAPI stack); full record in
`ARCHITECTURE.md`'s ADR-012. Summary:

- **Chosen: Reflex.** Pure Python, compiles to a real React frontend with
  an async FastAPI backend under the hood — a modern app feel (real
  routing/state, no full-page reruns) without taking on a second language
  for a single-user tool to maintain. Charting looked like the real cost
  versus Dash at comparison time (a Recharts wrapper, not Plotly-native)
  — confirmed stale once actually installed: `reflex==0.9.11` ships a
  first-party `reflex-components-plotly` package with a `PlotlyFinance`
  component, live-confirmed by building a real `go.Candlestick` figure.
  Genuine Plotly-native candlestick charting, not a trade-off after all.
- **Considered and not chosen**: Plotly Dash (more mature, better native
  financial charting, but more boilerplate and still no first-class
  drag/resize layout). A full React+Tremor+`react-grid-layout` stack (the
  most flexible, genuine drag/resize panels, but a second stack — real
  ongoing maintenance cost for one user — and it would require building
  `routers/*` now, which every phase since Phase 10 has deliberately
  deferred).
- **A real architecture simplification, not just a swap**: Reflex's own
  backend already is a FastAPI app, so its event handlers call `app/*`
  pipeline modules directly, in-process — no separate `api` service, no
  `routers/*` layer at all for Phase 18. `docker-compose.yml`'s `api`
  service is dropped; `frontend` replaces it.
- **Consequence**: `streamlit_app.py` and the `streamlit` dependency are
  gone; `frontend/` (a self-contained Reflex project) replaces them.
  `routers/*` stays unbuilt, reserved only for a future second HTTP
  consumer, if one ever appears.

## 3. Project tier and structure

**Lean**, still — one retrieval architecture that now has two retrieval
*types* (Axis 2 + Axis 3) feeding one generation call, not multiple
composed architectures needing a conductor.

```
trading-advisor/
├── data_catalog.yaml               # the 9 configured sources + 3 excluded-with-reason (articles/s06-02, ADR-006)
├── app/
│   ├── config.py
│   ├── schemas.py
│   ├── main.py
│   ├── services/
│   │   ├── run_recorder.py         # per-stage observability (Phase 1, built) — importable broadly, no business logic
│   │   ├── market_data.py          # yfinance + finnhub structured connectors; live-read + freshness cache
│   │   └── llm_service.py          # generation call AND embedding calls (Instructor + LiteLLM)
│   ├── guardrails/
│   │   └── analysis_guard.py       # citation integrity (s11-03) -> numeric grounding (s11-04) -> reliability-tier rule -> confidence + quality_status ("grounded"/"degraded"/"insufficient")
│   ├── ingest/                      # OFFLINE pipeline (articles/s06-01's split)
│   │   ├── catalog.py               # data_catalog.yaml loader (Pydantic, articles/s06-02)
│   │   ├── loaders/
│   │   │   └── http.py              # generic HTTP fetch, shared by all sources
│   │   ├── parsers/
│   │   │   ├── quotes_parser.py     # yfinance/finnhub JSON -> intermediate records (now full fast_info: OHLC/52w/SMA50+200/mktcap — ADR-007)
│   │   │   ├── instrument_parser.py # yfinance Ticker.info (once per symbol, on monitor-add) -> instrument reference record (ADR-007)
│   │   │   ├── daily_bar_parser.py  # yfinance Ticker.history() -> adjusted-close daily OHLCV bar (ADR-007)
│   │   │   ├── fundamentals_parser.py  # yfinance Ticker.info + quarterly_financials -> valuation + fundamentals snapshot (ADR-007)
│   │   │   ├── analyst_ratings_parser.py  # yfinance Ticker.upgrades_downgrades -> rating-change records (ADR-007)
│   │   │   ├── edgar_parser.py      # SEC filing HTML -> section-split text
│   │   │   ├── news_parser.py       # Finnhub + yfinance news JSON -> shared RawArticle records
│   │   │   ├── rss_parser.py        # elfinanciero_news + el_economista_news RSS -> RawArticle, keyword-filtered (ADR-006)
│   │   │   └── economic_data_parser.py  # banxico_sie + fred_economic_data JSON -> RawEconomicObservation (ADR-006)
│   │   ├── normalizers/
│   │   │   └── canonical.py         # -> Document(content, metadata), articles/s06-03's contract — news/filing sources only, everything else in this list feeds SQL directly
│   │   ├── chunking.py              # structural-by-Item for filings (built, Phase 3-4), one-chunk-per-item for news
│   │   ├── embedding.py             # text-embedding-3-small, writes document_chunks with embedding_version + source_hash (s11-05)
│   │   ├── refresh_worker.py        # scheduled loop, per-source cadence from data_catalog.yaml
│   │   ├── observation_store.py     # Axis 2 write side, market_observations (now with OHLC/52w/SMA/mktcap columns)
│   │   ├── instrument_store.py      # Axis 2 write side, instruments — upsert-on-change, not append-only (ADR-007)
│   │   ├── daily_bar_store.py       # Axis 2 write side, daily_bars (ADR-007)
│   │   ├── fundamentals_store.py    # Axis 2 write side, fundamentals (ADR-007)
│   │   ├── analyst_rating_store.py  # Axis 2 write side, analyst_ratings (ADR-007)
│   │   └── economic_indicator_store.py  # Axis 2 write side, economic_indicators (Phase 9, ADR-006)
│   ├── retrieval/                   # ONLINE pipeline
│   │   ├── sql_retriever.py         # Axis 2 typed reads: observations, daily_bars, fundamentals, analyst_ratings, economic_indicators, analyses, monitored_symbols
│   │   ├── vector_retriever.py      # Axis 3: hard filter (symbol) -> semantic + lexical search -> RRF fusion -> temporal soft-weight -> threshold/soft-fail
│   │   ├── hybrid_search.py         # tsvector/GIN lexical branch + RRF fusion with the semantic branch (s10-03)
│   │   └── temporal.py              # per-source-family decay/recency weighting (s10-06), applied last, over the survivors only
│   ├── analysis/
│   │   ├── trending.py              # deterministic ranking — NO LLM import
│   │   ├── technical_indicators.py  # RSI + volatility computed on read from daily_bars — NO LLM import (ADR-007; SMA50/200 and 52w hi/lo are already persisted columns, not computed here)
│   │   └── analysis_store.py        # Axis 2: analyses + monitored_symbols read/write
│   ├── prompts/
│   │   └── analyze/v1/{system,user}.j2
│   └── routers/                     # NOT built (ADR-012) — Reflex's own backend is the app
│                                    #   server; its event handlers call app/* directly,
│                                    #   in-process. Reserved only for a future second HTTP
│                                    #   consumer, if one ever appears.
├── migrations/                      # Alembic; market_observations, instruments, daily_bars, fundamentals,
│                                    #   analyst_ratings, economic_indicators, analyses, monitored_symbols, document_chunks
├── evals/
│   ├── golden_queries.json          # seeded from README.md §2a; must include an abstention case AND a contradiction case (s11-06)
│   └── measure_retrieval.py         # artisanal precision@k harness (s10-02) — decides IF/WHEN reranking (Phase 16) earns its place
├── tests/
├── frontend/                        # Reflex app (ADR-012) — event handlers call app/* pipeline
│   │                                #   modules directly, in-process; no separate API hop
│   ├── rxconfig.py
│   └── frontend/
│       ├── frontend.py              # rx.App, page registration
│       ├── state.py                 # rx.State subclasses — one per page, plumbing only
│       └── pages/                   # trending, symbol detail, analyze form, dashboard
├── docker-compose.yml               # postgres(+pgvector), redis, frontend, refresh_worker — all containerized now
├── Dockerfile
├── .env.example
├── ARCHITECTURE.md
└── pyproject.toml
```

`refresh_worker.py` is a normal docker-compose service again (see the ADR
above) — no host-native deployment wrinkle this time.

## 4. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language / API | Python 3.12, FastAPI + uvicorn | `PLAYBOOK.md` §4 default |
| Validation | Pydantic v2 | `PLAYBOOK.md` §4 default |
| Store | PostgreSQL 16 (`pgvector/pgvector:pg16`) | Axis 2's three tables + Axis 3's `document_chunks` — pgvector is now **activated**, not installed-unused |
| Cache | Redis | freshness-budget cache for live quote reads |
| Structured market data | `yfinance` (primary, covers BMV via `.MX`), `finnhub` (fallback) | Axis 2; both free/free-tier, no brokerage account. `yfinance` alone backs quotes, instrument reference, daily bars, fundamentals, and analyst ratings (ADR-007) — no new dependency per data category |
| Economic data | Banxico SIE (Mexico), FRED (US) | Axis 2; both free, official, token/key registration required — ADR-006, replacing the Investing.com economic-calendar idea |
| Unstructured market data | SEC EDGAR full-text search, Finnhub `/company-news`, Yahoo Finance news (`yfinance`), El Financiero + El Economista RSS (`feedparser`) | Axis 3; see `data_catalog.yaml` for cadence/quality per source. No social/community source of any kind (ADR-006) |
| Embedding model | `text-embedding-3-small` | `PLAYBOOK.md` §4/Axis 3 default; upgrade only against a measured recall gap |
| Chunking | Structural (by filing Item) for `sec_edgar_filings`; one chunk per item for the news sources (already short-form) | `articles/s07-03`/`s07-04`'s per-document-type rule — recursive chunking is overkill for a 2-paragraph news summary |
| Vector index | **None in v1** — sequential scan | Axis 3 default; add `hnsw` only against a measured latency number |
| LLM access | LiteLLM + Instructor, `gpt-4o-mini` primary / a Claude Haiku fallback | `PLAYBOOK.md` §4 default |
| Prompts | Jinja2, versioned (`prompts/analyze/v1/`) | standard convention |
| Structured output | Instructor | `stance` (`BULLISH`/`BEARISH`/`NEUTRAL`) + confidence + rationale + per-claim citations, validated schema |
| Frontend | **Reflex** (ADR-012, supersedes Streamlit) | trending list, symbol detail, analyze form, dashboard — pure Python, compiles to a real React frontend + async FastAPI backend; event handlers call `app/*` pipeline modules directly, no separate API service |
| Local deployment | `docker compose`: postgres, redis, frontend, **refresh_worker** | All nine sources are plain HTTPS APIs — no host-native deployment constraint this time (contrast the retired TradingView-only architecture); no separate `api` service — Reflex's own backend serves that role (ADR-012) |

## 5. Common commands

```bash
docker compose up --build      # postgres(+pgvector) + redis + frontend (Reflex) + refresh_worker
pytest                         # unit tests — no LLM, embedding, or network calls
reflex run                     # from frontend/, if run outside compose
```

## 6. Configuration

```bash
# Structured sources
FINNHUB_API_KEY=                          # backs finnhub_quotes AND finnhub_news

# Unstructured sources
EDGAR_USER_AGENT="your-name your-email@example.com"   # SEC's fair-access policy requires this

# Economic data (Axis 2, economic_indicators table — ADR-006)
BANXICO_SIE_TOKEN=                        # free token: https://www.banxico.org.mx/SieAPIRest/service/v1/token
FRED_API_KEY=                             # free key: https://fredaccount.stlouisfed.org

# LLM + embeddings
OPENAI_API_KEY=                           # gpt-4o-mini generation AND text-embedding-3-small
ANTHROPIC_API_KEY=                        # fallback LLM only, no embeddings

# Store
DATABASE_URL=postgresql+psycopg://trading-advisor:trading-advisor@postgres:5432/trading-advisor
REDIS_URL=redis://redis:6379

# Freshness (structured, live-read path only — unstructured cadence lives in data_catalog.yaml)
FRESHNESS_BUDGET_SECONDS=30

# Vector retrieval (Axis 3)
VECTOR_TOP_K=8
VECTOR_DISTANCE_THRESHOLD=0.35
HYBRID_SEARCH_ENABLED=true          # semantic + lexical, RRF-fused (s10-03) — a switchable boolean per s10-01's "measurable experiment" discipline
RERANK_ENABLED=false                # reserved (s10-01) — flip on only once evals/measure_retrieval.py shows a ranking gap
TEMPORAL_HALF_LIFE_DAYS_NEWS=14     # all five news sources' decay (s10-06) — sentiment ages fast

# Quality gate (s11-03/s11-04) — the "did this pass for this session" check
SEMANTIC_JUDGE_ENABLED=false        # reserved: a second, cheaper model verifying claims against sources — add only if numeric grounding + citation integrity prove insufficient
```

## 7. Build strategy

Rebuilt against `PLAYBOOK.md` §8, now turning on the chunking/embedding
phases the prior architecture skipped:

1. **Phase 1** — repo scaffold: the tree in §3, `.env.example`,
   `.gitignore`, `Dockerfile`, `docker-compose.yml` (now including
   `refresh_worker`), `/health`, a per-stage run recorder.
2. **Phase 2** — source audit: `data_catalog.yaml` (already written — this
   *is* the Phase 2 deliverable, done ahead of Phase 1 because the sources
   were decided in conversation first); finalize README §2a's queries into
   `evals/golden_queries.json`, including at least one query only Axis 3
   can answer (e.g. "why did NVDA move today").
3. **Phase 3-4 — done, extended 2026-09-10 for the redesigned source list
   (ADR-006).** One parser per source format: `quotes_parser.py`,
   `edgar_parser.py`, `news_parser.py` (now shared by `finnhub_news` and
   `yfinance_news`, converging on one `RawArticle` shape),
   `rss_parser.py` (new — `elfinanciero_news`/`el_economista_news`, keyword-
   filtered since RSS has no per-symbol query, verified live against both
   real feeds the same day), `economic_data_parser.py` (new —
   `banxico_sie`/`fred_economic_data`, each source's own disguised-null
   marker handled explicitly: Banxico's `"N/E"`, FRED's `"."`). All
   news/filing parsers converge on canonical `Document` via
   `normalizers/canonical.py` (`articles/s06-03`); `economic_data_parser.py`
   feeds SQL directly (Axis 2), never `Document`/embedding — there's
   nothing paraphrastic in a rate value. `edgar_parser.py`'s structural
   section-split (by filing Item) is also this source's Phase 7 chunking
   boundary. `reddit_parser.py` is deleted, not archived — ADR-006 dropped
   the source entirely. 31 tests, all passing, no network calls — parsers
   operate on already-fetched payloads (the `yfinance_news`/RSS fixtures
   were captured from real live calls, not invented); the `fetch_*`
   functions calling the real APIs are untested until real credentials
   exist for Finnhub/Banxico/FRED (`yfinance` and the two RSS feeds need
   no credentials and were verified live during this redesign).
4. **Phase 5 — PII: skipped, with a stated reason.** All nine sources are
   public market/company data about tickers or official economic series,
   not personal data about identifiable individuals in the GDPR sense.
   Revisit if a future source ever carries real personal data (e.g. a
   source containing named private individuals).
5. **Phase 6 — CAG: skipped**, unchanged from the prior architecture, no
   rulebook exists.
6. **Phase 7 — Chunking — done in Phase 3-4.** Structural (by filing Item,
   `edgar_parser.split_into_sections`) for `sec_edgar_filings`;
   single-chunk-per-record for all five news sources (already short-form,
   recursive chunking adds nothing — `articles/s07-03`).
7. **Phase 8 — done.** `document_chunks` migration
   (`migrations/versions/802e79b7320a_create_document_chunks.py`): typed
   columns for symbol/source_name/reliability_tier + JSONB for the rest
   (`articles/s08-04`'s schema split), `embedding_version` and
   `source_hash` from day one (`articles/s11-05`'s explicit warning — cheap
   now, a painful retrofit once a real model change happens), and the
   `content_tsv` generated column + GIN index for Phase 10's hybrid search
   built into the same migration rather than a second one later. No vector
   index yet. `services/db.py` (new — a shared `get_connection()` that
   registers the pgvector adapter once, used by every module touching
   `document_chunks`) and `ingest/embedding.py`
   (`text-embedding-3-small`, one batched call per source-fetch,
   `upsert_chunks()` in one atomic transaction, idempotent on
   `(source_name, document_id)`, skips a rewrite when `source_hash` hasn't
   changed). 24 tests passing (5 new, all mocking the OpenAI call and the
   DB connection — no real network calls). Verified live: migration
   applied against a real `pgvector/pgvector:pg16` container, a chunk
   round-tripped through insert → lexical (`tsvector`) match → vector
   cosine distance, then cleaned up.
8. **Phase 9 — done.** Seven migrations (`market_observations` with the
   full `fast_info` field set, `instruments`, `daily_bars`, `fundamentals`,
   `analyst_ratings`, `economic_indicators`, `monitored_symbols` with its
   `thesis` column), plus `yfinance_daily_bars`/`yfinance_fundamentals`/
   `yfinance_analyst_ratings` added to `data_catalog.yaml` as their own
   sources (each with its own daily cadence, distinct from quotes' 1-5 min
   — cadence belongs in the catalog, not hardcoded in the worker). Five new
   parsers (`instrument_parser.py`, `daily_bar_parser.py`,
   `fundamentals_parser.py`, `analyst_ratings_parser.py`, all
   `yfinance`-only) and their `*_store.py` write sides. `refresh_worker.py`
   dispatches per `source.name` to the right parser, treating
   `banxico_sie`/`fred_economic_data` as economy-wide (one fetch, not one
   per symbol) and `instruments` as populate-once-on-monitor-add rather
   than catalog-cadenced. 74 tests passing.

   **Verified live** against a real `pgvector/pgvector:pg16` instance with
   AAPL seeded as a monitored symbol, and four real bugs were caught and
   fixed in the process — this is exactly what live verification is for:
   - `.env`'s blank values with an unquoted trailing `# comment` were
     parsed as the comment text itself by `python-dotenv` (no delimiter
     between an empty value and `#`) — `FRED_API_KEY` silently became the
     literal string `"# free key: https://..."`. Fixed by moving every
     such comment to its own line above the variable, in both `.env` and
     `.env.example`.
   - `embed_texts()` crashed on a real 10-K: `sec_edgar_filings`' own
     structural-by-Item sections summed past OpenAI's 300k-tokens-per-
     request limit, and a single large Item can exceed the 8191-token
     per-input limit on its own. `embedding.py` now truncates any
     oversize input and batches by a token budget — real recursive
     sub-chunking of an oversized Item remains Phase 7's own named,
     still-open follow-up, not fully closed by this stopgap.
   - `yfinance`'s `FastInfo.get()` silently returns `None` for several real
     keys (`day_high`, `year_high`, `market_cap`, `quote_type` reproduced)
     that bracket access (`fast["day_high"]`) returns correctly — a library
     quirk, not a missing-field case. `market_data.py` now has
     `_fast_info_float`/`_fast_info_str` helpers that never call `.get()`;
     a fake `FastInfo` reproducing the exact quirk guards against
     regression in `test_market_data.py`.
   - `refresh_quotes` always called the generic `get_quote()` (yfinance
     first, Finnhub only as fallback), so the `finnhub_quotes` catalog
     source never actually polled Finnhub on a healthy day — silently
     redundant with `yfinance_quotes`, and a latent `reliability_tier`/
     `source_name` mismatch if the two catalog scores ever diverged. Fixed
     to route each catalog source to its own vendor call; `get_quote()`'s
     fallback behavior is reserved for Phase 10's live-read path, which
     genuinely wants "any working quote," not a scheduled per-vendor poll.

   Live run produced: 1 real quote (full field set confirmed), 1
   instrument reference row, 4 daily bars, 1 fundamentals snapshot, 977
   real analyst ratings, and 1018 real `document_chunks` from 25 actual
   AAPL SEC filings — embedded, batched, no crash. Finnhub/FRED/Banxico
   correctly failed or skipped (no credentials yet) without aborting the
   run.

   **Second live pass (2026-09-11), real `FINNHUB_API_KEY`/
   `BANXICO_SIE_TOKEN`/`FRED_API_KEY` now set, two monitored symbols
   (`AAPL`, `WALMEX.MX` — the BMV coverage claim, exercised for real, not
   just asserted).** Banxico's own series ids were confirmed live against
   the real SIE API before being wired in — `SF61745` (overnight target
   rate), `SF43718` (USD/MXN FIX, the authoritative daily reference, not
   the settlement-date variant), `SP30578` (INPC annual inflation %, not
   the raw index level). One more real bug found and fixed: **FRED returns
   a series' entire history with no bound** — an unbounded first call
   pulled 1823 rows, `CPIAUCSL` back to 1954. `fetch_fred_series()` now
   takes an `observation_start` and `refresh_worker.py` passes a 2-year
   lookback (`FRED_LOOKBACK_DAYS`); the same live series then landed 49
   rows. Two more things surfaced that are vendor behavior, not bugs:
   Yahoo Finance has no fundamentals data for `WALMEX.MX` (404, handled by
   the existing try/except, not a crash) — an external data gap on a
   Mexican filer, not something to fix here; and Finnhub's free tier
   returns 403 for non-US-exchange symbols entirely (confirmed by calling
   Finnhub directly for `WALMEX.MX` outside the worker) — expected, and
   exactly why `yfinance` is this project's primary source for BMV
   coverage, with Finnhub redundancy scoped to US tickers only. 76 tests
   passing.
9. **Phase 10 — Retrieval**: `sql_retriever.py` (Axis 2, typed) and
   `vector_retriever.py` (Axis 3), assembled in `s10-06`'s stated order —
   *cheap and excluding first, expensive and fine last, soft at the close*:
   (a) hard filter by `symbol` in the SQL `WHERE`, before any vector math;
   (b) semantic search (pgvector) and lexical search (`tsvector`/GIN,
   `hybrid_search.py`) run in parallel, fused by Reciprocal Rank Fusion
   (`s10-03`) — positions only, never raw scores, since cosine distance and
   `ts_rank` are not comparable numbers; (c) `temporal.py`'s per-source-family
   weighting (§2's ADR) applied last, over the fused survivors only; (d) a
   distance-threshold soft-fail (`VECTOR_DISTANCE_THRESHOLD`) returns
   `low_confidence` rather than forcing an answer (`s09-03`). Query
   expansion/decomposition and reranking are **not** built here — see §2's
   ADR and Phase 16 respectively.

   **Done (2026-09-10).** `sql_retriever.py` (typed reads across
   `instruments`, `market_observations`, `daily_bars`, `fundamentals`,
   `analyst_ratings`, `economic_indicators`, `monitored_symbols`, plus an
   `analyses` reader that only resolves once Phase 12 creates that table),
   `hybrid_search.py` (`content_tsv`/GIN lexical branch + `s10-03`'s RRF,
   fused by rank position only), `temporal.py` (news half-life decay via
   `TEMPORAL_HALF_LIFE_DAYS_NEWS`; `sec_edgar_filings` gets the
   "validity-flips" treatment instead — the most recent filing per
   `(symbol, form_type)` keeps full weight, older filings of the same form
   type are fixed-discounted, not smooth-decayed), `vector_retriever.py`
   (the full (a)-(d) orchestration above). 25 new tests, all mocking the DB
   connection/embedding call — no network calls; 106 passing total.

   **Live verification (2026-09-10)**, temporary dev Postgres on port 5433
   (never touching `fantasy-postgres-1` on 5432, confirmed healthy
   throughout and after teardown): real SEC filings + Finnhub/Yahoo news
   embedded for `AAPL` (1265 `document_chunks`), real quotes/daily
   bars/fundamentals/analyst ratings/economic indicators (US + MX) ingested,
   then `retrieve()` run against real embeddings with two real queries — a
   paraphrased one correctly soft-failed (`low_confidence=True`, distance
   0.399 > 0.35) and a near-verbatim one correctly cleared the threshold
   (`low_confidence=False`, distance 0.306, Risk Factors chunks ranked top),
   confirming `s09-03`'s soft-fail gate actually discriminates rather than
   always tripping or never tripping. `sql_retriever.py` verified against
   real rows for every table it reads.

   Three real bugs found and fixed, live only — none caught by unit tests
   against mocked shapes:
   - **`refresh_filings` never bounded its SEC EDGAR pull**: called
     `fetch_recent_filings()` with no `since`, so every scheduled poll
     re-fetched a large filer's *entire* tracked-form history — 140+
     individual document HTTP requests for `AAPL` alone, forever, even
     though `document_chunks`' `source_hash` already made the resulting
     writes no-ops. The waste was at the fetch layer, `source_hash` only
     ever protected the write layer. Fixed with `_latest_filing_date()` (a
     `MAX(published_at)` read per symbol) passed as `since`; re-verified
     live — the second `refresh_filings` call made 2 lightweight metadata
     requests instead of 140+ document fetches, with the chunk count
     unchanged.
   - **That fix then hit a naive/aware `datetime` comparison**: SEC's
     `filingDate` is a plain date string (`fetch_recent_filings` parses it
     naive), but `since` comes back timezone-aware from a `timestamptz`
     column — direct comparison raised `TypeError`. Fixed by comparing
     `.date()` on both sides, the only granularity `filingDate` actually
     carries.
   - **`semantic_search`'s cosine-distance parameter had no target type**:
     unlike `embed_and_store`'s `INSERT` into a `Vector`-typed column (which
     lets `pgvector`'s adapter infer the type), a bare query parameter
     compared via `<=>` has no column context — passing a plain Python list
     raised `operator does not exist: vector <=> double precision[]`. Fixed
     with an explicit `%s::vector` cast on both the `SELECT`'s distance
     expression and its `ORDER BY`.

   A fourth, non-retrieval finding surfaced incidentally during this pass
   and was fixed on the spot since it's a live credential-safety issue:
   **`refresh_worker.py`'s `logging.basicConfig(level=logging.INFO)`
   let `httpx`'s own request logger propagate to root at INFO**, and
   `fetch_fred_series()` sends `FRED_API_KEY` as a query parameter (FRED
   has no header-auth option) — so every scheduled poll would log the key
   in plaintext to container logs, forever. A real key was seen in a raw
   log line during this verification. Fixed with
   `logging.getLogger("httpx").setLevel(logging.WARNING)` in
   `refresh_worker.py`; re-verified live — no URL/key appears in output
   after the fix. **The user was advised to rotate the exposed
   `FRED_API_KEY` as a precaution**, independent of the code fix.
10. **Phase 11 — Augmentation**: `POST /analyze` assembles both retrieval
    types into one structured, XML-delimited context (`articles/s09-04`).
    The Axis-2 side (§7's ADR-007) now includes the instrument's reference
    row, latest `daily_bars`/valuation-and-fundamentals snapshot,
    RSI/volatility from `technical_indicators.py`, recent analyst rating
    changes, and country-matched `economic_indicators` — this is what
    turns "the price moved" into a groundable claim ("...against a
    52-week low and a Banxico hold"). On top of that, `s11-01`'s
    distillation discipline applies to the Axis-3 side: extractive
    compression for `sec_edgar_filings` chunks (keep lines mentioning the
    symbol/figures being asked about — cheap, cannot invent; the five news
    sources' chunks are already short enough to skip compression),
    **edge-loading the strongest evidence at the start and end of the
    context** using the corrected `front + reversed(back)` construction
    (`s09-04`'s `reorder_u_pattern` — `s11-01`'s own naive `insert(0,
    item)` version is a documented bug that inverts the intent, don't
    reproduce it), and logging every chunk a token-budget cutoff drops,
    not silently truncating.

    **Done (2026-09-10).** `app/analysis/augmentation.py`: a pure function
    (`assemble_context`), no DB/network access of its own — the caller
    passes already-fetched `sql_retriever` rows and a `RetrievalResult`.
    `build_market_data_block` renders the deterministic Axis-2 side as one
    `<market_data>` XML block (never compressed or budget-trimmed — it's
    already terse). The Axis-3 side follows `s11-01`'s exact pipeline
    order — `compress_chunks` (filing-family only) → `reorder_u_pattern`
    (edge-load, unconditional, matching `s11-01`'s revision of `s09-04`'s
    off-by-default gate) → `fit_to_budget`. `fit_to_budget` deliberately
    uses `s11-01`'s **continue**-on-miss loop, not `s09-04`'s original
    **break**-on-first-miss one: after edge-loading, relevance is no
    longer monotonic by position, so a `break` would wrongly drop a small,
    still-fitting chunk that happens to sit right after a huge one.
    `ANALYSIS_CONTEXT_TOKEN_BUDGET` (`config.py`, default 12,000) is a
    deliberately conservative default, not `s09-04`'s theoretical
    15%-output/5%-overhead ceiling (~102k on a 128k window) — this
    project's actual retrieval breadth (`VECTOR_TOP_K=8` per branch) never
    approaches that. **No router built yet**: `POST /analyze` isn't a
    coherent endpoint until Phase 12 (generation) and Phase 13 (the
    confidence gate) exist behind it — returning bare assembled context
    would be a half-built feature, not this phase's deliverable. 13 new
    tests (compression, `reorder_u_pattern`'s exact shape incl. the 6-item
    case, the continue-vs-break `fit_to_budget` distinction, market-data
    XML rendering with fields present/absent, full `assemble_context`
    integration); 119 passing total.

    **Live verification (2026-09-10)**, same temporary-dev-Postgres
    discipline as Phases 9-10 (`fantasy-postgres-1` confirmed healthy
    throughout and after teardown): real `sql_retriever` rows +
    `vector_retriever.retrieve()` output for `AAPL` assembled into one
    real context block — instrument, latest quote, fundamentals, 5 real
    analyst ratings, FRED indicators, and real SEC-filing/news `<source>`
    blocks, 4,542 tokens total, nothing dropped at the default 12,000
    budget. Re-run with a deliberately tight 800-token budget against the
    same real retrieved set: 6 of 8 real chunks correctly dropped, 2 kept,
    `augmentation_dropped_chunks` logged rather than silently truncating —
    confirming the budget cutoff actually discriminates on real data, not
    just a synthetic unit-test fixture. No new bugs found this pass — the
    only surprise was expected, not a defect: `<technical_indicators>`
    correctly omitted `rsi_14` (needs ≥15 daily bars; `refresh_daily_bars`
    only pulls a 5-day window) while still reporting `volatility` and
    `window_days`, exactly the "insufficient data stays absent, never
    invented" behavior `technical_indicators.py` was built to have.
11. **Phase 12 — Generation**: `s11-02`'s two-stage synthesis, not one
    black-box call — a deterministic aggregate computed in code first
    (a weighted signal per citation from **reliability_tier, temporal
    weight, and fusion rank**, three signals not seven, `s11-02`'s own
    "one sentence to justify each coefficient" discipline; a
    weighted-median anchor; a `contested` flag when *strong* sources
    disagree, not any two sources — a lone low-reliability outlier must
    never read as a contradiction), then one Instructor-validated generation call that
    reasons over that precomputed signal rather than inventing it, producing
    `stance`/confidence/rationale/citations with `chunk_id`s from the actual
    retrieved set (`s11-03`).

    **Done (2026-09-10).** `app/analysis/synthesis.py`: the deterministic
    stage. `s11-02`'s reference domain has a natural per-source number to
    synthesize (budget hours, written in the source text); this project's
    citations don't, and ADR-007 already ruled out adding one via a
    per-article LLM call. `_keyword_lean` fills that gap the way `s11-02`
    fills its own — a cheap, deterministic bullish/bearish lexicon lookup
    in [-1, 1], not a model call, so it doesn't reopen ADR-007's decision.
    Its accuracy is a named, expected limitation (see below), not assumed.
    `combined_weight` uses exactly the three named signals — `fusion_rank`
    (0.40), `temporal_weight` (0.35), `reliability_tier` (0.25, weighted
    least since every currently-included source already clears ADR-006's
    quality floor). `fusion_rank` required a small Phase 10 contract
    extension: `RetrievalResult` now also carries `fused_rank`, captured
    **before** temporal re-sorting — using the final post-temporal order
    would have double-counted temporal effects into what's supposed to be
    an independent signal. `aggregate_evidence` implements the *corrected*
    version of `s11-02`'s own contradiction logic (the handbook's own
    editor's note flags the bug in the original): `strong_low`/
    `strong_high`/`contested` are computed over STRONG citations
    (`weight >= 0.4`) only, never the full set. `contested` itself uses an
    absolute sign-disagreement threshold (`CONTESTED_LEAN_THRESHOLD=0.3`
    on each side of zero), not `s11-02`'s relative-spread formula — leans
    are zero-centered and bounded `[-1, 1]`, unlike always-positive hours,
    so a relative spread degenerates near an anchor close to zero, which
    is the common case here.

    `app/services/llm_service.py`: the judgment stage. `instructor.from_litellm(litellm.completion)`,
    `gpt-4o-mini` primary, `claude-haiku-4-5-20251001` fallback on any
    exception from the primary call — not tried speculatively. Real
    Jinja2 templates now fill `prompts/analyze/v1/{system,user}.j2`
    (previously placeholder stubs): the system prompt instructs
    BULLISH/BEARISH/NEUTRAL only (never BUY/SELL/HOLD, ADR-002), citing
    only provided `chunk_id`s, explaining rather than flattening a
    `contested` signal, and preferring NEUTRAL over a confident guess on
    thin evidence. `AnalysisSynthesis`/`Citation` (in `app/schemas.py`)
    are the Instructor response models — `stance`/`confidence`/
    `rationale`/`citations`, exactly CLAUDE.md §4's stated shape; the
    model's own `confidence` is explicitly documented as distinct from
    Phase 13's code-derived one, never conflated. 18 new tests (all
    mocking the LLM client — no real network calls in the unit suite);
    137 passing total.

    **No router or persistence built yet**: `POST /analyze` and the
    `analyses` table both wait for Phase 13's confidence gate, which is
    what actually computes the `quality_status` a persisted row needs —
    persisting a row with an undefined quality status would be a
    half-built feature, not this phase's deliverable.

    **Live verification (2026-09-10)**, same temporary-dev-Postgres
    discipline as Phases 9-11 (`fantasy-postgres-1` confirmed healthy
    throughout and after teardown), plus this phase's first **real**
    generation calls: the full Phase 10-12 pipeline run end to end against
    real `AAPL` data — retrieval, augmentation, the deterministic
    aggregate, then a genuine `gpt-4o-mini` call. Output: `stance=NEUTRAL`,
    a rationale correctly explaining the `contested=True` evidence
    (conflicting SEC filing risk-factor language) rather than averaging
    past it, citing two real `chunk_id`s independently confirmed present
    in the actual retrieved set — no hallucinated citation, though nothing
    code-enforces that yet (Phase 13's job). The fallback path was also
    live-verified for real, twice: once as a raw `litellm.completion` call
    confirming the model string itself resolves (a real risk — `litellm`'s
    model registry could plausibly lag a model's release), and once
    through the full `generate_synthesis()` integration with a
    deliberately invalid primary key (never a real one), confirming
    Instructor's retry/fallback machinery — not just bare `litellm` — also
    completes successfully end to end.

    One real, expected limitation surfaced and is recorded rather than
    silently patched: `_keyword_lean` saturated at exactly ±1.0 for every
    citation in the real run, with none landing near zero — SEC filing
    "Risk Factors" section headers are keyword-dense in one direction
    (mostly the word "risk" itself) regardless of whether they disclose
    anything new, so `contested=True` fires often whenever both a
    filing chunk and a bullish news chunk are retrieved together. This is
    exactly `_keyword_lean`'s own documented, named trade-off (a
    word-matching heuristic, not measured accuracy) — not a bug to fix
    now; `evals/measure_retrieval.py` (Phase 17) is the tool that decides
    whether this actually costs real answer quality, per `s11-02`'s own
    "measure it before assuming" discipline.
12. **Phase 13 — Guardrails, the confidence gate**: `analysis_guard.py`
    runs cheap-to-expensive, per `s11-04`'s verification funnel —
    (1) **citation integrity**, checked in code, never trusted to the
    model: every cited `chunk_id` must have been in the retrieved set, or
    it's dangling (`s11-03`); (2) **numeric grounding**: cited price/
    indicator figures must fall within the range of what was actually
    retrieved — interpolation allowed, extrapolation flagged (`s11-04`'s
    `numeric_grounding`); (3) the **reliability-tier rule** (§2's ADR): a
    directional `stance` needs ≥1 citation with `reliability_tier >= 3`.
    These three combine into `confidence` (a number) and `quality_status`
    (`grounded`/`degraded`/`insufficient`) — `insufficient` **forces
    `stance=NEUTRAL`** as an enforced invariant (`s11-04`'s abstention
    discipline: "declining to answer is a feature, not a failure," but
    over-abstaining is declining to do the work, so the thresholds get
    tuned against Phase 17's golden set, not guessed). A semantic judge
    (`SEMANTIC_JUDGE_ENABLED`) is a reserved, config-gated fourth layer —
    not built now. Also: an input relevance check so execution-shaped
    requests ("buy me X shares") get an explicit out-of-scope response
    rather than being reinterpreted as analysis.

    **Done (2026-09-10).** `app/guardrails/analysis_guard.py`:
    `check_input_relevance` matches imperative execution shapes only
    ("buy me 10 shares", "place an order") — never a question about
    buying ("should I buy AAPL"), which is a legitimate analysis request.
    `check_citation_integrity` is a direct translation of `s11-03`'s
    referential-integrity check — resolved vs. dangling `chunk_id`s
    against the actual retrieved set. `numeric_grounding` is `s11-04`'s
    check adapted: this domain synthesizes no `[low, high]` numeric range
    (unlike the reference's budget hours), so a figure is grounded iff it
    matches a real retrieved value directly, not "falls within an
    interpolated range" — checked only for `$`/`%`-marked figures, a
    deliberate scope limit avoiding false positives on bare numbers that
    aren't financial claims (an Item number, an RSI period). Percent
    figures are checked against both a field's raw value and its ×100
    reading, since yfinance stores some ratios as 0-1 fractions and others
    already percent-scale, and the rationale may phrase either way — a
    named imprecision, not a claim of unit certainty. `check_reliability_rule`
    matches §2's ADR literally. `guard_analysis` combines all three into
    one code-derived `confidence` (the mean Phase-12 citation weight over
    *resolved* citations — reusing the same signal that already decided
    ranking, not a new number invented here) and `quality_status`.
    `retrieval.low_confidence` (Phase 10's own soft-fail signal) is folded
    into the severity decision as a *degrading*, not automatically
    *insufficient*, input — forcing NEUTRAL on thin-but-otherwise-clean
    evidence would be exactly the over-abstention `s11-04` warns against.
    A fully-dangling citation list, any fabricated `$`/`%` figure, or a
    failed reliability rule are the three conditions that do force
    `insufficient`/`NEUTRAL`, matching `s11-03`'s "the one thing that's
    never acceptable is ignoring it." 25 new tests; 162 passing total.

    **Live verification (2026-09-10)**, same temporary-dev-Postgres
    discipline as Phases 9-12 (`fantasy-postgres-1` confirmed healthy
    throughout and after teardown): the full Phase 10-13 pipeline run
    against real `AAPL` data with a real `gpt-4o-mini` call, then guarded.
    `check_input_relevance` correctly separated a real analysis query from
    "Buy me 10 shares of AAPL." with the right out-of-scope reason. The
    guardrail resolved all 3 real citations (no dangling, no fabricated
    figures), `reliability_rule_passed=True`, landing on `degraded` purely
    because retrieval's own `low_confidence` was true that run — exactly
    the intended "thin evidence lowers confidence without forcing
    abstention" behavior, not a failure.

    One real, live-only finding, fixed on the spot: the model's free-text
    `rationale` named raw numeric source ids ("sources 370 and 554") that
    matched neither its own structured `citations` field nor any real
    retrieved chunk. `guard_analysis` never saw this — by `s11-03`'s own
    design, the structured `citations` field is the source of truth and
    prose is presentation over it, so nothing was actually ungrounded —
    but a reader skimming the rationale alone would be misled by a number
    that looks like a citation and isn't one. Fixed by tightening
    `system.j2`'s citation rule to explicitly forbid inline numeric source
    ids in prose; re-verified live immediately after — the same query's
    rationale no longer named any raw source number.
13. **Phase 14-15 — skipped**: no agentic Actor-Critic loop (Phase 13's
    guardrail is deterministic code, not an iterating model), no
    orchestration trigger.
14. **Phase 16 — Advanced retrieval, reserved, not built speculatively**:
    reranking is the named candidate (`s10-01`) — add it only once
    Phase 17's harness shows the relevant chunks are *in* the retrieved set
    but not at the top, the specific signal `s10-01` says reranking (and
    only reranking) fixes.
15. **Phase 17 — Evals**: two tools, not one. `evals/measure_retrieval.py`
    is the artisanal precision@k harness (`s10-02`) — 5-20 real queries,
    hand-annotated, median latency measured warm — and it is what decides
    Phase 16's reranking question with a real gain/cost table instead of a
    guess. `evals/golden_queries.json` is the golden set for the full
    pipeline (`s11-06`), seeded from README §2a, and **must include the
    out-of-scope execution case, an abstention case (unknown symbol, or a
    symbol with genuinely no retrievable content), and a contradiction case
    (sources that disagree, to check `contested` and the synthesis logic
    actually fire)** — skipping the abstention case means the suite rewards
    always answering, per `s11-06`'s own explicit warning. RAGAS
    (faithfulness/answer relevancy/context precision/context recall) is
    named as the upgrade path once the golden set is large enough to carry
    it; not adopted now — the artisanal harness is deliberately the
    cheaper, sufficient tool for the decisions this project actually needs
    to make at its current scale.
16. **Phase 18** — Reflex (ADR-012, supersedes Streamlit): trending,
    symbol detail, analyze form (showing per-claim citations with their
    reliability tier and the `contested`/`quality_status` flags),
    dashboard. Event handlers call `app/*` pipeline modules directly, in
    process — no `routers/*` FastAPI layer, since Reflex's own backend
    already serves that role and a second HTTP hop would be pure overhead
    for a single-user tool.

    **Done (2026-09-11).** Two real backend gaps surfaced immediately:
    `trending.py` and `analysis_store.py` (plus the `analyses` table
    itself) were named in CLAUDE.md's own tree since Phase 1 but never
    built — Phases 10-13 stayed scoped to the pure `/analyze` pipeline and
    explicitly deferred persistence each time. Built now: the `analyses`
    migration (citations/resolved/dangling/ungrounded_figures as JSONB,
    `s08-04`'s schema-split rule — typed columns for what's queried by,
    JSONB for what's read back whole), `analysis_store.py` (`insert_analysis`
    persists the GUARDED result, never the model's raw self-report;
    `add_to_monitor`/`remove_from_monitor`, soft-delete only), `trending.py`
    (ranks by absolute `%` change, deterministic, no LLM import, matching
    `technical_indicators.py`'s own rule). 12 new tests.

    `frontend/` (Reflex): `state.py` (plumbing only — every event handler
    calls straight into `app/*`, per ADR-012's dependency rule),
    `pages/{dashboard,symbol_detail,analyze}.py`. Blocking calls
    (Postgres, the LLM call) run via `asyncio.to_thread` inside
    `@rx.event(background=True)` handlers so a slow `/analyze` request
    doesn't freeze the app for other pages. A real candlestick chart
    (`reflex_components_plotly`'s `PlotlyFinance`/`Plotly` component,
    confirmed genuinely Plotly-native — see ADR-012) renders `daily_bars`
    on the symbol detail page.

    **Five real bugs found only by actually compiling/running the app —
    none guessable from memory of an earlier Reflex version:**
    - `DynamicRouteArgShadowsStateVarError` (twice): a dynamic route
      segment's name (`symbol` on `/symbols/[symbol]`) is reserved across
      *every* state, not just the page's own — `AnalyzeState.symbol` and
      even `SymbolState.symbol` (the page's own state!) both had to be
      renamed (`symbol_input`, `current_symbol`).
    - Plain Python `+` is unsupported between two dict-subscripted Vars
      (`ObjectItemOperation`) in this Reflex version — fixed by rendering
      separate text nodes instead of concatenating strings.
    - `reflex_components_plotly.Plotly`'s `data` prop expects a real
      `plotly.graph_objs.Figure` object, not a plain data/layout dict
      pair — the natural-looking guess from the component's own prop
      names was wrong; the actual `TypeError` named the expected type.
    - Calling `.length()` on a subscripted `dict`-typed Var raises
      `UntypedVarError` (subscripting loses type information to
      `typing.Any`) — fixed by flattening `AnalyzeState.result` into
      individual typed fields instead of one nested dict blob.
    - A cosmetic bug caught only by actually looking at the rendered
      page, not by compiling: confidence showed as "+50.00%" — the same
      `_pct` formatter used for price *change* (where a leading "+"
      correctly means "up from a baseline") was reused for confidence
      (a plain magnitude with no baseline to be "up" from). Fixed with a
      separate `_pct_plain` formatter; re-verified live.

    **Live verification (2026-09-11)**, same temporary-dev-Postgres
    discipline as Phases 9-13 (`fantasy-postgres-1`'s daemon was down in
    this environment for unrelated reasons — confirmed via `docker ps`
    failing entirely, not proceeding on an assumption — so a separate,
    already-running native `dockerd` was used instead, zero interaction
    with `fantasy-postgres-1` either way): driven with a real headless
    browser (Playwright; `chromium-cli` wasn't available in this
    environment), not just `curl`, against real `AAPL` data. Confirmed:
    the dashboard shows the real price/change/volume; the symbol detail
    page renders a real, correctly-colored candlestick chart from real
    `daily_bars`; the analyze form completed a real `gpt-4o-mini` call
    end to end, persisted the result via the new `analysis_store.py`, and
    displayed real citations; the input-relevance guard correctly
    blocked "Buy me 10 shares of AAPL" with the right out-of-scope
    message. Zero browser console errors across all three pages.

    **Docker containerization was also attempted** (`frontend/Dockerfile`,
    `docker-compose.yml` updated to ADR-012's topology — no `api` service,
    a new one-shot `migrate` service both `frontend` and `refresh_worker`
    depend on via `service_completed_successfully`, since `frontend` only
    waiting on postgres *health* — not on the schema actually
    existing — was a real startup race). One real bug found and fixed:
    Reflex's own `bun` installer needs `unzip`, not obviously so from its
    docs, only from the container's own `SystemPackageMissingError`. One
    real bug found and left **open, for Phase 19-20**: dynamic routes
    (`/symbols/[symbol]`) 404 under `reflex run --env prod --single-port`
    in an actual running container — static routes (`/`, `/analyze`)
    serve fine; root cause not yet identified. This is a
    production-container-serving gap, not a Phase 18 UI defect — the UI
    itself is fully built and live-verified via `reflex run`'s plain dev
    server above. Full `docker compose up` validation remains Phase
    19-20's explicit, separate job per its own line below, not assumed
    done here.
17. **Phase 19-20** — local validation (`docker compose up`, golden set,
    confirm no directional stance is ever backed by a low-reliability
    citation alone and at least one golden-set case actually abstains);
    finalize `ARCHITECTURE.md` against what was actually built. **Must
    resolve Phase 18's known open item first**: dynamic routes 404 under
    `reflex run --env prod --single-port` in a real container — `docker
    compose up` cannot be considered validated while `/symbols/{symbol}`
    doesn't actually serve.

    **Done (2026-09-12).** Phase 18's open item investigated and fixed
    first: reading Reflex's own source
    (`reflex.utils.exec.get_frontend_mount`) and inspecting a real
    `reflex export` build's output confirmed react-router's static export
    already generates `__spa-fallback.html` — a bootable shell for
    exactly the "dynamic route, value unknown at build time" case — but
    Reflex's built-in prod static server never serves it, a plain 404
    instead. Fixed in `frontend/frontend.py` via `api_transformer`
    (Reflex's own documented extension point): one explicit Starlette
    route matches `/symbols/{symbol}` and serves that shell directly;
    client-side react-router resolves the actual symbol once the bundle
    boots. Confirmed live, twice — a raw `reflex run --env prod
    --single-port` locally, then again through a real `docker compose up`
    — both times with a genuine browser navigating directly to
    `/symbols/AAPL` (not a client-side link click, the harder case), full
    hydration, zero console errors.

    **`docker compose up` then surfaced a second real bug**, found only
    by actually clicking through the full user journey (analyze → add to
    monitor → back to dashboard) against the real compose stack, not by
    curl or a single-page check: the dashboard and symbol-detail pages
    used each page's own `on_mount` prop to trigger `DashboardState.load`/
    `SymbolState.load`. `on_mount` is a component-lifecycle hook — it
    doesn't refire when navigating back to a route already mounted once
    in the same SPA session, since react-router keeps the app shell alive
    across navigation. A real symbol added to the watchlist from the
    analyze page therefore never appeared on the dashboard without a hard
    browser refresh. Fixed by moving both to `on_load` at
    `app.add_page(..., on_load=...)` registration — Reflex's own
    documented page-level hook, specifically meant to fire on every
    navigation *to* a route. Confirmed live: added `AAPL` to monitor from
    the analyze page, navigated back to `/`, saw it appear with real
    price/change data with no manual reload.

    **Golden-set-style confirmation, scoped to what Phase 19-20 itself
    asks for — not Phase 17's own full harness build**: `evals/
    golden_queries.json`/`measure_retrieval.py` remain Phase 17's
    separate, not-yet-built deliverable; building them now would be
    scope creep past what was actually asked ("phase 19 and 20"). Instead,
    the two specific properties Phase 19-20 names were confirmed directly
    against the live `docker compose` stack: **the abstention case** — an
    analysis on a genuinely unknown symbol (`ZZZZFAKE`) correctly landed
    on `quality_status=insufficient`, `stance=NEUTRAL`, `confidence=0.0`,
    and — a stronger confirmation than a clean case would have been — the
    model actually hallucinated a citation (`chunk_id=0`, never in the
    retrieved set, since retrieval was empty) and `guard_analysis` caught
    it anyway via the fully-dangling-citation check, forcing
    `insufficient` regardless. **The reliability-tier invariant** is
    enforced in code and unit-tested (`test_analysis_guard.py`), but is
    honestly **not independently live-testable against real data right
    now**: every currently-included catalog source already scores
    `reliability_tier >= 4` (ADR-006 dropped the one source that
    didn't), so no real citation exists today that *could* violate the
    `>= 3` floor — stated plainly rather than staged with synthetic data
    to manufacture a live-looking test.

    **A separate, real credential-safety incident during this pass, not
    a code bug**: a raw `docker compose config` call — run to debug why a
    `docker-compose.override.yml` port override wasn't taking effect —
    printed all four real secrets (`ANTHROPIC_API_KEY`, `BANXICO_SIE_TOKEN`,
    `FINNHUB_API_KEY`, `FRED_API_KEY`) in plaintext into the session
    transcript. Flagged to the operator immediately, who was advised to
    rotate all four. No project file or commit was affected — the
    exposure was transient, in a tool-output stream only — but it is
    recorded here because a credential seen in a session transcript is
    treated as compromised regardless of where else it may have leaked,
    matching this project's own established discipline from ADR-008's
    `FRED_API_KEY` incident. The lesson carried forward: never run a
    full env/config dump command in this repository without redaction,
    for any reason, including debugging.

    **`fantasy-postgres-1` note**: Docker Desktop's own daemon was down
    throughout this validation for unrelated reasons (confirmed via a
    failed `docker ps`, not assumed) — the same situation as Phases
    18/13. All work used a separate, native `dockerd` (`docker --context
    default`), with zero interaction with the real, Desktop-hosted
    `fantasy-postgres-1` either way. One incidental discovery, reported
    to the operator but not acted on: a *second*, dormant
    `fantasy-postgres-1` container object exists under the native
    context (state `created`, never started, dated three weeks before
    this session, its own separate `fantasy_postgres_data` volume) —
    left completely untouched.

    174 tests passing (no backend logic changed this phase — both fixes
    were frontend-only). `ARCHITECTURE.md`/`CLAUDE.md` updated against
    what was actually built, closing out the core build plan through
    Phase 20; Phase 17 (evals) and Phase 16 (reranking, reserved) remain
    the two named, deliberately-not-yet-built items.

## Extension — Discovery: company suggestions from general news (2026-09-12)

Added per `PLAYBOOK.md` §11.7 ("extend `CLAUDE.md` to add `<capability>`") —
the one sanctioned way to reopen this file after v1. This is new content
under its own heading; nothing above this line was rewritten to match it.

### Why this needed a fresh architecture pass, not a bolt-on

Every existing capability (`/analyze`, trending, monitor) starts from a
symbol the operator already picked. The operator asked for the opposite: a
feed that reads general market news and *suggests* companies worth a
look, acting "as an experienced trader," explicitly as an orchestrated
Actor-Critic-Boss pipeline. `PLAYBOOK.md` §2's axes were run fresh
against this one capability, not re-litigated for the ones already
shipped:

- **Axis 1 (CAG)**: no — the corpus (recent general news) changes
  between runs.
- **Axis 2 (SQL, exact entities)**: yes, for the *retrieval* side only —
  "give me recent general articles" is a `WHERE published_at > cutoff`
  read, no embedding needed. There is no user query to semantically match
  against; the Actor reads a time-windowed batch, not a search result.
- **Axis 3 (vector RAG)**: explicitly **not** used for this capability's
  storage. Reusing `document_chunks` (embedding-shaped, `symbol NOT NULL`)
  for general articles would repeat the exact anti-pattern
  `PLAYBOOK.md` §2 names: *"do not embed a corpus that Axis 2 already
  answered with SQL."* A new, plain SQL table instead (`general_news_items`).
- **Axis 4 (Agentic Actor-Critic-Boss)**: **yes — this is the fit**, and
  per the framework's own stated default, Critic and Boss are
  **deterministic code, not a second model call** — reserve a real LLM
  call for the critic only when a check genuinely needs judgment no rule
  can express. None of this capability's checks do.
- **Axis 5 (multi-agent orchestration)**: **no.** The trigger conditions
  (unknowable step count/order, multiple heterogeneous specialist roles
  whose *number* is data-dependent, a router whose capability set grows
  over time) don't fire — this is one specialist role in a fixed,
  enumerable sequence. Building a graph-orchestration layer here would be
  the "speculative infrastructure" `PLAYBOOK.md` repeatedly warns against
  for a personal, single-user tool. Named explicitly so nobody adds
  routing this doesn't need, the same discipline ADR-004's Axis-5 "No"
  row already established for `/analyze`.
- **Composition with `/analyze`**: an independent path sharing only
  plumbing (`services/market_data.py`, `services/llm_service.py`) — no
  conductor, staying Lean tier. A suggestion routes the operator *into*
  `/analyze` (pre-filled with the suggested symbol) rather than adding to
  `monitored_symbols` directly — a suggestion is a lead, not a grounded
  analysis, and it must pass through the real guardrailed pipeline before
  it can result in a monitored symbol, never bypass it.
- **Trigger**: scheduled only (operator's explicit choice, 2026-09-12) —
  `refresh_worker` runs it on a daily cadence, matching
  `economic_indicators`'s own "economy-wide, one fetch, not per-symbol"
  pattern; the UI only ever reads the latest persisted batch, never
  triggers a scan itself.

### Concrete design

**New table, `general_news_items`** (Axis 2, no embedding): `id`,
`source_name`, `reliability_tier` (copied from the catalog source at
ingest, same convention as `document_chunks`), `headline`, `summary`,
`url`, `published_at`, `ingested_at`. Unique on `(source_name, url)` — an
article's URL is a real, stable natural key here (unlike
`document_chunks`'s synthetic `document_id`, needed only because a filing
splits into multiple chunks per document).

**Sources, v1 scope**: `elfinanciero_news` and `el_economista_news` only
— both are already general-purpose feeds by nature (a sector/homepage
RSS, not filtered to one company), so no new catalog entries or new
vendor integrations are needed. Finnhub's `/news?category=general`
endpoint (a real, distinct general-market-news endpoint, different from
the already-used per-symbol `/company-news`) is a named, deliberately
deferred addition — reserved, not built now, since the two RSS sources
alone are sufficient to build and verify the capability honestly before
widening it.

**New parser function**: `rss_parser.parse_rss_general(feed, source_name)`
— a sibling to the existing `parse_rss_for_symbol`, skipping its
keyword-filter step entirely; both converge on the same `RawArticle`
shape already defined for the existing news parsers.

**Actor** (`services/llm_service.py`, a new function alongside
`generate_synthesis`, same `instructor.from_litellm` client, same
`gpt-4o-mini`/Haiku-4.5 fallback pair): given a batch of recent
`general_news_items` rows, produce `DiscoverySuggestions` (Instructor/
Pydantic, `app/schemas.py`) — a list of `SuggestedCompany` (`symbol`,
`company_name`, `reasoning`, `source_article_ids: list[int]`). System
prompt frames the persona explicitly as an experienced trader scanning
for catalysts, sector momentum, and unusual news density — not "anything
mentioning a company name."

**Critic** (`app/guardrails/discovery_guard.py`, deterministic code, no
LLM import — mirrors `analysis_guard.py`'s own existing shape):
1. **Citation integrity**: every `source_article_id` a suggestion cites
   must have been in the batch actually given to the Actor — the same
   dangling-citation check as `check_citation_integrity`, applied here.
2. **Symbol resolution**: every suggested `symbol` must actually resolve
   via `market_data.get_instrument_info()` — confirmed live
   (2026-09-12) that a bogus symbol returns a near-empty dict (one stray
   key, no `symbol`/`quoteType`) rather than raising, so resolution is
   checked by presence of `info.get("symbol")` **and**
   `info.get("quoteType")`, not by catching an exception that never
   comes.
3. **Reliability-tier rule**: reused as-is — a suggestion needs its
   citations to include at least one source with `reliability_tier >= 3`
   (trivially satisfied today, same defense-in-depth posture as the
   existing rule, since both configured sources score `>= 4`).

**Boss** (`app/analysis/discovery.py`): calls the Actor once, runs the
Critic over every suggestion, and for any suggestion that fails: retries
the *whole Actor call* once with feedback naming exactly which
suggestions were rejected and why, then — past that one retry — drops
only the still-failing suggestions (never the whole batch) and logs what
was dropped, the same "never silently discard" discipline
`augmentation.py`'s token-budget cutoff already established.

**New table, `suggestions`** (append-only, like `analyses` — no
`dismissed`/status tracking for v1, not asked for): `id`, `symbol`,
`company_name`, `reasoning`, `source_article_ids` (JSONB), `generated_at`.
The UI reads the latest batch by `generated_at`, nothing more.

**`refresh_worker` integration**: a new daily-cadence job — fetch both
RSS sources' full feeds (`parse_rss_general`), upsert into
`general_news_items`, read the last `DISCOVERY_LOOKBACK_DAYS` (a
worker-file constant, matching `FRED_LOOKBACK_DAYS`'s own precedent —
not a `Settings` field, since it isn't operator-tunable) worth of rows,
run the Boss loop, persist to `suggestions`.

**New Reflex page, `/feeds`**: lists the latest suggestions (symbol,
company name, reasoning, source links) with a link into `/analyze`
pre-filled with the suggested symbol and a sensible default query — never
a direct "add to monitor" from an unguarded suggestion.

### Build order (own numbering, D1-D6 — not a continuation of Phases 1-20's numbering, since this is a `PLAYBOOK.md` §11.7 extension, not the original v1 plan)

1. **D1** — `general_news_items` migration + `parse_rss_general` +
   `general_news_store.py`, tested + live-verified against both real RSS
   feeds.
2. **D2** — `sql_retriever.get_recent_general_news()`.
3. **D3** — Actor (`generate_discovery_suggestions` in `llm_service.py`)
   + `DiscoverySuggestions`/`SuggestedCompany` schemas.
4. **D4** — Critic (`discovery_guard.py`) + Boss (`discovery.py`),
   `suggestions` migration + store.
5. **D5** — `refresh_worker` daily-cadence integration.
6. **D6** — `/feeds` Reflex page.

Each phase gets the same discipline as Phases 1-20: real tests against
real-shaped fixtures, then live verification against a temporary dev
Postgres (never `fantasy-postgres-1`) with real API calls, bugs found and
fixed on the spot, documented here and in `ARCHITECTURE.md`, then
committed.
