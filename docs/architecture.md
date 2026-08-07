# Architecture — mi-dream

**Multi-Agent System with Continuous Learning Memory.**

The system orchestrates LLM agents whose long-term memory **learns from its own execution**: every conversation/task generates a `ReasoningTrace`, an async pipeline turns traces into `Lesson` and then into `Strategy`, and a `Curator` governs promotion up to `ACTIVE` — from where strategies feed back into execution via semantic (vector) recall. Knowledge is born from operational experience, not from document ingestion.

- **Reference design:** [SDD v2.4](../docs/superpowers/specs/2026-08-06-multi-agent-learning-system-design.md)
- **Stack:** Python 3.11+ · Neo4j 5.26 · `neo4j-graphrag` · `langchain-core` tools · OpenAI-compatible proxy

---

## 1. Architectural Overview

```
                          ┌──────────────────────────────┐
                          │            CLI               │
                          │  typer · prompt_toolkit      │
                          │  /chat · /reflect · /distill │
                          │  /curator · /init · /status  │
                          └──────────────┬───────────────┘
                                         │
                       ┌─────────────────┴──────────────────┐
                       ▼                                    ▼
            ┌──────────────────┐                 ┌────────────────────┐
            │   Execution Path │                 │  Learning Pipeline │
            │   (runtime)      │                 │  (async, cron)     │
            │                  │                 │                    │
            │  REPL → ask_llm  │                 │  Evaluator         │
            │  Tools:          │                 │  Reflector (LLM)   │
            │   recall_strategy│                 │  Scheduler (batches)│
            │   save_trace     │                 │  Distiller         │
            │                  │                 │  Curator           │
            │                  │                 │  Reviewer          │
            └────────┬─────────┘                 └─────────┬──────────┘
                     │                                     │
                     ▼                                     ▼
                 ┌──────────────────────────────────────────────┐
                 │                 Neo4j 5.26                    │
                 │  ReasoningTrace · Lesson · Strategy           │
                 │  Episode · DailyReview                        │
                 │  vector index strategy_embedding (1536-d)     │
                 └──────────────────────────────────────────────┘
```

Two independent paths by design:

1. **Execution Path (low latency, recall SLO < 500ms P95)** — conversation, strategy recall, trace recording. Never blocked by learning-pipeline failures.
2. **Learning Pipeline (async, cron/CLI)** — trace degradation → lessons → strategies → governance. Failure here **never** blocks execution (graceful degradation).

---

## 2. Components by Module

### 2.1 `src/mi_dream/config.py`
Central configuration via `pydantic-settings` + `python-dotenv`. Singleton `settings` consumed by every module.

### 2.2 `src/mi_dream/cli/` — Command-line interface
| File | Responsibility |
|---|---|
| `app.py` | typer CLI: `chat`, `sessions`, `init`, `reflect`, `distill`, `curator`, `learn`, `review` |
| `repl.py` | Interactive loop (`prompt_toolkit`): slash commands, recall before answering, per-message trace, sessions |
| `session.py` | `SessionManager` + `new_session_id()` — persistent JSON sessions (`~/.midream/sessions/*.json`) |
| `commands.py` | Slash command registry (`COMMANDS` + `dispatch`) |
| `completer.py` | Slash-command autocomplete in the prompt |
| `renderer.py` | rich output (tables, panels, Markdown, health check) |
| `cron.py` | `CronManager` — scheduled jobs (`/cron add <interval> "<prompt>"`), scripts in `.midream/scripts/` |

### 2.3 `src/mi_dream/agents/` — Agent layer
| File | Responsibility |
|---|---|
| `tools.py` | langchain tools: `recall_strategy` (vector router) and `save_reasoning_trace` (sanitized persistence) |

> **Implementation note:** the REPL interactive chat route calls `ask_llm` directly (with a prompt built from the `ExecutionContext`). The langchain tools in `tools.py` are the multi-agent task harness (SDD §6) and are exercised via `tests/test_agents_supervisor.py`.

### 2.4 `src/mi_dream/knowledge/` — Knowledge Domain
| File | Responsibility |
|---|---|
| `models.py` | Pydantic models: `Strategy`, `StrategyCreate`, `Lesson`, enums `StrategyState`/`CuratorDecision`, `VALID_TRANSITIONS` |
| `repository.py` | `StrategyRepository` — parameterized Cypher CRUD (never string interpolation); promotion/transition/supersession rules live in the Cypher itself |
| `router.py` | `StrategyRouter` + `ExecutionContext` — runtime contract between retrieval and agents |
| `vector.py` | `StrategyVectorRetriever` — **async** adapter over `neo4j-graphrag`'s `VectorCypherRetriever` (sync, runs via `to_thread`) |
| `distiller.py` | `KnowledgeDistiller` — consolidates `Lesson` → EXPERIMENTAL `Strategy` + `SUPPORTED_BY` link (KM-002); seeds `support_count`/`success_rate` on CREATE/REINFORCE |
| `curator.py` | `Curator` — integrity, state machine, dedup, EXPERIMENTAL→ACTIVE promotion, trace immutability |

### 2.5 `src/mi_dream/learning/` — Learning Pipeline
| File | Responsibility |
|---|---|
| `evaluator.py` | `Evaluator` — scores traces for reflection (deterministic heuristic: length, outcome, failure; `+0.1` bonus for `success`) |
| `reflector.py` | `Reflector` — synthesizes `Lesson` via LLM (`ask_llm`); heuristic fallback when the provider fails; drops score < 0.5 |
| `scheduler.py` | `ReflectionScheduler` — cycle: selects traces without a lesson (batch of 50) → evaluates → reflects → creates `Lesson` + `DERIVED_FROM`. `run_learning_cycle()` orchestrates reflect→distill→curator (automatic reflection) |
| `compactor.py` | `ConversationCompactor` — `summarize()` (LLM) + `compact()` (char threshold + keep_recent); `persist_episode()` writes `(:Episode)` + derived `ReasoningTrace` |
| `reviewer.py` | `DailyReviewer` — Daily Review (SDD §22): daily production stats + pipeline health + integrity (`Curator`) + LLM narrative summary; persists `(:DailyReview {date})`. Helpers: `run_daily_review`, `reviewed_dates`, `daily_review_due` |

### 2.6 `src/mi_dream/memory/` — Persistence and Memory
| File | Responsibility |
|---|---|
| `connection.py` | `get_driver()` — async Neo4j (Bolt) driver singleton |
| `bootstrap.py` | `bootstrap_schema()`/`ensure_schema()` — constraints + 1536-d cosine vector indexes; idempotent and process-cached |
| `reasoning.py` | `trace_fingerprint()` — deterministic SHA-256 of the trace payload (supports INV-001) |
| `embeddings.py` | `build_embedder()` — `OpenAIEmbeddings` from `neo4j-graphrag`, reuses the OpenAI-compatible proxy |

### 2.7 `src/mi_dream/llm/client.py`
`get_client()` (OpenAI singleton) + `ask_llm()` — chat call with system/user, run off the event loop via an executor when needed.

### 2.8 `src/mi_dream/health.py`
`check_all()` → `check_neo4j()` + `check_llm_provider()`; used by the REPL `/status`.

### 2.9 `src/mi_dream/security/sanitizer.py`
Regex PII sanitization (email, phone, SSN, API keys, bearer) before any trace write (SDD §18.2). `sanitize()`.

---

## 3. Data Model (Neo4j)

### 3.1 Nodes
| Node | Properties | Created by |
|---|---|---|
| `ReasoningTrace` | `id, content, metadata (JSON string), outcome, content_hash, created_at, tenant_id` | tools/save_reasoning_trace, REPL, Compactor (derived from summary) |
| `Lesson` | `id, summary, decision (CREATE/REINFORCE/REFINE/CONTRADICT), source_trace_ids, confidence, tenant_id, created_at` | ReflectionScheduler |
| `Strategy` | `id, title, description, domain, content, state, support_count, success_rate, created_at, updated_at, tenant_id, superseded_by, embedding (1536-d)` | KnowledgeDistiller |
| `Episode` | `id, summary, content, session_id, tenant_id, created_at, embedding (1536-d)` | ConversationCompactor |
| `DailyReview` | `date, report (JSON string), tenant_id, created_at` | DailyReviewer |

### 3.2 Relationships
| Relationship | Source → Target | Meaning |
|---|---|---|
| `DERIVED_FROM` | `Lesson` → `ReasoningTrace` | the lesson knows its origins |
| `SUPPORTED_BY` | `Lesson` → `Strategy` | lesson supports the strategy (KM-002) |
| `SUPERSEDES` | `Strategy` → `Strategy` | versioning (KM-006) |

### 3.3 Strategy state machine (`VALID_TRANSITIONS`)
```
EXPERIMENTAL ──(support_count≥3, success_rate≥0.6)──▶ ACTIVE
ACTIVE ──(unused 90d)──▶ STALE
STALE ──(reinforced)──▶ ACTIVE       STALE ──(90d+ unused, support<3)──▶ ARCHIVED
ACTIVE ──(better successor)──▶ SUPERSEDED ──(90d+)──▶ ARCHIVED
ACTIVE ──(failed revalidation, no successor)──▶ DEPRECATED   [Phase 3]
```

---

## 4. Execution Flow (Chat)

```
User types / or a message
   │
   ▼
REPL (repl.py:98)
   ├─ slash command → dispatch() / render_*  (skills, agents, help, session, clear, exit, status, compact, learn, review)
   └─ regular message →
        add_message("user", msg)                         → SessionManager (JSON)
        recall_context(msg)                              → StrategyRouter.retrieve()
        │                                                  ├─ vector-first: StrategyVectorRetriever.search(goal, tenant, domain, ACTIVE)
        │                                                  ├─ fallback: list_by_domain(ACTIVE)  [if vector fails/empty]
        │                                                  ├─ recent_traces: latest 20 ReasoningTrace of the tenant
        │                                                  └─ episodes: latest 5 Episode (session summaries)
        build_system_prompt(ctx)                          → injects strategies + recent history + summaries into the system prompt
        ask_llm(system, user)                             → provider (executor thread)
        add_message("assistant", msg) + render            → SessionManager + rich
        save_reasoning_trace(...)                         → Neo4j ReasoningTrace (sanitized, content_hash)
        auto_learn()                                      → context: every LEARN_TRACE_THRESHOLD traces + on /exit
        auto_compact()                                    → if context >= COMPACT_THRESHOLD_CHARS: LLM summary + persist Episode + cycle
        background tasks                                  → _auto_learn (time, fallback) + _daily_review (fixed hour + catch-up)
```

**Graceful degradation:** if Neo4j or the router fails, `recall_context` returns an empty `ExecutionContext` and the chat continues from scratch. A trace-write failure never interrupts the response. A learning-pipeline failure never blocks the chat.

---

## 5. Learning Pipeline

```
ReasoningTrace (append-only, sanitized)
   │  cron: /reflect (ReflectionScheduler.run_cycle)  — batch of up to 50 traces WITHOUT lesson
   ▼
Evaluator.evaluate()      → scores (0..1): content>200ch +0.3, outcome +0.4, failure +0.3, success +0.1
   ▼
Reflector.reflect()       → LLM synthesizes Lesson (decision + confidence); heuristic fallback
   ▼
(Learning:Lesson) + (l)-[:DERIVED_FROM]->(t)          persisted by the scheduler
   │  cron: /distill (KnowledgeDistiller)
   ▼
Distiller                 → CREATE: EXPERIMENTAL Strategy + SUPPORTED_BY + embedding
                            REINFORCE/REFINE: match by title → update_metrics (+1) / create new
                            CONTRADICT: recorded on the Lesson only (no mutation)  [FailurePattern: Phase 2]
   │  cron: /curator (Curator)
   ▼
Curator                   → run_integrity_checks (KM-002, KM-006, INV-001)
                            process_experimental_candidates (EXPERIMENTAL→ACTIVE, INV-002)
                            run_state_machine (STALE/SUPERSEDED/ARCHIVED)
                            deduplicate (merge SUPPORTED_BY + delete duplicate)
   │
   ▼
Strategy ACTIVE  ──▶  available for vector recall (embedding already written at CREATE)
```

> **Recommended operational order:** `reflect` → `distill` → `curator`. The Distiller writes the Strategy embedding at CREATE time (via `build_embedder()`), guaranteeing ACTIVE strategies are reachable by vector recall.

### 5.1 Automatic reflection, context triggers, and Daily Review (v2.4)

- **`run_learning_cycle()`** (`learning/scheduler.py`) orchestrates reflect→distill→curator in a single call; each stage is isolated in `try/except` (a failure never blocks the chat). Run in the background by the REPL (context triggers + every `REFL_INTERVAL_MINUTES` + on `/exit`), by the `mi-dream learn` daemon (infinite loop, `-i/--interval-minutes`, `--once` for a single cycle), and manually via `/learn`.
- **Context triggers (v2.4):** in the REPL, after each turn: (a) if `_traces_since_learn >= LEARN_TRACE_THRESHOLD` → run the cycle; (b) if the context >= `COMPACT_THRESHOLD_CHARS` → auto-compact (`ConversationCompactor`) + persist `(:Episode)` + run the cycle. The time interval remains as a fallback.
- **Compaction** (`learning/compactor.py`): when the session exceeds `COMPACT_THRESHOLD_CHARS`, the `ConversationCompactor` summarizes old turns via LLM (preserving key facts), keeps `COMPACT_KEEP_RECENT` turns verbatim, and persists the summary as `(:Episode)` (with embedding in the `episode_embedding` index) **and** as a derived `ReasoningTrace` — so the compacted summary enters the learning pipeline.
- **Daily Review (v2.4)** (`learning/reviewer.py`): `DailyReviewer` collects daily stats (traces/episodes/lessons/strategies/promoted), pipeline health (unprocessed traces, pending lessons, promotion candidates), integrity via `Curator`, and an LLM narrative summary; persists `(:DailyReview {date, report})`. Runs at a fixed hour with catch-up on start (REPL/daemon), manually via `/review` or `mi-dream review [--once]`.

---

## 6. Vector Recall

`StrategyVectorRetriever` (vector.py) adapts `neo4j-graphrag`'s `VectorCypherRetriever`:

- `strategy_embedding` index (1536-d, cosine) defined at bootstrap.
- Retrieval query (`RETRIEVAL_QUERY`) resolves `superseded_by` via `OPTIONAL MATCH (node)-[:SUPERSEDES]->(succ)` and uses map projection with `.id` (shorthand requires `.`; a key without a dot becomes a variable).
- Search filters: `{tenant_id, state: ACTIVE, domain}`.
- Underlying retriever is **synchronous** → runs via `asyncio.to_thread`.
- **Known workaround:** upstream `neo4j-graphrag` 1.18.0 bug where `_node_embedding_property` is never populated — the adapter copies it from `_embedding_node_property` in `_build()` (vector.py:69).
- `Strategy.score` (cosine similarity) is filled by the retriever; the Router exposes the context via `ExecutionContext.to_json()`.

---

## 7. CLI

### Commands (typer)
| Command | Action |
|---|---|
| `mi-dream chat [-s <session>]` | Interactive REPL (new random or resumed session, resumable) |
| `mi-dream sessions` | List saved sessions |
| `mi-dream init` | Bootstrap the Neo4j schema (constraints + indexes) |
| `mi-dream reflect` | One Evaluator→Reflector→Lesson cycle |
| `mi-dream distill` | Pending lessons → EXPERIMENTAL Strategies |
| `mi-dream curator [--tenant]` | Governance (integrity, state, dedup) |
| `mi-dream learn` | Automatic reflection daemon (infinite loop, `-i/--interval-minutes`; `--once` for a single cycle) |
| `mi-dream review` | Daily Review (stats + integrity + LLM summary; `--once` for a single review; daily daemon without `--once`) |

### Slash commands (REPL)
`/skills` `/agents` `/commands` `/help` `/session [<id>]` `/clear` `/status` `/exit` `/compact` `/learn` `/review`

### Sessions
- `new_session_id()` generates `MMDDHHMM-xxxx` (e.g., `08061257-a1b2`) — resumable with `/session <id>`.
- JSON persistence (`~/.midream/sessions/`); `/session` without args creates a new session.
- The REPL preserves a resumed session (`chat --session`); it only creates a new one if the current session is empty.

---

## 8. Security and Invariants

### Security (SDD §18)
- **PII/Secrets:** `sanitize()` applied before writing any `ReasoningTrace`; `trace_fingerprint` covers the full payload.
- **Tenant:** every node carries `tenant_id`; the Router filters by scope before recall (Neo4j ACL: Phase 2).
- **Injection:** parameterized Cypher only (no string interpolation).
- **Human approval:** promotion to ACTIVE is governed by the Curator (Phase 1 manual; approval workflow: Phase 2).

### Invariants enforced by the Curator
| ID | Rule | Where |
|---|---|---|
| INV-001 / KM-001 | ReasoningTrace immutable (append-only + `content_hash`) | `check_trace_immutability` |
| INV-002 | ACTIVE requires `support_count >= 3` | `process_experimental_candidates` |
| INV-002a | `support_count` monotonically non-decreasing (clamp in Cypher) | `update_metrics` |
| INV-003 | SUPERSEDED points to exactly one successor | `mark_superseded` |
| KM-002 | ACTIVE has ≥ 1 `SUPPORTED_BY` Lesson | `INTEGRITY_CHECKS` |
| KM-006 | `SUPERSEDES` forms a DAG (no cycles) | `INTEGRITY_CHECKS` |

---

## 9. Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Bolt connection |
| `NEO4J_USER` / `NEO4J_PASSWORD` | `neo4j` / — | Credentials |
| `NEO4J_DATABASE` | `neo4j` | Database |
| `TENANT_ID` | `default` | Knowledge scope |
| `REFL_INTERVAL_MINUTES` | `10` | Auto-cycle interval in the REPL (fallback) |
| `COMPACT_THRESHOLD_CHARS` | `8000` | Context size that triggers compaction |
| `COMPACT_KEEP_RECENT` | `8` | Turns kept verbatim after compaction |
| `LEARN_TRACE_THRESHOLD` | `10` | Traces since the last cycle that trigger auto-learn (v2.4) |
| `DAILY_REVIEW_HOUR` | `8` | Hour (0-23) for the daily review (v2.4) |
| `LLM_PROVIDER` | `anthropic` | Provider |
| `LLM_BASE_URL` | `http://localhost:20128/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | — | Key (required for chat) |
| `LLM_MODEL` | `claude-sonnet-4-6` | Model |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature for chat calls |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` | (uses LLM) | Embedding proxy override |

Infra: `docker-compose.yml` starts `neo4j:5.26` with APOC, 1G/512M heaps, and a healthcheck.

---

## 10. Tests

`pytest` (asyncio_mode=auto), `ruff` as linter. 237 passed / 4 skipped.

| Group | Covers |
|---|---|
| `tests/test_*.py` (unit) | config, connection, models, repository, router, vector, curator, distiller, reflection, scheduler, reviewer, security, health, CLI (app, commands, repl, session, renderer, entry) |
| `tests/integration/test_phase1_flow.py` | Phase 1 flow with mocked Neo4j |
| `tests/integration/test_cli_integration.py` | end-to-end REPL (real or mocked Neo4j/LLM) |
| `tests/integration/test_load_chat_learning.py` | chat→context→learning load test (`LOAD_TEST_MESSAGES`=30, `LOAD_TEST_CONCURRENCY`=5) |
| `tests/integration/test_real_llm.py` | real call to the provider |

Commands:
```bash
uv sync --extra dev      # installs deps + dev deps (NOTE: --dev alone does NOT install dev deps)
.venv/bin/python -m pytest          # suite
.venv/bin/ruff check src tests      # lint
```

---

## 11. Roadmap (SDD §15)

- **Phase 1 (current):** langchain tools, Neo4j bolt, Strategy CRUD + state, automatic reflection, deterministic Distiller, Curator, Lesson as a first-class node, vector recall, Episode compaction (v2.3), context triggers + Daily Review (v2.4), failure monitoring (v2.5: `ReasoningTrace {outcome:"failure"}` + `/failures` + `mi-dream failures`).
- **Phase 2:** dual-path Learning Pipeline (Success: Evaluator→Reflector; Failure: FailureAnalyzer→FailurePattern → PatternMiner → Distiller → Curator), Pattern Miner (clustering), LLM Distiller (authoring), Knowledge Librarian (compaction, reindexing) — **Leiden deferred** until real data volume, `BestPractice`/`Workflow`, `VALIDATES`/`CONTRADICTS`/`ABSTRACTS`/`AVOIDS` relationships, observability (Langfuse/OTel).
- **Phase 3:** Capability Graph, cross-tenant, Online Validation (`Validation`, KM-008), Adaptive Retrieval.

---

## 12. Relevant Architecture Decisions (summary)

- **Direct Cypher over Bolt, not hosted NAMS** — required for the Curator (dedup, SUPERSEDES, integrity).
- **Batch reflection (cron), never per isolated episode** — avoids trivial-lesson noise.
- **`metadata` as a JSON string + primitive `outcome`** — Neo4j rejects Map as a property; outcome becomes a property the Evaluator can score.
- **Deterministic Distiller in Phase 1** — the decision already comes from the Reflector; LLM authoring is Phase 2.
- **KM-002 restricted to ACTIVE** — EXPERIMENTAL is born without a supporting lesson by construction.
- **Execution Context as a runtime object**, not from the graph — swapping the Router does not change the agents.
- **`prompt_session`/`sess` with distinct names in the REPL** — avoids the shadowing that broke `prompt_async` (regression fixed).
- **Scheduler in batches of 50** (`LIMIT`) — idempotent cycle (`NOT EXISTS { (:Lesson)-[:DERIVED_FROM]->(t) }`).
- **Leiden deferred** — community detection only after real data volume (hundreds/thousands of Strategies with usage metrics); otherwise operational complexity without measurable benefit (SDD §15, §17).
- **FailurePath as negative knowledge** — `FailurePattern` is not the inverse of `Strategy`; success and failure are distinct signals that feed the same Router (positive + negative recall) (SDD §20.3, §23.7).
