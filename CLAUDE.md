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
| 2 — SQL-retrieval RAG | **Yes — three tables** | `market_observations` (ingested quotes/OHLCV from `yfinance_quotes`/`finnhub_quotes`), `economic_indicators` (official macro series from `banxico_sie`/`fred_economic_data` — **new, ADR-006**), and `analyses` (persisted on-demand analyses). All three name their entities exactly (symbol-or-series-id, timestamp) — no embedding needed for any. `economic_indicators` is its own table, not folded into `market_observations`, per `s10-05`'s schema-divergence rule: a price tick is symbol-keyed, a macro series (Banxico's overnight rate, US CPI) is economy-wide — different entities, not variations of one thing. |
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
│   │   │   ├── quotes_parser.py     # yfinance/finnhub JSON -> intermediate records
│   │   │   ├── edgar_parser.py      # SEC filing HTML -> section-split text
│   │   │   ├── news_parser.py       # Finnhub + yfinance news JSON -> shared RawArticle records
│   │   │   ├── rss_parser.py        # elfinanciero_news + el_economista_news RSS -> RawArticle, keyword-filtered (ADR-006)
│   │   │   └── economic_data_parser.py  # banxico_sie + fred_economic_data JSON -> RawEconomicObservation (ADR-006)
│   │   ├── normalizers/
│   │   │   └── canonical.py         # -> Document(content, metadata), articles/s06-03's contract — news/filing sources only, economic_data_parser feeds SQL directly
│   │   ├── chunking.py              # structural-by-Item for filings (built, Phase 3-4), one-chunk-per-item for news
│   │   ├── embedding.py             # text-embedding-3-small, writes document_chunks with embedding_version + source_hash (s11-05)
│   │   ├── refresh_worker.py        # scheduled loop, per-source cadence from data_catalog.yaml
│   │   ├── observation_store.py     # Axis 2 write side, market_observations
│   │   └── economic_indicator_store.py  # Axis 2 write side, economic_indicators (Phase 9, ADR-006)
│   ├── retrieval/                   # ONLINE pipeline
│   │   ├── sql_retriever.py         # Axis 2 typed reads: observations, economic_indicators, analyses, monitored_symbols
│   │   ├── vector_retriever.py      # Axis 3: hard filter (symbol) -> semantic + lexical search -> RRF fusion -> temporal soft-weight -> threshold/soft-fail
│   │   ├── hybrid_search.py         # tsvector/GIN lexical branch + RRF fusion with the semantic branch (s10-03)
│   │   └── temporal.py              # per-source-family decay/recency weighting (s10-06), applied last, over the survivors only
│   ├── analysis/
│   │   ├── trending.py              # deterministic ranking — NO LLM import
│   │   └── analysis_store.py        # Axis 2: analyses + monitored_symbols read/write
│   ├── prompts/
│   │   └── analyze/v1/{system,user}.j2
│   └── routers/
│       ├── trending.py              # GET /trending
│       ├── symbols.py               # GET /symbols/{symbol}/status, GET /symbols/{symbol}/analyses
│       ├── analyze.py               # POST /analyze
│       └── monitor.py               # GET/POST /monitor, DELETE /monitor/{symbol}
├── migrations/                      # Alembic; market_observations, economic_indicators, analyses, monitored_symbols, document_chunks
├── evals/
│   ├── golden_queries.json          # seeded from README.md §2a; must include an abstention case AND a contradiction case (s11-06)
│   └── measure_retrieval.py         # artisanal precision@k harness (s10-02) — decides IF/WHEN reranking (Phase 16) earns its place
├── tests/
├── streamlit_app.py
├── docker-compose.yml               # postgres(+pgvector), redis, api, streamlit, refresh_worker — all containerized now
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
| Structured market data | `yfinance` (primary, covers BMV via `.MX`), `finnhub` (fallback) | Axis 2; both free/free-tier, no brokerage account |
| Economic data | Banxico SIE (Mexico), FRED (US) | Axis 2; both free, official, token/key registration required — ADR-006, replacing the Investing.com economic-calendar idea |
| Unstructured market data | SEC EDGAR full-text search, Finnhub `/company-news`, Yahoo Finance news (`yfinance`), El Financiero + El Economista RSS (`feedparser`) | Axis 3; see `data_catalog.yaml` for cadence/quality per source. No social/community source of any kind (ADR-006) |
| Embedding model | `text-embedding-3-small` | `PLAYBOOK.md` §4/Axis 3 default; upgrade only against a measured recall gap |
| Chunking | Structural (by filing Item) for `sec_edgar_filings`; one chunk per item for the news sources (already short-form) | `articles/s07-03`/`s07-04`'s per-document-type rule — recursive chunking is overkill for a 2-paragraph news summary |
| Vector index | **None in v1** — sequential scan | Axis 3 default; add `hnsw` only against a measured latency number |
| LLM access | LiteLLM + Instructor, `gpt-4o-mini` primary / a Claude Haiku fallback | `PLAYBOOK.md` §4 default |
| Prompts | Jinja2, versioned (`prompts/analyze/v1/`) | standard convention |
| Structured output | Instructor | `stance` (`BULLISH`/`BEARISH`/`NEUTRAL`) + confidence + rationale + per-claim citations, validated schema |
| Frontend | Streamlit | trending list, symbol detail, analyze form, dashboard |
| Local deployment | `docker compose`: postgres, redis, api, streamlit, **refresh_worker** | All nine sources are plain HTTPS APIs — no host-native deployment constraint this time (contrast the retired TradingView-only architecture) |

## 5. Common commands

```bash
docker compose up --build      # postgres(+pgvector) + redis + api + streamlit + refresh_worker
pytest                         # unit tests — no LLM, embedding, or network calls
streamlit run streamlit_app.py # if run outside compose
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
   single-chunk-per-record for `finnhub_news`/`reddit_mentions` (already
   short-form, recursive chunking adds nothing — `articles/s07-03`).
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
8. **Phase 9 — Freshness, per source — next up.** Three migrations still
   needed (`market_observations`, `economic_indicators`, `monitored_symbols`
   — `document_chunks` already exists from Phase 8) plus
   `economic_indicator_store.py` (Axis 2 write side, mirroring
   `observation_store.py`). `refresh_worker.py` reads each
   `data_catalog.yaml` source's own `refresh.declared` cadence (1-5 min for
   quotes, daily for economic data, hourly for filings, 30 min for the five
   news sources) — one worker, one catalog-driven schedule, dispatching to
   the right parser per `source.name`. Incremental reindexing uses
   `source_hash` to skip unchanged documents (`s11-05`'s `is_stale`
   pattern) — a filing correction re-embeds only that filing, never the
   whole corpus. The live-read path (`FRESHNESS_BUDGET_SECONDS`) stays
   structured-sources-only.
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
10. **Phase 11 — Augmentation**: `POST /analyze` assembles both retrieval
    types into one structured, XML-delimited context (`articles/s09-04`),
    with `s11-01`'s distillation discipline on top: extractive compression
    for `sec_edgar_filings` chunks (keep lines mentioning the symbol/figures
    being asked about — cheap, cannot invent; news/Reddit chunks are
    already short enough to skip compression), **edge-loading the strongest
    evidence at the start and end of the context** using the corrected
    `front + reversed(back)` construction (`s09-04`'s `reorder_u_pattern` —
    s11-01's own naive `insert(0, item)` version is a documented bug that
    inverts the intent, don't reproduce it), and logging every chunk a
    token-budget cutoff drops, not silently truncating.
11. **Phase 12 — Generation**: `s11-02`'s two-stage synthesis, not one
    black-box call — a deterministic aggregate computed in code first
    (a weighted signal per citation from **reliability_tier, temporal
    weight, and fusion rank**, three signals not seven, `s11-02`'s own
    "one sentence to justify each coefficient" discipline; a
    weighted-median anchor; a `contested` flag when *strong* sources
    disagree, not any two sources — a lone Reddit outlier must never read
    as a contradiction), then one Instructor-validated generation call that
    reasons over that precomputed signal rather than inventing it, producing
    `stance`/confidence/rationale/citations with `chunk_id`s from the actual
    retrieved set (`s11-03`).
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
16. **Phase 18** — Streamlit: trending, symbol detail, analyze form
    (showing per-claim citations with their reliability tier and the
    `contested`/`quality_status` flags), dashboard.
17. **Phase 19-20** — local validation (`docker compose up`, golden set,
    confirm no Reddit-only citation ever backs a directional stance and at
    least one golden-set case actually abstains); finalize
    `ARCHITECTURE.md` against what was actually built.
