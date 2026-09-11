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
| Store | PostgreSQL 16 (`pgvector/pgvector:pg16`) | Axis 2's `market_observations`/`economic_indicators`/`analyses`/`monitored_symbols` **and** Axis 3's `document_chunks` — pgvector is now activated |
| Cache | Redis | Freshness-budget cache for live structured-quote reads |
| Structured data | `yfinance` (primary, covers BMV via `.MX`), `finnhub` (fallback) | Axis 2, no brokerage account, both free/free-tier |
| Economic data | Banxico SIE (Mexico), FRED (US) | Axis 2, free/official, token or key registration required — ADR-006 |
| Unstructured data | SEC EDGAR full-text search, Finnhub `/company-news`, Yahoo Finance news (`yfinance`), El Financiero + El Economista RSS (`feedparser`) | Axis 3 — see `data_catalog.yaml` for the per-source cadence/quality record. No social/community source of any kind — ADR-006 |
| Embedding model | `text-embedding-3-small` | `PLAYBOOK.md` §4/Axis 3 default |
| LLM access | LiteLLM (`gpt-4o-mini`, fallback a Claude Haiku model) | One wrapper, cross-provider fallback |
| Frontend | Streamlit | Trending list, symbol detail, analyze form, monitor dashboard |
| Deploy | docker compose (postgres, redis, api, streamlit, **refresh_worker**) | All nine sources are plain HTTPS APIs — everything is containerizable this time |

**Not used, deliberately**: no vector index in v1 (Axis 3's own default —
sequential scan until a measured latency number says otherwise), no agent
orchestration framework (Axis 5 rejected), no ORM beyond what
Alembic/SQLAlchemy needs, no order-execution path of any kind (unchanged
from the second architecture — there is still nothing here that acts), no
social or community content of any kind, ever (ADR-006 — a hard rule, not
merely a Reddit-specific exclusion).

## 1. Architecture decision

**Axis 2 (SQL-retrieval RAG)** covers `market_observations`,
`economic_indicators` (ADR-006), and `analyses`: all three name their
entities exactly (symbol-or-series-id, timestamp), typed columns, no
embedding. `economic_indicators` is a separate table from
`market_observations`, not a variant of it — `articles/s10-05`'s
schema-divergence rule: a price tick is symbol-keyed, a Banxico/FRED series
is economy-wide, and forcing them into one table would mean a `symbol`
column that's `NULL` for every macro row. **Axis 3 (vector RAG) is newly
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
│                              economic_data_parser.py — ADR-006), normalizers/, chunking.py,
│                              embedding.py, refresh_worker.py, observation_store.py,
│                              economic_indicator_store.py (Phase 9, ADR-006)
├── retrieval/       ONLINE: sql_retriever.py (Axis 2), vector_retriever.py (Axis 3, orchestrates the below)
│                     hybrid_search.py — lexical (tsvector/GIN) branch + RRF fusion with semantic
│                     temporal.py — per-source-family decay/recency weighting, applied last
├── analysis/        trending.py — deterministic, NO LLM import
│                     analysis_store.py — Axis 2, analyses + monitored_symbols
├── prompts/         analyze/v1/{system,user}.j2
└── routers/         trending.py, symbols.py, analyze.py, monitor.py — thin HTTP only
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
| `services/llm_service.py` | `config`, `schemas`, `prompts` | `routers` |
| `guardrails/*` | `config`, `schemas` | `routers` |
| `ingest/*` | `config`, `schemas`, `services/market_data.py`, `services/db.py` | `routers`, `guardrails`, `retrieval/*` |
| `retrieval/vector_retriever.py` | `config`, `schemas`, `retrieval/hybrid_search.py`, `retrieval/temporal.py` | `ingest/*` (reads what ingest already wrote, never triggers a fetch), `routers` |
| `retrieval/hybrid_search.py`, `retrieval/temporal.py` | `config`, `schemas` | `ingest/*`, `routers`, each other's caller role — these are called *by* `vector_retriever.py`, not by routers directly |
| `retrieval/sql_retriever.py` | `config`, `schemas` | `ingest/*`, `routers` |
| `analysis/trending.py` | `config`, `schemas` | `services/llm_service.py` — **no LLM import, ever** |
| `analysis/analysis_store.py` | `config`, `schemas` | `routers` |
| `prompts/*` | `schemas` | everything else |
| `routers/*` | anything above | — (holds no business logic) |
| `main.py` | `config`, `routers` | — |

## 4. The conductor

**N/A — Lean tier.** `routers/analyze.py` is the one path that touches both
retrieval types, and it does so directly, in a fixed order:

```
routers/analyze.py
 → retrieval/sql_retriever.py     (recent market_observations + past analyses)
 → retrieval/vector_retriever.py  (top-k document_chunks, threshold + soft-fail)
 → services/llm_service.py        (one generation call over both)
 → guardrails/analysis_guard.py   (validate + reliability-tier rule)
 → analysis/analysis_store.py     (persist)
```

Both retrieval calls always run — nothing routes between them at runtime,
so this is augmentation (`articles/s09-04`), not a conductor. Extract one
only if a second, genuinely cross-capability request appears.

## 5. Request paths

```
GET /api/v1/trending
 1. read monitored_symbols (active=true)                          free
 2. read latest market_observations per symbol                     free
 3. trending.rank() — deterministic % change / volume sort          free

GET /api/v1/symbols/{symbol}/status
 1. market_data live read (cached, FRESHNESS_BUDGET_SECONDS)         free
 2. read recent market_observations for symbol (sparkline)           free

GET /api/v1/symbols/{symbol}/analyses
 1. read analyses history for symbol, newest first                   free

POST /api/v1/analyze
 1. sql_retriever: recent market_observations + relevant                free
    economic_indicators (country-matched: MX symbols get banxico_sie,
    US symbols get fred_economic_data) + past analyses
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
 8. return result (frontend shows "add to monitor")

POST /api/v1/monitor           {symbol, analysis_id?}
 1. upsert monitored_symbols (active=true)                            free

DELETE /api/v1/monitor/{symbol}
 1. set monitored_symbols.active = false                              free

GET /api/v1/monitor
 1. read monitored_symbols (active=true) + latest observation each     free
```

Offline (`ingest/refresh_worker.py`, not a request path): per-source
scheduled loop reading `data_catalog.yaml`'s cadence, running
loader → parser → normalizer → (chunk → embed, for Axis-3 sources) → store.

## 6. Contracts that do not break

- Routes: `/api/v1/trending`, `/api/v1/symbols/{symbol}/status`,
  `/api/v1/symbols/{symbol}/analyses`, `/api/v1/analyze`,
  `/api/v1/monitor` (GET/POST), `/api/v1/monitor/{symbol}` (DELETE),
  `/health`.
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
| A new unstructured **news** source | If it's RSS, `ingest/parsers/rss_parser.py` already handles the shape — just a new `data_catalog.yaml` entry with the feed URL and keyword list. If it needs a real API client, a new `ingest/parsers/*_parser.py` producing `news_parser.RawArticle`. Either way, `axis: vector_rag`, no other code changes needed to activate it. **Never a social/community feed of any kind — that's not a config toggle, it's excluded by policy (ADR-006).** |
| A prompt change | `prompts/analyze/v<N>/` — new version, not an edit |
| A new query pattern over observation/analysis history | `retrieval/sql_retriever.py` |
| A change to chunking/embedding strategy | `ingest/chunking.py` / `ingest/embedding.py`, plus a re-embedding pass (`articles/s11-05`) |
| An HTTP endpoint | `routers/`, thin |

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
- ~~`alpaca-core` / `alpaca-mcp`~~ — deleted (ADR-001).
- ~~`tradingview-mcp-jarp` dependency~~ — dropped (ADR-004).
- ~~`reddit_mentions`~~ — dropped entirely, not merely excluded-with-reason
  (ADR-006). No social/community feed of any kind is a candidate for this
  project going forward — not a per-source decision to revisit.
- ~~`tradingview_community` / `google_finance` / `investing_com_calendar`~~
  — considered and excluded-with-a-written-reason in `data_catalog.yaml`
  (ADR-006); not a reserved slot to reopen without new information (no
  public API exists for any of the three as of 2026-09-10).

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
