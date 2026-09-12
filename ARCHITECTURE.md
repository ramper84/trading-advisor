# Architecture

This is the architecture contract for **Trading Advisor**. New code must fit
one of the layers below; if a piece fits nowhere, decide where it lives and
update this document — do not add another folder at the root.

This is this project's **third** architecture. The first (Alpaca execution)
and second (TradingView-only) are both retired in full — see the Appendix's
ADRs. Everything below describes only the current scope: multiple
independently configured structured and unstructured market-data sources,
no execution, no single dependency the whole system hinges on.

## 0. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Matches `PLAYBOOK.md` §4's default |
| HTTP | FastAPI + uvicorn | Typed request/response is the contract |
| Store | PostgreSQL 16 (`pgvector/pgvector:pg16`) | Axis 2's `market_observations`/`instruments`/`daily_bars`/`fundamentals`/`analyst_ratings`/`economic_indicators`/`analyses`/`monitored_symbols` (ADR-007 widens this from 4 to 8) **and** Axis 3's `document_chunks` — pgvector is now activated |
| Cache | Redis | Freshness-budget cache for live structured-quote reads |
| Structured data | `yfinance` (primary, covers BMV via `.MX`), `finnhub` (fallback) | Axis 2, no brokerage account, both free/free-tier. `yfinance` alone also backs `instruments`/`daily_bars`/`fundamentals`/`analyst_ratings` (ADR-007) — no new dependency per data category |
| Economic data | Banxico SIE (Mexico), FRED (US) | Axis 2, free/official, token or key registration required — ADR-006 |
| Unstructured data | SEC EDGAR full-text search, Finnhub `/company-news`, Yahoo Finance news (`yfinance`), El Financiero + El Economista RSS (`feedparser`) | Axis 3 — see `data_catalog.yaml` for the per-source cadence/quality record. No social/community source of any kind — ADR-006 |
| Embedding model | `text-embedding-3-small` | `PLAYBOOK.md` §4/Axis 3 default |
| LLM access | LiteLLM (`gpt-4o-mini`, fallback a Claude Haiku model) | One wrapper, cross-provider fallback |
| Frontend | **Reflex** (ADR-012, supersedes Streamlit) | Trending list, symbol detail, analyze form, monitor dashboard — pure Python, real React frontend + async FastAPI backend; event handlers call `app/*` directly, no separate API service |
| Deploy | docker compose (postgres, redis, frontend, **refresh_worker**) | All nine sources are plain HTTPS APIs — everything is containerizable this time; no separate `api` service — Reflex's own backend serves that role (ADR-012) |

**Not used, deliberately**: no vector index in v1 (Axis 3's own default —
sequential scan until a measured latency number says otherwise), no agent
orchestration framework (Axis 5 rejected), no ORM beyond what
Alembic/SQLAlchemy needs, no order-execution path of any kind (unchanged
from the second architecture — there is still nothing here that acts), no
social or community content of any kind, ever (ADR-006 — a hard rule, not
merely a Reddit-specific exclusion).

## 1. Architecture decision

**Axis 2 (SQL-retrieval RAG)** covers eight tables, widened by ADR-007 from
an original three: `market_observations` (quote ticks — now carrying the
full `fast_info` set: OHLC-today, 52-week hi/lo, SMA50/200, market cap,
exchange/currency/quote-type, all from the *same* call already made, zero
new API cost), `instruments` (a static reference table — sector/industry
from the slower `Ticker.info`, refreshed once on monitor-add, not on every
poll), `daily_bars` (adjusted-close OHLCV history — the actual chart
backbone), `fundamentals` (valuation metrics and reported financials
merged into one snapshot table), `analyst_ratings` (rating-change events),
`economic_indicators` (ADR-006), and `analyses`. All name their entities
exactly (symbol-or-series-id, timestamp), typed columns, no embedding.
Two `articles/s10-05` schema-divergence calls are worth naming explicitly:
`economic_indicators` is separate from `market_observations` (a price tick
is symbol-keyed, a Banxico/FRED series is economy-wide — forcing them
together would mean a `symbol` column that's `NULL` for every macro row),
while `fundamentals` deliberately merges what could have been two tables
(valuation ratios and reported financials) because both are "a company's
financial snapshot as of a date" — not divergent enough to split. **Axis 3
(vector RAG) is newly
activated**, reversing the second architecture's deferral:
`sec_edgar_filings` and the five news sources (Finnhub, Yahoo Finance, El
Financiero, El Economista) are genuinely paraphrastic content with no
exact-match retrieval path — a real corpus that grows continuously, exactly
the case `PLAYBOOK.md`'s Axis 3 is for. **Axis 1 (CAG)** stays not-selected
— no rulebook exists to ground it. **Axis 4 (Critic)** stays downgraded to
a plain output guardrail (no execution to gate), extended with one new rule
below. **Axis 5 (orchestration)** stays not-selected — `/analyze` runs a
fixed two-retrieval-then-one-generation pipeline; nothing is chosen at
runtime.

**The confidence gate** (the substantive change Axis 3's activation forces
into the guardrail, and the answer to "did this analysis pass for this
session"): `guardrails/analysis_guard.py` runs three deterministic checks,
cheapest first, per `articles/s11-04`'s verification funnel, and combines
them into a `confidence` score and a `quality_status`
(`grounded`/`degraded`/`insufficient`) persisted on every `analyses` row —
never a self-reported LLM confidence, which the RAGAS article (`s11-06`)
and the hallucination article (`s11-04`) both treat as unreliable on its
own.

1. **Citation integrity** (`s11-03`), checked in code, never trusted to the
   model: every `chunk_id` an analysis cites must actually have been in the
   retrieved set for that request. A citation pointing at a chunk that was
   never retrieved is dangling — a hallucination with a well-formed
   citation, the specific failure `s11-03`'s own closing section names.
2. **Numeric grounding** (`s11-04`): the price/indicator figures the
   analysis cites must fall within the range of what was actually
   retrieved (interpolation between cited sources is fine; a figure outside
   every cited source's range is flagged as unsupported extrapolation).
3. **The reliability-tier rule**: every `document_chunks` row carries a
   `reliability_tier` copied from its catalog source at ingest time, and a
   `BULLISH`/`BEARISH` `stance` needs ≥1 citation with `reliability_tier
   >= 3`. This rule was written for `reddit_mentions` (`reliability: 2`,
   `consistency: 2` — below `articles/s06-02`'s own `is_rag_ready` bar) and
   is kept after ADR-006 dropped that source entirely: every remaining
   source scores `reliability >= 4`, so the rule currently has nothing to
   gate against. It stays as defense-in-depth for any future lower-quality
   source, not because a current one needs it — removing a working
   guardrail because its current trigger went away would be optimizing for
   today's catalog over the next one.

If (1) or (2) fail outright, `quality_status="insufficient"` and
`stance` is **forced to `NEUTRAL`** regardless of what the model produced —
an enforced invariant, not a convention the model is merely asked to
follow (`s11-04`'s abstention discipline: "an honest `None`/abstention is
worth more than a filler answer"). Mixed signals degrade `confidence`
rather than rejecting outright. A model-based semantic judge (`s11-04`'s
second, more expensive verification layer) is a reserved, config-gated
addition — not built until the cheap checks above prove insufficient
against Phase 17's golden set.

**Live pass-through, per source type** (`PLAYBOOK.md` §2's cross-cutting
note, unchanged in kind from the second architecture, just scoped
per-source now):

1. **Structured sources** (`yfinance_quotes`, `finnhub_quotes`) get both
   tiers: a live-read path (`FRESHNESS_BUDGET_SECONDS`-cached) for
   `GET /symbols/{symbol}/status`, and a scheduled-refresh path (1-5 min)
   writing `market_observations`.
2. **Economic-data sources** (`banxico_sie`, `fred_economic_data`) get
   scheduled refresh only, daily — Banxico/FRED release on their own
   schedule, never continuously, so there is no live-read path for them.
3. **Unstructured sources** get scheduled refresh only, at the cadence each
   source declares in `data_catalog.yaml` (hourly for filings, 30 min for
   the five news sources) — there is no "live status" reading for a
   document; the corpus it produces is queried through Axis 3's retriever,
   not read live per request.

**Deployment**: unlike the second architecture, nothing here requires a
GUI desktop app or a shared host network namespace — every source is a
plain HTTPS API. `refresh_worker.py` is therefore a normal docker-compose
service (see ADR-004 below, which supersedes ADR-003).

## 2. The layer map

```
app/
├── config.py · schemas.py · main.py
├── services/        market_data.py — structured connectors (yfinance/finnhub), live-read + cache
│                     llm_service.py — generation AND embedding calls
├── guardrails/      analysis_guard.py — output validation, divergence flag, reliability-tier citation rule
├── ingest/          OFFLINE: catalog.py, loaders/, parsers/ (incl. rss_parser.py,
│                              economic_data_parser.py — ADR-006; instrument_parser.py,
│                              daily_bar_parser.py, fundamentals_parser.py,
│                              analyst_ratings_parser.py — ADR-007), normalizers/, chunking.py,
│                              embedding.py, refresh_worker.py, observation_store.py,
│                              economic_indicator_store.py (ADR-006), instrument_store.py,
│                              daily_bar_store.py, fundamentals_store.py,
│                              analyst_rating_store.py (all Phase 9, ADR-007)
├── retrieval/       ONLINE: sql_retriever.py (Axis 2), vector_retriever.py (Axis 3, orchestrates the below)
│                     hybrid_search.py — lexical (tsvector/GIN) branch + RRF fusion with semantic
│                     temporal.py — per-source-family decay/recency weighting, applied last
├── analysis/        trending.py — deterministic, NO LLM import
│                     technical_indicators.py — RSI + volatility from daily_bars, NO LLM import (ADR-007)
│                     augmentation.py — assembles SQL + vector retrieval into one XML context,
│                              pure function, NO LLM import, NO DB access (Phase 11, ADR-009)
│                     synthesis.py — deterministic per-citation weight + weighted-median anchor +
│                              contested flag, pure function, NO LLM import (Phase 12, ADR-010)
│                     analysis_store.py — Axis 2, analyses + monitored_symbols
├── prompts/         analyze/v1/{system,user}.j2
└── routers/         NOT built (ADR-012) — Reflex's own backend is the app server;
                       its event handlers call app/* directly, in-process. Reserved
                       only for a future second HTTP consumer, if one ever appears.

frontend/            Reflex project (ADR-012, Phase 18) — pages/ (trending, symbol
                       detail, analyze form, dashboard), state.py (rx.State, plumbing
                       only — calls app/* directly, no business logic of its own)
```

Lean tier (`PLAYBOOK.md` §3): the offline/online split
(`articles/s06-01`) is the organizing idea — `ingest/` never runs inside a
request; `retrieval/` never touches a network source directly.

## 3. Dependency rules (MUST / MUST NOT)

| Layer | MAY import | MUST NOT import |
|---|---|---|
| `config.py` | (nothing internal) | — |
| `schemas.py` | `config` | everything else |
| `services/run_recorder.py` | `config` | everything else — pure observability plumbing, importable by `ingest/*`, `retrieval/*`, and `routers/*` alike |
| `services/db.py` | `config` | everything else — the one shared Postgres connection helper (registers the pgvector adapter), importable by `ingest/*`, `retrieval/*`, and `analysis/*` alike |
| `services/market_data.py` | `config`, `schemas` | `routers`, `analysis`, `guardrails` |
| `services/llm_service.py` | `config`, `schemas`, `prompts`, `analysis/synthesis.py` (the `EvidenceAggregate` it reasons over) | `routers` |
| `guardrails/*` | `config`, `schemas`, `analysis/synthesis.py` (types only), `retrieval/sql_retriever.py` (types only), `retrieval/vector_retriever.py` (types only) | `routers`, `services/llm_service.py` — no LLM import, ever; a semantic judge (reserved, §8) would be the one exception |
| `ingest/*` | `config`, `schemas`, `services/market_data.py`, `services/db.py` | `routers`, `guardrails`, `retrieval/*` |
| `retrieval/vector_retriever.py` | `config`, `schemas`, `retrieval/hybrid_search.py`, `retrieval/temporal.py` | `ingest/*` (reads what ingest already wrote, never triggers a fetch), `routers` |
| `retrieval/hybrid_search.py`, `retrieval/temporal.py` | `config`, `schemas` | `ingest/*`, `routers`, each other's caller role — these are called *by* `vector_retriever.py`, not by routers directly |
| `retrieval/sql_retriever.py` | `config`, `schemas` | `ingest/*`, `routers` |
| `analysis/trending.py` | `config`, `schemas` | `services/llm_service.py` — **no LLM import, ever** |
| `analysis/augmentation.py` | `config`, `schemas`, `analysis/technical_indicators.py`, `retrieval/sql_retriever.py` (types only), `retrieval/vector_retriever.py` (types only) | `services/llm_service.py` — no LLM import; `services/db.py` — pure function, caller fetches rows |
| `analysis/synthesis.py` | `config`, `schemas`, `retrieval/hybrid_search.py` (types only), `retrieval/temporal.py` (`temporal_weight`), `retrieval/vector_retriever.py` (types only) | `services/llm_service.py` — **no LLM import, ever**; `services/db.py` — pure function |
| `analysis/analysis_store.py` | `config`, `schemas` | `routers` |
| `prompts/*` | `schemas` | everything else |
| `routers/*` | anything above | — not built (ADR-012); reserved for a future second HTTP consumer only |
| `frontend/*` (Reflex) | anything under `app/*` | holds no business logic of its own — `state.py` plumbs `app/*` calls to the UI, nothing more (ADR-012) |
| `main.py` | `config`, `routers` | — |

## 4. The conductor

**N/A — Lean tier.** `frontend/state.py`'s analyze-page event handler is
the one path that touches both retrieval types, and it does so directly,
in-process (ADR-012: no `routers/analyze.py`, no HTTP hop — Reflex's own
backend calls `app/*` in the same process), in a fixed order:

```
frontend state.py: AnalyzeState.run_analysis()
 → retrieval/sql_retriever.py     (recent market_observations + past analyses)
 → retrieval/vector_retriever.py  (top-k document_chunks, threshold + soft-fail)
 → analysis/augmentation.py       (assemble one XML-delimited context, Phase 11)
 → analysis/synthesis.py          (deterministic per-citation weight + anchor, Phase 12)
 → services/llm_service.py        (one generation call, reasons over the aggregate)
 → guardrails/analysis_guard.py   (validate + reliability-tier rule)
 → analysis/analysis_store.py     (persist)
```

Both retrieval calls always run — nothing routes between them at runtime,
so this is augmentation (`articles/s09-04`), not a conductor. Extract one
only if a second, genuinely cross-capability request appears.

## 5. Request paths

No HTTP routes (ADR-012) — each is a Reflex page's `on_load`/event handler
in `frontend/state.py`, calling `app/*` directly, in-process:

```
TrendingState.load()  (dashboard page, on_load)
 1. read monitored_symbols (active=true)                          free
 2. read latest market_observations per symbol                     free
 3. trending.rank() — deterministic % change / volume sort          free

SymbolState.load(symbol)  (symbol detail page, on_load)
 1. market_data live read (cached, FRESHNESS_BUDGET_SECONDS)         free
 2. read recent market_observations for symbol (sparkline)           free
 3. read analyses history for symbol, newest first                   free

AnalyzeState.run_analysis(symbol, query)  (analyze form submit)
 1. sql_retriever: recent market_observations, instrument reference row,   free
    latest daily_bars + fundamentals snapshot, recent analyst_ratings,
    relevant economic_indicators (country-matched: MX symbols get
    banxico_sie, US symbols get fred_economic_data), technical_indicators
    (RSI/volatility computed from daily_bars) + past analyses
 2. vector_retriever, in order (s10-06's cheap-first, soft-last):       free
    a. hard filter: WHERE symbol = :symbol, before any vector math
    b. semantic (pgvector) + lexical (tsvector/GIN) search, parallel
    c. hybrid_search.reciprocal_rank_fusion() — positions, never raw scores
    d. temporal.py's per-source-family weighting, applied last
    e. distance-threshold soft-fail -> low_confidence if nothing clears it
 3. augmentation: extractive compression (filings), edge-loading         free
    (front + reversed(back)), token-budget fit with logged drops
 4. synthesis: weighted aggregate (reliability_tier + temporal + fusion   free
    rank) computed in code; contested flag on strong-source disagreement
 5. generate stance/confidence/rationale/citations over that aggregate    LLM
 6. analysis_guard.validate(): citation integrity -> numeric grounding ->  free
    reliability-tier rule -> confidence + quality_status; insufficient
    forces stance=NEUTRAL
 7. persist analyses row                                                  free
 8. update state (page shows "add to monitor")

MonitorState.add(symbol, analysis_id?)  ("add to monitor" button)
 1. upsert monitored_symbols (active=true)                            free

MonitorState.remove(symbol)  ("remove from monitor" button)
 1. set monitored_symbols.active = false                              free

MonitorState.load()  (dashboard page, on_load)
 1. read monitored_symbols (active=true) + latest observation each     free
```

Offline (`ingest/refresh_worker.py`, not a request path): per-source
scheduled loop reading `data_catalog.yaml`'s cadence, running
loader → parser → normalizer → (chunk → embed, for Axis-3 sources) → store.

## 6. Contracts that do not break

- Reflex pages/routes (ADR-012, no REST API): `/` (dashboard), `/symbols/{symbol}`,
  `/analyze`, `/health` (still a plain FastAPI route — Reflex apps can mix
  in bare API endpoints, and a liveness check has no state to plumb
  through a page).
- `analyses.stance` ∈ `{BULLISH, BEARISH, NEUTRAL}`, never defaulted.
- `analyses.quality_status = "insufficient"` ⟹ `stance = NEUTRAL`, always —
  an enforced invariant checked in code, not a convention the model is
  merely asked to follow.
- A `BULLISH`/`BEARISH` stance always carries ≥1 citation with
  `reliability_tier >= 3` — enforced in `analysis_guard.py`, not left to
  the prompt alone.
- Every citation an analysis returns resolves to a `chunk_id` that was
  actually in that request's retrieved set — checked in code
  (`analysis_guard.py`'s citation-integrity pass), never trusted to the
  model.
- `document_chunks.reliability_tier` and `.embedding_version` are copied
  at ingest time, never recomputed at query time.
- Which sources are active comes from `data_catalog.yaml`'s `decision`
  field; nothing hardcodes a source list in `app/` code.
- The schema comes from `migrations/`; nothing creates a table on demand.

## 7. Where does new code go?

| If you add… | It goes in… |
|---|---|
| A new structured quote vendor | `services/market_data.py` + a new `data_catalog.yaml` entry, `axis: sql_retrieval` |
| A new economic-data source | `ingest/parsers/economic_data_parser.py` + a new `data_catalog.yaml` entry, `axis: sql_retrieval`, feeding `economic_indicators` |
| A new market-data category (instrument/fundamentals/ratings-shaped) | A new `ingest/parsers/*_parser.py` + `*_store.py` pair feeding its own Axis-2 table — check `s10-05`'s schema-divergence rule first: does it merge into `fundamentals` (another financial-snapshot-as-of-a-date field) or genuinely need a new table? |
| A new technical indicator | `analysis/technical_indicators.py` — compute from `daily_bars` on read, NO LLM import; persist a new column only if it turns out too expensive to compute per-request |
| A new unstructured **news** source | If it's RSS, `ingest/parsers/rss_parser.py` already handles the shape — just a new `data_catalog.yaml` entry with the feed URL and keyword list. If it needs a real API client, a new `ingest/parsers/*_parser.py` producing `news_parser.RawArticle`. Either way, `axis: vector_rag`, no other code changes needed to activate it. **Never a social/community feed of any kind — that's not a config toggle, it's excluded by policy (ADR-006).** |
| A prompt change | `prompts/analyze/v<N>/` — new version, not an edit |
| A new query pattern over observation/analysis history | `retrieval/sql_retriever.py` |
| A change to chunking/embedding strategy | `ingest/chunking.py` / `ingest/embedding.py`, plus a re-embedding pass (`articles/s11-05`) |
| A new page/view | `frontend/pages/`, thin — state/event handlers in `frontend/state.py` call `app/*`, no business logic in either |
| An HTTP endpoint (rare — a second consumer beyond the Reflex UI) | `routers/`, thin (ADR-012: not built by default) |

## 8. Reserved slots

- **Axis 1 — a personal "analysis style" CAG doc.** Not selected for v1.
- **Reranking** (`articles/s10-01`, `PLAYBOOK.md` Phase 16). Hybrid search
  is *not* in this slot — it's adopted from Phase 10 (§1) because this
  domain's exact-identifier density makes the case immediately, not
  speculatively. Reranking stays reserved because there's no evidence yet
  of the specific problem it fixes (relevant chunks retrieved but ranked
  low) — `evals/measure_retrieval.py` (`s10-02`) is what will show that
  evidence if it appears.
- **Query expansion/decomposition** (`s10-04`). Deliberately not adopted,
  not merely deferred — `/analyze`'s query is one ticker, and the article's
  own guidance is that a short, single-topic query needs neither technique.
- **A semantic judge** (`s11-04`'s second verification layer,
  `SEMANTIC_JUDGE_ENABLED`). Add only if numeric grounding + citation
  integrity prove insufficient against the golden set.
- **RAGAS** (`s11-06`). The artisanal precision@k harness (`s10-02`) is the
  deliberately cheaper, sufficient tool at this project's scale; RAGAS is
  the named upgrade path once the golden set grows large enough to carry it.
- **A vector index (`hnsw`).** Sequential scan until a measured latency
  number justifies it.
- **A conductor**, if a second, genuinely cross-capability request appears.
- **Per-article sentiment tagging** (ADR-007). Tagging every ingested news
  chunk bullish/bearish/neutral at ingest time would add an LLM call per
  article — a real cost multiplier for no proven benefit over computing
  `stance` once, at analysis time, from the retrieved set. Reserved, not
  built.
- ~~`alpaca-core` / `alpaca-mcp`~~ — deleted (ADR-001).
- ~~`tradingview-mcp-jarp` dependency~~ — dropped (ADR-004).
- ~~`reddit_mentions`~~ — dropped entirely, not merely excluded-with-reason
  (ADR-006). No social/community feed of any kind is a candidate for this
  project going forward — not a per-source decision to revisit.
- ~~`tradingview_community` / `google_finance` / `investing_com_calendar`~~
  — considered and excluded-with-a-written-reason in `data_catalog.yaml`
  (ADR-006); not a reserved slot to reopen without new information (no
  public API exists for any of the three as of 2026-09-10).
- ~~Confirming Banxico's own series ids~~ — resolved 2026-09-11, live
  against the real SIE API with a real token: `SF61745` (overnight target
  rate), `SF43718` (USD/MXN FIX), `SP30578` (INPC annual inflation %),
  wired into `refresh_worker.py`'s `BANXICO_SERIES`. A FRED-side GDP series
  remains unidentified — that piece alone stays open, not the whole item.

## Appendix — Architecture Decision Records

### ADR-001 — Drop Alpaca execution scope entirely (2026-09-06)

- **Status**: Accepted.
- **Context**: v1 originally read a paper-trading Alpaca account and
  proposed human-approved orders. The operator decided against ever using a
  brokerage account for this project.
- **Decision**: Remove the entire execution path — no brokerage client, no
  approval workflow, no risk critic gating an order.
- **Consequence**: `alpaca-core`/`alpaca-mcp` (sibling repos, fully built
  and tested in a prior session) had no purpose left and were **deleted**
  (user-confirmed; neither had any commits). "No individual stock-picking"
  is lifted. `examples/thesis-v1-archived-alpaca-execution.md` is retired.

### ADR-002 — Rename recommendation labels to BULLISH/BEARISH/NEUTRAL (2026-09-06)

- **Status**: Accepted.
- **Context**: `BUY`/`SELL`/`HOLD` name executable brokerage actions; ADR-001
  removed execution entirely.
- **Decision**: `analyses.stance` uses `BULLISH`/`BEARISH`/`NEUTRAL`.
- **Consequence**: Every schema/prompt/UI surface uses the new enum; no
  migration needed, no code existed yet.

### ADR-003 — Ingest worker runs host-native, not in docker-compose (2026-09-06) — **superseded by ADR-004**

- **Status**: Superseded.
- **Context**: The second architecture depended on `tradingview-mcp-jarp`,
  which requires a real, GUI TradingView Desktop app reachable only via a
  host-loopback CDP port.
- **Decision** (at the time): run the ingest worker as a host-native
  process, outside docker-compose.
- **Why superseded**: ADR-004 drops the TradingView dependency entirely.
  None of the five sources it's replaced with need a host-side GUI process
  — `refresh_worker.py` is a normal containerized service again.

### ADR-004 — Drop TradingView entirely; multiple configured sources; Axis 3 activates (2026-09-06)

- **Status**: Accepted.
- **Context**: The operator decided against depending on TradingView at
  all (even via `tradingview-mcp-jarp`), preferring several independently
  configured sources — reasoning being TradingView itself is likely just
  aggregating multiple vendors internally. Structured-only data also meant
  Axis 3 had nothing genuine to retrieve; once real unstructured sources
  (filings, news, social) entered the picture, that stopped being true.
- **Decision**: Adopt `data_catalog.yaml` (`articles/s06-02`) naming five
  sources — `yfinance_quotes`, `finnhub_quotes` (Axis 2),
  `sec_edgar_filings`, `finnhub_news`, `reddit_mentions` (Axis 3, newly
  built pipeline per `articles/s06-03`/`s07-03`). Activate pgvector.
  Introduce the reliability-tier citation rule in `analysis_guard.py`
  because `reddit_mentions` fails `articles/s06-02`'s own `is_rag_ready`
  bar (reliability=2, consistency=2) and is included anyway, by exception,
  not by quietly averaging the score up.
- **Consequence**: ADR-003 is superseded (see above). `services/
  tv_connector.py` is replaced by `services/market_data.py` + the full
  `ingest/` pipeline. New env vars (`FINNHUB_API_KEY`, `REDDIT_CLIENT_ID`/
  `SECRET`, `EDGAR_USER_AGENT`) replace `TRADINGVIEW_MCP_PATH`/
  `TV_DEBUG_PORT`. `document_chunks` (pgvector) is a new table alongside
  the existing `market_observations`/`analyses`/`monitored_symbols`.

### ADR-005 — Confidence gate (s10/s11) built into Phases 8-13, 17 (2026-09-06)

- **Status**: Accepted.
- **Context**: the operator asked for a computed confidence number gating
  whether an analysis "passes" before being trusted, and for the
  `production-rag-handbook`'s `articles/s10-*`/`s11-*` series to be checked
  against the phase plan rather than assumed.
- **Decision**: adopt, now (not reserved) — hybrid search + RRF fusion
  (`s10-03`) given this domain's identifier density; per-source-family
  temporal weighting (`s10-06`); `embedding_version`/`source_hash` columns
  from day one (`s11-05`); corrected edge-loading and logged-drop
  distillation (`s11-01`); weighted, contradiction-aware synthesis with a
  deterministic aggregate computed in code (`s11-02`); citation integrity
  checked in code, never trusted to the model (`s11-03`); numeric grounding
  and an enforced `insufficient -> NEUTRAL` abstention invariant (`s11-04`);
  the artisanal precision@k harness plus an abstention+contradiction case in
  the golden set (`s10-02`/`s11-06`). Explicitly **not** adopted: reranking
  (no evidence yet of the problem it fixes — reserved pending
  `measure_retrieval.py`), query expansion/decomposition (wrong query
  shape for this domain), a semantic judge and RAGAS (both reserved,
  cheaper tools suffice at this scale).
- **Consequence**: `analyses` gains `confidence` (float) and
  `quality_status` (`grounded`/`degraded`/`insufficient`) columns;
  `document_chunks` gains `embedding_version`/`source_hash`;
  `retrieval/hybrid_search.py` and `retrieval/temporal.py` are new modules
  under `retrieval/vector_retriever.py`; `analysis_guard.py`'s
  responsibility grows from a single reliability-tier check to the full
  three-step funnel in §1.

### ADR-006 — Drop Reddit and TradingView-as-source entirely; add official economic data and Mexican news (2026-09-10)

- **Status**: Accepted.
- **Context**: Before Phase 9 began, the operator asked to redesign the
  source list around their actual day-to-day habits, with one hard rule:
  no social/community feed of any kind, ever — a strengthening from
  "Reddit specifically" to a permanent category exclusion. The operator's
  own list named TradingView (charting + community analysis), Yahoo/Google
  Finance, Investing.com's economic calendar, El Economista, El Financiero,
  and Banxico. Each was researched for actual data-access feasibility
  (API vs. account vs. infeasible) before any catalog change, live where
  possible:
  - **TradingView**: no public API, confirmed against the same
    `tradingview-mcp-jarp` research the second architecture was built on —
    the only access path is CDP against a locally running Desktop app, the
    exact constraint ADR-003/ADR-004 already removed. Its unique value
    (community-shared analysis) is the same "grain of salt" category as
    Reddit.
  - **Yahoo Finance**: already in use (`yfinance_quotes`); confirmed live
    to cover BMV via `.MX` tickers (e.g. `WALMEX.MX`) — this, not
    TradingView, is what actually solves Mexican-market coverage. Also
    exposes its own news aggregation (`Ticker.news`), confirmed against a
    live call the same day.
  - **Google Finance**: confirmed no public API has existed since 2012;
    only the `GOOGLEFINANCE()` Sheets formula remains, unusable as a
    backend source.
  - **Investing.com**: confirmed no free/official API against their own
    support docs — only a read-only widget or paid third-party scrapers.
    Replaced by the official sources for the same underlying data: FRED
    (US Fed decisions/inflation) and Banxico's SIE API (Mexican rate
    decisions/inflation), both free and official, requiring only a
    registration token.
  - **El Financiero / El Economista**: both confirmed to publish free,
    live, no-account RSS feeds. El Financiero's is a standard Arc XP
    outboundfeed. El Economista's required more digging — the site 403s
    generic automated fetches (confirmed via both `WebFetch` and a bare
    `curl`) but serves its feed to a standard browser User-Agent; the real
    feed URL (`/rss/ultimas-noticias`, no `.xml` extension) was found via
    its own homepage's `<link rel="alternate">` autodiscovery tag, not
    guessed. Section-specific feed slugs (`sectorfinanciero`, `economia`,
    `empresas`) 403 consistently and are not relied upon — only the
    general "últimas noticias" feed is confirmed public, matching
    `elfinanciero_news`'s shape (general feed + client-side keyword match,
    not a per-symbol query).
- **Decision**: `data_catalog.yaml` v2 — dropped `reddit_mentions`
  entirely. Added `yfinance_news`, `banxico_sie`, `fred_economic_data`,
  `elfinanciero_news`, `el_economista_news` (9 sources included). Recorded
  `tradingview_community`, `google_finance`, `investing_com_calendar` as
  excluded-with-a-written-reason (`articles/s06-02`'s "deliberate
  exclusion" discipline) rather than silently omitted. Kept
  `finnhub_quotes`/`finnhub_news` as vendor redundancy per the operator's
  explicit choice, even though not in their original day-to-day list.
  `economic_indicators` is a new Axis-2 table, separate from
  `market_observations` (`s10-05`'s schema-divergence rule — see §1).
- **Consequence**: `app/ingest/parsers/reddit_parser.py` deleted (not
  archived), along with its test and `praw` as a dependency. New parsers:
  `economic_data_parser.py` (Banxico/FRED, each with its own disguised-null
  marker — `"N/E"` and `"."` respectively), `rss_parser.py` (shared by both
  Mexican outlets, browser User-Agent required). `news_parser.py` extended
  with `parse_yfinance_news`, converging on the same `RawArticle` shape
  Finnhub already used. The reliability-tier guardrail rule (§1) now has no
  live source to gate against — kept as defense-in-depth, not removed. All
  new parser fixtures were captured from real live calls (yfinance,
  El Financiero, El Economista) rather than invented, per this project's
  own "verify before implementing" discipline; Finnhub/Banxico/FRED
  `fetch_*` functions remain untested pending real credentials.

### ADR-007 — Widen Axis 2 to a full market-data framework (2026-09-10)

- **Status**: Accepted.
- **Context**: the operator supplied an 8-category market-data framework
  (instrument identification, price/volume, valuation, fundamentals,
  technical indicators, macro context, sentiment/qualitative, portfolio
  tracking) and asked for a quick audit of what the parsers actually
  persisted against it. The audit found `MarketObservationRecord` captured
  only a live tick (`price`/`bid`/`ask`/`volume`) — no OHLC, no 52-week
  range, no moving averages — despite `yfinance`'s own `fast_info` call
  (already made for every quote) returning `open`/`dayHigh`/`dayLow`/
  `yearHigh`/`yearLow`/`fiftyDayAverage`/`twoHundredDayAverage`/
  `marketCap`/`exchange`/`currency`/`quoteType` for free, live-confirmed
  the same day. Valuation, fundamentals, technical indicators (beyond what
  `fast_info` already gives), macro-series completeness, and analyst
  ratings were confirmed as genuine gaps — no parser touched any of them.
  Portfolio tracking (buy price, cost basis, P&L) was confirmed as
  correctly out of scope, not a gap, per ADR-001.
- **Decision**: widen Axis 2 from 4 tables to 8 (§1). `market_observations`
  gains the full `fast_info` field set at zero additional API cost. Four
  new tables: `instruments` (reference data — sector/industry need
  `Ticker.info`'s slower call, fetched once on monitor-add, not every
  poll), `daily_bars` (adjusted-close OHLCV — the real chart backbone,
  distinct grain from `market_observations`'s ticks), `fundamentals`
  (valuation ratios and reported financials merged into one table — both
  are "a financial snapshot as of a date," not divergent enough to split
  per `s10-05`), `analyst_ratings` (rating-change events, via `yfinance`'s
  `Ticker.upgrades_downgrades` — no new dependency). Technical indicators:
  SMA50/SMA200/52-week hi-lo are already `market_observations` columns
  (free from `fast_info`); only RSI and volatility need real computation,
  done on read from `daily_bars` in `analysis/technical_indicators.py`
  (deterministic, no LLM import, no persisted table — cheap enough over a
  bounded window that persisting would be premature). `monitored_symbols`
  gains a `thesis` text column (a one-line personal note on why a symbol
  is watched) — an annotation, not a position, so it doesn't reopen
  ADR-001. Per-article sentiment tagging and confirming Banxico's exact
  series ids are named as reserved slots (§8), not built now.
- **Consequence**: five new parsers (`instrument_parser.py`,
  `daily_bar_parser.py`, `fundamentals_parser.py`,
  `analyst_ratings_parser.py`, all `yfinance`-only, no new dependency) and
  four new `*_store.py` write sides, all scoped into Phase 9 (`CLAUDE.md`
  §7) rather than built immediately — this ADR records the scoping
  decision, not a completed implementation. `retrieval/sql_retriever.py`
  and the `/analyze` augmentation step (Phase 10-11) will read from all
  eight Axis-2 tables once Phase 9 lands them.
- **Verification (2026-09-10, Phase 9 built and closed)**: implemented in
  full and verified live against a real `pgvector/pgvector:pg16` instance
  with AAPL seeded as a monitored symbol. Four real bugs surfaced and were
  fixed in the process, each recorded in `CLAUDE.md` §7's Phase 9 entry:
  an `.env` inline-comment parsing trap (`python-dotenv` has no delimiter
  between a blank value and a trailing `#` comment), `embed_texts()`
  crashing on a real 10-K's aggregate token count, `yfinance`'s
  `FastInfo.get()` silently returning `None` for several real keys that
  bracket access returns correctly, and `refresh_quotes` never actually
  polling Finnhub because it routed through the yfinance-first fallback
  helper meant for Phase 10's live-read path. Live run produced 1018 real
  `document_chunks` from 25 actual SEC filings, 977 real analyst ratings,
  and a fully populated `market_observations` row — no invented numbers in
  this record.
- **Second verification (2026-09-11)**: real `FINNHUB_API_KEY`/
  `BANXICO_SIE_TOKEN`/`FRED_API_KEY` obtained, `AAPL` + `WALMEX.MX` both
  seeded — the BMV coverage claim exercised for real. Banxico's series ids
  confirmed live (§8's now-resolved item). One more real bug: FRED returns
  a series' entire history with no bound (1823 rows on an unbounded first
  call) — `fetch_fred_series` now takes `observation_start`,
  `refresh_worker.py` passes a 2-year lookback, the same call then landed
  49 rows. Two vendor-behavior findings, not bugs: Yahoo has no
  fundamentals data for `WALMEX.MX` (404, handled, not a crash); Finnhub's
  free tier 403s entirely for non-US-exchange symbols, confirmed by
  calling Finnhub directly — expected, and the reason `yfinance` (not
  Finnhub) is this project's BMV-coverage source.

### ADR-008 — Retrieval layer built (Phase 10); a credential-logging gap found and closed (2026-09-10)

- **Status**: Accepted.
- **Context**: `CLAUDE.md` §7 Phase 10 scoped the retrieval layer
  (`sql_retriever.py`, `hybrid_search.py`, `temporal.py`,
  `vector_retriever.py`) but none of it existed yet — `retrieval/` held
  only a docstring. This ADR records that build and its live verification,
  the same discipline as ADR-007's Phase 9 record.
- **Decision**: implement exactly the (a)-(d) order §2's Axis-3 row
  already specified — hard symbol filter, semantic+lexical run fused by
  RRF (position only), temporal weighting applied last over the fused
  survivors, distance-threshold soft-fail at the close. `temporal.py`
  implements the two-family split literally: news sources get exponential
  half-life decay; `sec_edgar_filings` gets a fixed discount for
  non-latest filings within the same `(symbol, form_type)` group, not a
  smooth decay — the "validity flips" case §2 named but hadn't built.
- **Verification (2026-09-10)**: temporary dev Postgres on port 5433
  (`fantasy-postgres-1` on 5432 confirmed healthy, untouched, before and
  after). Real SEC filings + Finnhub/Yahoo news embedded for `AAPL` (1265
  `document_chunks`); real quotes/daily bars/fundamentals/analyst
  ratings/economic indicators (US + MX) ingested. `vector_retriever.retrieve()`
  run against real embeddings: a paraphrased query correctly soft-failed
  (distance 0.399 > the 0.35 threshold), a near-verbatim query correctly
  cleared it (distance 0.306, Risk Factors chunks ranked top) — the
  soft-fail gate discriminates, confirmed both ways, not asserted from one
  side only. `sql_retriever.py` verified against real rows across every
  table it reads. Full outcome, including three retrieval-layer bugs found
  and fixed live (an unbounded `refresh_filings` SEC pull, a naive/aware
  `datetime` comparison that fix then exposed, and a missing `::vector`
  cast on the semantic-search query parameter), is recorded in `CLAUDE.md`
  §7's Phase 10 entry rather than duplicated here.
- **A fourth finding, credential safety, not retrieval**: `refresh_worker.py`
  sets root logging to INFO, and `httpx`'s request logger propagates to
  root by default; `fetch_fred_series()` sends `FRED_API_KEY` as a query
  parameter (FRED has no header-auth option), so every scheduled poll
  would log the key in plaintext to container logs. A real key was seen in
  a raw log line during this verification pass. **Decision**:
  `refresh_worker.py` now sets `logging.getLogger("httpx").setLevel(logging.WARNING)`
  explicitly — the one process in this codebase that talks to a
  query-param-authenticated API needs to own suppressing that library's
  default verbosity, rather than relying on every future logging
  configuration to remember it. **The operator was advised to rotate the
  exposed `FRED_API_KEY`** as a precaution, independent of the code fix —
  a credential seen in a session transcript is treated as compromised
  regardless of whether the transcript itself leaks further. The key has
  since been rotated (confirmed by the operator, 2026-09-10).

### ADR-009 — Augmentation built (Phase 11); a deliberate `fit_to_budget` deviation from the reference (2026-09-10)

- **Status**: Accepted.
- **Context**: `CLAUDE.md` §7 Phase 11 scoped `POST /analyze` assembling
  both retrieval types into one XML-delimited context, per
  `articles/s09-04` (XML `<source>` delimiters, `reorder_u_pattern`
  edge-loading) and `s11-01` (extractive compression, a composable
  compress→order→fit pipeline). Neither generation (Phase 12) nor the
  confidence gate (Phase 13) exist yet.
- **Decision**: build `app/analysis/augmentation.py` as a pure function —
  no DB or network access of its own, matching `retrieval/*`'s own
  read-only style one layer up. No router built: a `POST /analyze` that
  only returns assembled context, with no analysis behind it, would be a
  half-built endpoint, not this phase's actual deliverable — the router
  is deferred until Phase 12-13 give it something coherent to do. The
  Axis-2 side renders as one deterministic `<market_data>` XML block,
  never compressed or budget-trimmed (it's already typed and terse); the
  Axis-3 side gets `s11-01`'s full pipeline — extractive compression
  (filing-family only), `s09-04`'s corrected `reorder_u_pattern` (not
  `s11-01`'s own broken `insert(0, item)` version — CLAUDE.md's Phase 11
  entry names the bug explicitly, this ADR just confirms it wasn't
  reproduced), then a token-budget fit.
- **A real divergence from the reference, chosen deliberately**: `s09-04`'s
  `truncate_to_token_budget` `break`s on the first chunk that doesn't fit
  — correct only when the input is still sorted by descending relevance.
  `s11-01`'s own `fit_to_budget` runs *after* the edge-loading `order`
  stage, over input that is no longer monotonic by position, and uses a
  **continue**-on-miss loop instead — skip the chunk that doesn't fit,
  keep checking the rest. `augmentation.py`'s `fit_to_budget` follows
  `s11-01`'s version for exactly this reason: with edge-loading applied
  first (per this project's own pipeline order), a `break`-based fit would
  wrongly discard a small, still-fitting chunk that happens to sit
  immediately after a large one. Live-verified with a deliberately tight
  800-token budget against a real 8-chunk retrieved set: 6 dropped, 2
  kept, `augmentation_dropped_chunks` logged — the continue-loop's
  behavior confirmed on real data, not asserted from the synthetic unit
  test alone.
- **`ANALYSIS_CONTEXT_TOKEN_BUDGET` default (12,000, `config.py`)**: not
  `s09-04`'s theoretical 15%-output/5%-overhead ceiling (~102k tokens on
  gpt-4o-mini's 128k window) — this project's actual retrieval breadth
  (`VECTOR_TOP_K=8` per branch, at most ~16 distinct fused chunks) never
  approaches that, so a conservative, explicit default was chosen over
  the theoretical maximum. Configurable, per `s10-01`'s "measurable
  experiment" discipline, not hardcoded.
- **Verification (2026-09-10)**: 13 new tests (compression, both
  `reorder_u_pattern` cases including the 6-item shape, the
  continue-vs-break `fit_to_budget` distinction, market-data XML
  rendering with fields present and absent, full integration); 119
  passing total. Live, on the same temporary-dev-Postgres discipline as
  ADR-008 (`fantasy-postgres-1` confirmed healthy throughout and after
  teardown): a real context assembled for `AAPL` from real `sql_retriever`
  rows and a real `vector_retriever.retrieve()` result — 4,542 tokens,
  nothing dropped at the default budget; re-run at an 800-token budget,
  6 of 8 real chunks correctly dropped and logged. No new bugs found —
  the one notable observation was expected behavior, not a defect:
  `<technical_indicators>` correctly omitted `rsi_14` (needs ≥15 daily
  bars; `refresh_daily_bars` only pulls a 5-day window) while still
  reporting `volatility`/`window_days`, exactly `technical_indicators.py`'s
  intended "insufficient data stays absent, never invented" behavior.

### ADR-010 — Generation built (Phase 12): a domain-transfer decision for the deterministic anchor, and the first real LLM calls (2026-09-10)

- **Status**: Accepted.
- **Context**: `CLAUDE.md` §7 Phase 12 scoped `s11-02`'s two-stage
  synthesis — a deterministic weighted-citation aggregate computed in
  code, then one Instructor-validated generation call that reasons over
  it. `s11-02`'s own reference domain (historical budget estimation)
  weighted-medians a number that exists **in the source text itself**
  (hours). This project's citations — news/filing chunks — carry no such
  number, and ADR-007 already closed the obvious way to manufacture one
  (a per-article LLM sentiment call: "a real cost multiplier for no
  proven benefit over computing stance once, at analysis time").
- **Decision**: `_keyword_lean` (`analysis/synthesis.py`) fills the gap
  the same way `s11-02` fills its own — cheaply and deterministically, not
  with a model call, so it doesn't reopen ADR-007. A small, documented
  bullish/bearish lexicon scores each citation's content in `[-1, 1]`
  purely by word count; `0.0` means no lexicon hit, not "confirmed
  neutral". `combined_weight` uses exactly `CLAUDE.md`'s three named
  signals — `fusion_rank` (0.40), `temporal_weight` (0.35),
  `reliability_tier` (0.25, weighted least because every currently-included
  source already clears ADR-006's quality floor, so it differentiates the
  set less than the other two). `aggregate_evidence` implements `s11-02`'s
  contradiction logic **corrected**, matching the handbook's own editor's
  note on the reference's bug: `strong_low`/`strong_high`/`contested` are
  computed over `weight >= 0.4` citations only, never the full set, so a
  lone weak outlier cannot manufacture a contradiction or widen the range
  the model is told to stay within. `contested` itself uses an absolute
  sign-disagreement threshold (`±0.3`), not `s11-02`'s relative-spread
  formula, which degenerates when the anchor sits near zero — the common
  case for a value that is zero-centered and bounded, unlike always-positive
  hours.
- **A small Phase 10 contract extension, made honest by necessity**:
  computing `fusion_rank` as an independent signal required
  `RetrievalResult` (`vector_retriever.py`) to expose the RRF-fused rank
  **before** temporal re-sorting, as a new `fused_rank` field — reusing the
  final, already-temporally-weighted candidate order would have
  double-counted temporal effects into a signal `CLAUDE.md` treats as
  independent of it. Live-verified via a dedicated regression test: a
  stale-but-semantically-best candidate correctly shows `fused_rank=1`
  even though temporal weighting demotes it in the final candidate order.
- **The first real LLM calls in this project**: `services/llm_service.py`
  uses `instructor.from_litellm(litellm.completion)` — `gpt-4o-mini`
  primary, `claude-haiku-4-5-20251001` fallback on any exception from the
  primary call, matching `CLAUDE.md` §4's stated stack. Both paths were
  live-verified with real API calls, not assumed: a raw `litellm.completion`
  sanity check confirmed the fallback model string actually resolves (a
  genuine risk — `litellm`'s static model registry can lag a model's
  release), and a second run forced the primary call to fail with a
  deliberately invalid key (never a real one) to confirm the fallback
  succeeds through the full `generate_synthesis()`/Instructor retry
  integration, not just bare `litellm`.
- **Verification (2026-09-10)**: 18 new tests (the deterministic aggregate,
  the corrected contradiction logic, prompt rendering against the real
  template files, the LLM client mocked for both the success and fallback
  paths); 137 passing total. Live, same temporary-dev-Postgres discipline
  as ADR-008/009 (`fantasy-postgres-1` confirmed healthy throughout and
  after teardown): the full Phase 10-12 pipeline run against real `AAPL`
  data produced `stance=NEUTRAL` with a rationale that correctly explained
  a real `contested=True` signal (conflicting SEC filing risk-factor
  language) rather than averaging past it, citing two `chunk_id`s
  independently confirmed present in the real retrieved set — no
  hallucinated citation observed, though nothing code-enforces that yet
  (Phase 13). One expected, named limitation observed on real data, not a
  bug: every citation's `_keyword_lean` saturated at exactly `±1.0` in
  this run (SEC "Risk Factors" headers are keyword-dense in one direction
  regardless of whether they disclose anything new), so `contested=True`
  fires often when a filing chunk and a bullish news chunk are retrieved
  together — a known trade-off of a word-matching heuristic, left for
  Phase 17's eval harness to measure rather than patched on a guess.
- **Scoping, matching Phases 10-11's own precedent**: no router, no
  `analyses` table, no persistence built yet. Phase 13's guardrail is what
  computes `quality_status`; persisting a row without one would be a
  half-built feature, not this phase's deliverable.

### ADR-011 — Guardrails built (Phase 13): the confidence gate, a domain-transfer for numeric grounding, and a prose/structure gap found live (2026-09-10)

- **Status**: Accepted.
- **Context**: `CLAUDE.md` §7 Phase 13 scoped `analysis_guard.py` —
  `s11-03`'s referential-integrity check, `s11-04`'s numeric grounding, and
  §2's reliability-tier rule, combined into `confidence` +
  `quality_status`, plus an input-relevance check for execution-shaped
  requests. This is the last phase in the core `/analyze` pipeline (Phase
  14-15 skipped, Phase 16 reserved) — Phases 10-13 together now form a
  complete, tested, live-verified path from a symbol + query to a
  guarded, citation-checked stance.
- **Decision**: `check_input_relevance` matches only imperative execution
  shapes ("buy me 10 shares", "place an order") via a small pattern set,
  deliberately excluding questions about buying ("should I buy AAPL",
  "is AAPL a good buy") — those are legitimate analysis requests this
  system must still answer, not out-of-scope ones. `check_citation_integrity`
  is a direct, undistorted translation of `s11-03` — this check is
  domain-agnostic (a `chunk_id` either was or wasn't in the retrieved
  set), so no adaptation was needed, unlike Phase 12's synthesis anchor.
- **Numeric grounding's domain transfer**: `s11-04`'s reference checks a
  *synthesized* `[low_hours, high_hours]` range against cited sources'
  numeric field, allowing interpolation and flagging extrapolation. This
  project's `AnalysisSynthesis` schema has no structured numeric field at
  all — figures live embedded in free-text `rationale`. `numeric_grounding`
  adapts by extracting `$`/`%`-marked figures from the rationale via
  regex and checking each against a pool of the REAL retrieved SQL values
  (the same ones rendered into Phase 11's `<market_data>` block) — grounded
  iff it matches a real value directly, since nothing is synthesized into
  a range here for interpolation to apply to. Scoped deliberately to `$`
  and `%`-marked figures only, to avoid false positives on bare numbers
  that aren't financial claims (an Item number, "RSI-14"). Percent figures
  are checked against both a field's raw value and its ×100 reading,
  since this project's own ingested data (yfinance, Phase 9) stores some
  ratios as 0-1 fractions and others already percent-scale — a named
  imprecision, not a claim of unit certainty.
- **`retrieval.low_confidence` folded in as a degrading input, not a
  fourth named check**: Phase 10's own soft-fail signal already
  represents exactly the "thin evidence" `s11-04`'s abstention discipline
  warns should lower confidence — re-declaring it as a separate check
  would double-encode the same concept. It contributes to `degraded`
  severity, deliberately never to `insufficient` on its own: forcing
  `NEUTRAL` on thin-but-otherwise-clean evidence (real citations resolve,
  no fabricated figures, reliability rule passes) would be exactly the
  over-abstention `s11-04` names as "declining to do the work," not
  prudence. `insufficient`/forced-`NEUTRAL` is reserved for the three
  conditions `CLAUDE.md` actually names: a fully-dangling citation list, a
  fabricated `$`/`%` figure, or a failed reliability rule.
- **`confidence` reuses Phase 12's own signal**: the mean per-citation
  `weight` (`analysis/synthesis.py`'s `combined_weight`, already computing
  fusion-rank/temporal/reliability) over *resolved* citations only — not a
  new number invented at this layer. This keeps the pipeline's notion of
  "how much does this evidence deserve to be trusted" coherent end to end
  rather than each phase inventing its own confidence formula.
- **Verification (2026-09-10)**: 25 new tests (input relevance including
  the buy-question/buy-command distinction, citation integrity, numeric
  grounding across dollar/percent/economic-indicator pools and the
  no-pool fabrication case, the reliability rule, and full `guard_analysis`
  integration across grounded/degraded/insufficient outcomes); 162
  passing total. Live, same temporary-dev-Postgres discipline as
  ADR-008/009/010 (`fantasy-postgres-1` confirmed healthy throughout and
  after teardown): the full Phase 10-13 pipeline run against real `AAPL`
  data with a real `gpt-4o-mini` call, then guarded — all 3 real citations
  resolved, no fabricated figures, reliability rule passed, landing on
  `degraded` purely from `low_confidence` being true that run, exactly the
  intended behavior, not a failure.
- **A real, live-only finding, fixed on the spot**: the model's free-text
  `rationale` named raw numeric source ids ("sources 370 and 554")
  matching neither its own structured `citations` field nor any real
  retrieved chunk. `guard_analysis` correctly saw nothing wrong — by
  `s11-03`'s own stated design, the structured `citations` field is the
  source of truth and prose is presentation over it — but a reader
  skimming only the rationale would be misled by a number that looks like
  a citation and isn't one. Fixed by tightening `system.j2`'s citation
  rule to explicitly forbid inline numeric source ids in prose;
  re-verified live immediately after on the same query — no raw source
  number appeared in the rationale.
- **Scoping**: still no router, still no `analyses` table or persistence.
  Phases 10-13 now form a complete, independently-tested, independently
  live-verified pipeline (`sql_retriever`/`vector_retriever` →
  `augmentation` → `synthesis` → `llm_service` → `analysis_guard`) with
  no code yet calling all five in sequence outside a verification script
  — wiring that into an actual UI flow plus `analyses`-table persistence
  is left for Phase 18's frontend (Reflex, per ADR-012 — Streamlit at the
  time this ADR was written), or sooner if asked for explicitly, not
  assumed to be this phase's job.

### ADR-012 — Switch frontend from Streamlit to Reflex before Phase 18; drop the separate `api` service (2026-09-11)

- **Status**: Accepted.
- **Context**: before Phase 18 began, the operator asked to explore
  alternatives to Streamlit — wanting a more modern feel and a genuinely
  configurable dashboard with real charting, and naming Streamlit's
  linear-script rerun model and limited layout control as the specific
  frustration. Three alternatives were researched (current as of
  2026-09, not from possibly-stale memory) and presented with an honest
  cost/benefit each:
  - **Plotly Dash**: pure Python, explicit component/callback model (no
    full-script rerun), best native financial charting (candlestick/OHLC
    built in, unlike a Recharts wrapper). Costs: more boilerplate than
    Streamlit or Reflex, and no first-class drag/resize panel layout —
    still needs a community add-on for that.
  - **Reflex**: pure Python, compiles to a real React frontend with an
    async FastAPI backend under the hood. Modern app feel (real
    routing/state, no full-page reruns) without a second language for a
    single-user tool to maintain solo. At comparison time its charting
    looked like the real cost versus Dash — a Recharts wrapper, not
    Plotly-native. **That turned out to be stale once actually
    installed**: `reflex==0.9.11` ships a first-party
    `reflex-components-plotly` package with a dedicated `PlotlyFinance`
    component, confirmed live by importing it and building a real
    `go.Candlestick` figure — Reflex gets genuine Plotly-native
    candlestick/OHLC charting after all, closing most of the gap this
    comparison originally conceded to Dash. Recorded honestly as a
    finding that improved on verification, not assumed correct from
    initial research.
  - **React (Next.js) + Tremor + FastAPI**: the most modern and most
    flexible option — Tremor (free/open-source since Vercel's 2025
    acquisition) is purpose-built for dashboard/KPI/chart components on
    Recharts+Tailwind, and pairing it with `react-grid-layout` gives
    genuine user drag/resize panels, which none of the Python options
    provide natively. Cost: a second stack (TypeScript/React) for a
    single-user personal project to maintain alone, and it would require
    building `routers/*` now — deliberately deferred by every phase since
    Phase 10.
- **Decision**: **Reflex.** For a personal, single-user tool, the modern
  app feel and single-language maintenance burden outweighed Dash's
  stronger native charting and React's superior configurability — both
  real costs, not free upgrades, for a project with exactly one user.
- **A real architecture simplification, not just a framework swap**:
  Reflex's own backend already is a FastAPI app. Its event handlers can
  call `app/*` pipeline modules directly, in-process — there is no need
  for a separate `routers/*` FastAPI layer or `api` docker-compose
  service at all for Phase 18. This is a genuine simplification versus
  the original Streamlit-plus-separate-`api`-service design implied by
  `CLAUDE.md`'s original tree (`docker-compose.yml` listing `api` and
  `streamlit` as distinct services) — one fewer network hop, one fewer
  service to run, for a single-user local deployment that never needed
  a second HTTP consumer in the first place.
- **Consequence**: `streamlit_app.py` and the `streamlit` dependency are
  removed; `frontend/` (a self-contained Reflex project) replaces them.
  `routers/*` stays unbuilt — reserved only for a future second HTTP
  consumer, if one ever appears, not assumed necessary by default.
  `docker-compose.yml`'s `api` service is dropped; `frontend` replaces it.
  §2's layer map, §4's conductor diagram, and §5's request paths are
  updated to describe Reflex event handlers instead of REST routes —
  `GET /api/v1/trending` etc. become `TrendingState.load()` etc., called
  from a page's `on_load`, not from an HTTP client.
- **Verification (2026-09-11)**: two real backend gaps closed first —
  `trending.py`, `analysis_store.py`, and the `analyses` table itself
  were named in the tree since Phase 1 but never built (Phases 10-13
  stayed scoped to the pure pipeline); 12 new tests. `frontend/`'s
  `state.py` + three pages were then compiled and run for real, catching
  five real bugs no amount of reasoning from memory of an earlier Reflex
  version would have surfaced: two separate `DynamicRouteArgShadowsStateVarError`s
  (a dynamic route segment's name is reserved across *every* state, not
  just the page owning the route — even `SymbolState`'s own `symbol`
  field collided with its own page's `[symbol]` segment), an unsupported
  `+` between two dict-subscripted Vars, a `Plotly` component prop that
  actually wants a full `plotly.graph_objs.Figure` rather than the
  data/layout dict pair its prop names suggested, an `UntypedVarError`
  from calling `.length()` on a subscripted `dict` Var (fixed by
  flattening `AnalyzeState.result` into individual typed fields), and a
  cosmetic confidence-display bug ("+50.00%") caught only by looking at
  the rendered page. Driven live with a real headless browser (Playwright
  — `chromium-cli` wasn't available in this environment) against real
  `AAPL` data: dashboard, symbol detail (a real, correctly-colored
  candlestick chart), and a full real `gpt-4o-mini` analyze run with
  persistence and citations, plus the input-relevance guard correctly
  blocking an execution-shaped query. Zero browser console errors.
  `fantasy-postgres-1`'s own daemon (Docker Desktop) was down in this
  environment for unrelated reasons — confirmed via a failed `docker ps`,
  not assumed — so a separate, already-running native `dockerd` was used
  for all verification instead, with zero interaction with
  `fantasy-postgres-1` either way.
- **Docker containerization, attempted ahead of Phase 19-20's own
  scheduled validation**: `frontend/Dockerfile` (Reflex needs Node.js —
  a separate Dockerfile from the root Python-only one) and
  `docker-compose.yml` updated to this ADR's topology, including a new
  one-shot `migrate` service — `frontend` depending only on postgres
  *health* left a real startup race against the schema not existing yet,
  closed via `service_completed_successfully`. One real bug found and
  fixed: Reflex's `bun` installer needs `unzip`, undocumented, surfaced
  only by the container's own `SystemPackageMissingError`. **One real bug
  found and left open, explicitly for Phase 19-20**: dynamic routes
  (`/symbols/[symbol]`) 404 under `reflex run --env prod --single-port`
  in an actual running container (confirmed reproducible; `--single-port`
  is mandatory in prod mode, so there is no separate-ports workaround) —
  static routes (`/`, `/analyze`) serve fine, root cause not yet
  identified. This is a production-container-serving gap, not a defect in
  the UI itself, which is fully built and live-verified via `reflex run`.
  `docker compose up` is not considered validated until this is resolved.

### ADR-013 — Phase 19-20: both open/found frontend bugs root-caused and fixed; local validation complete (2026-09-12)

- **Status**: Accepted.
- **Context**: ADR-012 left one known bug open explicitly for this phase
  (dynamic routes 404 in `reflex run --env prod --single-port`). Running
  the actual `docker compose up` stack for the first time — not just the
  `frontend` image in isolation, as ADR-012's own preview did — surfaced
  a second, more subtle bug that only a full click-through of the user
  journey could have found.
- **Bug 1 root cause (the one ADR-012 left open)**: read directly from
  Reflex's own source (`reflex.utils.exec.get_frontend_mount`) rather
  than guessed. `get_frontend_mount()` mounts the compiled frontend as a
  bare `PrecompressedStaticFiles(..., html=True)` — Starlette's static
  file server, which serves `index.html` only for a directory that
  actually exists on disk. A dynamic route's arbitrary value (`AAPL`,
  `WALMEX.MX`, anything) has no such directory, since react-router's
  static export cannot enumerate every possible value at build time.
  Inspecting a real `reflex export` build's output
  (`.web/build/client/`) confirmed the export process already generates
  `__spa-fallback.html` — a bootable shell built for exactly this case —
  but nothing in Reflex's own serving code ever references that file; an
  unmatched path just gets Starlette's default 404. **Decision**: fix it
  in application code, not by patching Reflex — `frontend/frontend.py`
  now passes `api_transformer=` (Reflex's own documented extension point
  for wrapping the backend ASGI app) a small Starlette instance with one
  explicit `Route("/symbols/{symbol}", ...)` that serves
  `__spa-fallback.html` directly, ahead of the rest of the app being
  mounted at `""`. Scoped to exactly this app's one dynamic route, not a
  blanket catch-all that would mask genuinely bogus paths. Verified live
  twice: a raw `reflex run --env prod --single-port` locally, then again
  through a real `docker compose up`, both via a genuine browser
  navigating directly to the URL (not a client-side link click — the
  harder case, since it forces a fresh server round trip with no
  existing app state).
- **Bug 2, found only by exercising the real compose stack end to end**:
  `dashboard.py`/`symbol_detail.py` triggered their data loads via each
  page's own `on_mount` component prop. `on_mount` is a React
  component-lifecycle hook — it fires when a component is first inserted
  into the DOM, and does **not** refire when react-router keeps the same
  mounted component alive across a later navigation back to its route
  (exactly what an SPA is supposed to do for performance). A symbol added
  to the watchlist from the analyze page therefore never appeared on the
  dashboard without a full hard refresh — invisible in every prior
  single-page check this project had done, since none of them navigated
  away and back within one browser session. **Decision**: moved both to
  `on_load=` at `app.add_page(...)` registration instead —
  `add_page`'s own documented parameter, specifically designed to fire
  on every navigation *to* a route regardless of whether the component
  was already mounted. Verified live: added `AAPL` to monitor from the
  analyze page, navigated back to `/`, saw it appear with real
  price/change data with no manual reload — the exact failure this fix
  closes.
- **Golden-set confirmation, deliberately scoped to what this phase
  itself asks for, not Phase 17's separate harness**: `evals/
  golden_queries.json` and `measure_retrieval.py` remain unbuilt — that
  is Phase 17's own named deliverable, and building it now would be
  scope creep past "phase 19 and 20" as actually requested. The two
  specific properties this phase's own checklist names were instead
  confirmed directly against the live stack: an analysis on a genuinely
  unknown symbol (`ZZZZFAKE`) correctly produced
  `quality_status=insufficient`/`stance=NEUTRAL`/`confidence=0.0` — and,
  more tellingly, did so via the citation-integrity check actually
  firing on a real hallucinated citation (`chunk_id=0`, never retrieved),
  not merely because retrieval happened to be thin. The reliability-tier
  invariant is enforced in code and unit-tested but **honestly not
  independently live-testable today**: every currently-included catalog
  source already scores `reliability_tier >= 4` (ADR-006), so no real
  citation exists that could violate the `>= 3` floor — stated plainly
  rather than staged with synthetic data to fake a live confirmation.
- **A real credential-safety incident, not a code bug, recorded for the
  same reason ADR-008's was**: debugging why a temporary
  `docker-compose.override.yml` port override wasn't taking effect led
  to running `docker compose config` unfiltered, which printed all four
  real secrets (`ANTHROPIC_API_KEY`, `BANXICO_SIE_TOKEN`,
  `FINNHUB_API_KEY`, `FRED_API_KEY`) into the session transcript in
  plaintext. Flagged to the operator immediately; all four were advised
  for rotation. No file or commit was affected — the exposure was a
  transient tool-output stream only — but a credential seen in a
  transcript is treated as compromised regardless of where else it might
  leak, the same posture ADR-008 already established. Carried forward as
  a standing rule: never run a full env/config dump in this repository
  unfiltered, for any reason, including debugging a compose override.
- **`fantasy-postgres-1`, again**: Docker Desktop's daemon was down
  throughout this validation, same as Phases 13/18 — confirmed via a
  failed `docker ps`, not assumed. All work used a separate, native
  `dockerd`, zero interaction with the real Desktop-hosted
  `fantasy-postgres-1` either way. One incidental discovery reported to
  the operator, not acted on: a second, dormant `fantasy-postgres-1`
  container object exists under the native context (state `created`,
  never started, dated three weeks before this session, its own separate
  volume) — left untouched; not this project's concern to clean up.
- **Consequence**: this closes the phase list's core build plan through
  Phase 20. 174 tests passing (both bugs were frontend-only; no backend
  logic changed). Phase 16 (reranking) and Phase 17 (evals) remain the
  two deliberately-unbuilt, explicitly-reserved items — not gaps, named
  choices per their own ADR/§8 entries.
