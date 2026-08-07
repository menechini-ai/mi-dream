<h1 align="center">MI Dream</h1>

<p align="center">
  <strong>Multi-Agent System with Continuous Learning Memory.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/graph-Neo4j-4581c3?logo=neo4j&logoColor=white" alt="Neo4j"/>
  <img src="https://img.shields.io/badge/tests-218%20passed-green" alt="Tests"/>
</p>

<p align="center">
  <a href="#overview">Overview</a> •
  <a href="#features">Features</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#installation--usage">Installation &amp; Usage</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#commands">Commands</a> •
  <a href="#tests">Tests</a> •
  <a href="#documentation">Documentation</a>
</p>

---

## Overview

A multi-agent system whose long-term memory **learns from its own execution**: every conversation/task generates a `ReasoningTrace`; an async pipeline turns traces into `Lesson` and then into `Strategy`; a `Curator` governs promotion up to `ACTIVE` — from where strategies feed back into execution via semantic (vector) recall. Knowledge is born from operational experience, not from document ingestion.

### What's Inside

| Feature | Description |
|---------|-------------|
| **Interactive CLI** | REPL with slash commands, autocomplete, and persistent resumable sessions (`/session <id>`) |
| **Reasoning Memory** | Every exchange produces an immutable, PII-sanitized `ReasoningTrace` with an integrity fingerprint (INV-001) |
| **Async Learning Pipeline** | `Evaluator → Reflector → Distiller → Curator` (cron/CLI) |
| **Knowledge Graph** | `ReasoningTrace → Lesson → Strategy` with a state machine, versioning (`SUPERSEDES`), and deduplication |
| **Episodic Memory** | Conversation compaction into `Episode` past a threshold — auto-compact + auto-learn driven by context |
| **Daily Review** | Daily stats + integrity checks + LLM narrative summary (`mi-dream review` / `/review`) |
| **Failure Monitoring** | LLM failures persist as failure traces with error type/source, inspectable via `/failures` and `mi-dream failures` |
| **Vector Recall** | `strategy_embedding` (1536-d cosine) with domain fallback — graceful degradation never blocks execution |
| **Multi-Tenant** | Isolation via `tenant_id` on every node (scaffold) |

---

## Features

### 💬 Interactive REPL

- Slash commands with autocomplete; persistent sessions saved as JSON (`/session <id>`)
- **Context-driven auto-learning**: runs `run_learning_cycle()` every `LEARN_TRACE_THRESHOLD` traces
- **Auto-compaction** into `Episode` when the context passes `COMPACT_THRESHOLD_CHARS` (the time interval `REFL_INTERVAL_MINUTES` remains as a fallback)

### 🧠 Reasoning Memory

- Every exchange → immutable `ReasoningTrace`, PII-sanitized (email, phone, SSN, API keys, bearer) before any write
- Integrity fingerprint via `trace_fingerprint()` (deterministic SHA-256, supports INV-001)

### ⚙️ Learning Pipeline

- `Evaluator → Reflector → Distiller → Curator`, each stage isolated in `try/except`
- Failures never block execution — graceful degradation by design
- `ReflectionScheduler.run_cycle()` batches up to 50 traces without a lesson; `run_learning_cycle()` orchestrates reflect → distill → curator

### 🧩 Knowledge Graph

- `ReasoningTrace → Lesson → Strategy` with a state machine (`EXPERIMENTAL → ACTIVE → STALE / SUPERSEDED / DEPRECATED → ARCHIVED`)
- Versioning via `SUPERSEDES`, deduplication, integrity checks
- The `Curator` promotes `EXPERIMENTAL` strategies with `support_count ≥ 3` and `success_rate ≥ 0.6`

### 📦 Episodic Memory

- `ConversationCompactor` summarizes (LLM) and compacts past a character threshold, keeping recent turns verbatim
- `persist_episode()` writes `(:Episode)` plus a derived `ReasoningTrace`

### 📅 Daily Review

- `DailyReviewer`: daily production stats + pipeline health + integrity (`Curator`) + LLM narrative summary
- Idempotent `(:DailyReview {date})` persistence; run via `/review` or `mi-dream review --once`

### 🔍 Vector Recall

- `StrategyVectorRetriever` — async adapter over `neo4j-graphrag`, backed by a 1536-d cosine index
- Domain-based listing fallback when vectors are unavailable

---

## How It Works

```
┌───────────────────────────────────────────────────────────┐
│                      MI Dream Core                         │
├──────────────────────────┬────────────────────────────────┤
│      Execution Path      │   Learning Pipeline (async)     │
│  chat → recall → trace   │   traces → lessons → strategies │
├──────────────────────────┴────────────────────────────────┤
│      cli/app.py · repl.py (unified CLI)                    │
│      chat · reflect · distill · curator · learn · review   │
│      · sessions · init · failures                          │
├────────────────────────────────────────────────────────────┤
│  Memory: Neo4j Bolt + vector index · PII guard · .env      │
└────────────────────────────────────────────────────────────┘
```

### Execution Path (low latency, recall SLO < 500 ms P95)

```
user input
  → add_message + recall strategies (vector recall, domain fallback)
  → ask_llm (system prompt built from the ExecutionContext)
  → save_reasoning_trace (PII-sanitized + integrity fingerprint)
  → auto-learn / auto-compact when thresholds are hit
```

### Learning Pipeline (async)

```
run_learning_cycle()
  → reflect:  un-learned ReasoningTraces (batch of 50) → Evaluator → Reflector → Lesson
  → distill:  pending Lessons → EXPERIMENTAL Strategy (+ SUPPORTED_BY link)
  → curator:  integrity checks → state machine → dedup → promote to ACTIVE
```

---

## Architecture

Two independent paths by design:

1. **Execution Path** (low latency, recall SLO < 500 ms P95) — conversation, strategy recall, trace recording.
2. **Learning Pipeline** (async) — traces → lessons → strategies → governance; failures here never block execution.

```
ReasoningTrace ──▶ Lesson ──▶ Strategy (EXPERIMENTAL) ──▶ ACTIVE
                        ▲                                  │
                        │            (vector recall)       ▼
                      Chat execution ◀── REPL / langchain tools
```

### Core Components

| Component | File | Function |
|-----------|------|----------|
| **CLI Entry** | `cli/app.py` | typer commands: `chat`, `sessions`, `init`, `reflect`, `distill`, `curator`, `learn`, `review` |
| **REPL** | `cli/repl.py` | Interactive loop (`prompt_toolkit`): slash commands, recall before answering, per-message trace, auto-learn/auto-compact, daily-review task |
| **Sessions** | `cli/session.py` | `SessionManager` — persistent JSON sessions (`~/.midream/sessions/*.json`) |
| **Learning** | `learning/scheduler.py` | `ReflectionScheduler.run_cycle()` + `run_learning_cycle()` orchestrator |
| **Compactor** | `learning/compactor.py` | `ConversationCompactor` — summarize + compact + `persist_episode()` |
| **Reviewer** | `learning/reviewer.py` | `DailyReviewer` — daily stats + integrity + LLM summary |
| **Failure Monitor** | `learning/failure_analyzer.py` | `get_failures()` — last failed `ReasoningTrace`s, filterable by type/source |
| **Knowledge** | `knowledge/` | `models`, `repository`, `router`, `vector`, `distiller`, `curator` |
| **Memory** | `memory/` | `connection` (Bolt driver), `bootstrap` (schema), `embeddings`, `reasoning` (fingerprint) |
| **LLM** | `llm/client.py` | `ask_llm_full` / `ask_llm` — OpenAI-compatible chat wrapper |
| **Security** | `security/sanitizer.py` | Regex PII redaction before any trace write |

### Repository Structure

```
src/mi_dream/
├── agents/           # YAML agents (implementation, research, review) + langchain tools
├── cli/              # typer, REPL, sessions, renderer, completer, slash commands, cron, loader
├── knowledge/        # Strategy, Lesson, repository, router, vector, distiller, curator
├── learning/         # Evaluator, Reflector, Scheduler, Compactor, Reviewer, FailureAnalyzer
├── llm/              # OpenAI-compatible client (ask_llm)
├── memory/           # Neo4j connection, schema bootstrap, embeddings, trace fingerprint
├── security/         # PII sanitization
├── skills/           # YAML skills (brainstorming, systematic-debugging, TDD, writing-plans)
├── config.py         # configuration (pydantic-settings)
└── health.py         # health checks
```

---

## Installation & Usage

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (environment manager)
- Docker (for Neo4j)
- An OpenAI-compatible LLM endpoint and `LLM_API_KEY`

### Setup

```bash
# 1. Start Neo4j
docker compose up -d

# 2. Install dependencies (includes dev deps)
uv sync --extra dev

# 3. Configure the environment
cp .env.example .env
#   edit .env: NEO4J_PASSWORD, LLM_API_KEY, etc.

# 4. Bootstrap the schema (constraints + vector indexes)
uv run mi-dream init
```

> **Note:** `uv sync --dev` does not install the dev dependencies in this project — use `uv sync --extra dev`.

### Start Chatting

```bash
uv run mi-dream chat
```

Then just talk — and review the knowledge the conversation keeps building:

> Deploy this service and tell me what you know about K8s debugging.
>
> What strategies does the system already hold?
>
> Run a learning cycle and the daily review.

---

## Configuration

Remote features require a working Neo4j and an OpenAI-compatible LLM endpoint. Configure via `.env` (see `.env.example`). All variables are optional except `NEO4J_PASSWORD` and `LLM_API_KEY`.

### Neo4j

| Variable | Default | Used By |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://localhost:7687` | `memory/connection.py` |
| `NEO4J_USER` | `neo4j` | `memory/connection.py` |
| `NEO4J_PASSWORD` | — | `memory/connection.py` |
| `NEO4J_DATABASE` | `neo4j` | All graph queries |
| `TENANT_ID` | `default` | Knowledge scope on every node |

### LLM & Embeddings

| Variable | Default | Used By |
|----------|---------|---------|
| `LLM_PROVIDER` | `anthropic` | `llm/client.py` |
| `LLM_BASE_URL` | `http://localhost:20128/v1` | `llm/client.py` |
| `LLM_API_KEY` | — | `llm/client.py` (required for chat) |
| `LLM_MODEL` | `claude-sonnet-4-6` | `llm/client.py` |
| `LLM_MAX_TOKENS` | `4096` | `llm/client.py` |
| `LLM_TEMPERATURE` | `0.7` | `llm/client.py` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | `memory/embeddings.py` |
| `EMBEDDING_DIMENSIONS` | `1536` | Schema vector index |
| `EMBEDDING_BASE_URL` | `LLM_BASE_URL` | `memory/embeddings.py` |
| `EMBEDDING_API_KEY` | `LLM_API_KEY` | `memory/embeddings.py` |

### Learning & Runtime

| Variable | Default | Purpose |
|----------|---------|---------|
| `REFL_INTERVAL_MINUTES` | `10` | Auto-cycle interval in the REPL (fallback trigger) |
| `COMPACT_THRESHOLD_CHARS` | `8000` | Context size that triggers compaction |
| `COMPACT_KEEP_RECENT` | `8` | Turns kept verbatim after compaction |
| `LEARN_TRACE_THRESHOLD` | `10` | Traces since the last cycle that trigger auto-learn |
| `DAILY_REVIEW_HOUR` | `8` | Hour (0–23) for the daily review task |
| `VECTOR_TOP_K` | `5` | Top-K for vector recall |
| `SKILLS_DIR` | `.midream/skills` | YAML skills directory |
| `AGENTS_DIR` | `.midream/agents` | YAML agents directory |

### Local Configuration via `.midream/`

The `.midream/` directory holds local CLI configuration and data (gitignored):

| File | Purpose |
|------|---------|
| `agents/*.yaml` | Define specialized agents with `name`, `description`, and `prompt` |
| `skills/*.yaml` | Reusable skills (brainstorming, systematic-debugging, TDD, writing-plans) |
| `cron.json` | Scheduled jobs (`/cron add <interval> "<prompt>"`) |
| `history` | REPL session history |
| `scripts/` | Scripts executable by cron jobs |

Agents and skills are plain YAML — easy to add or customize without touching the code.

---

## Commands

One stable entry point:

```bash
uv run mi-dream <command> [args]
```

### REPL Slash Commands

| Command | Action |
|---------|--------|
| `/help` | Help |
| `/skills` `/agents` `/commands` | Lists |
| `/session [<id>]` | Create a new session or resume an existing one |
| `/clear` | Clear the session context |
| `/compact` | Compact the conversation into a summary (`Episode`) and clean the context |
| `/learn` | Run a learning cycle (reflect → distill → curator) now |
| `/review` | Run the Daily Review (daily stats + integrity + LLM summary) now |
| `/failures [<type>]` | List the last 20 failed LLM calls (optionally filtered by error type) |
| `/status` | Health check (Neo4j + LLM) |
| `/exit` | Exit (the session is saved with its ID) |

### CLI Commands

| Command | What it does |
|---------|--------------|
| `chat` | Start the interactive REPL |
| `sessions` | List saved sessions |
| `init` | Bootstrap the Neo4j schema (constraints + vector indexes) |
| `reflect` | Run a reflection cycle: `Evaluator → Reflector → Lesson` |
| `distill` | Consolidate pending Lessons into `EXPERIMENTAL` Strategies |
| `curator` | Governance: integrity, state machine, dedup |
| `learn` | Daemon: continuous automatic reflection (reflect → distill → curator) |
| `review` | Daily Review (stats + integrity + LLM summary); use `--once` for a single review |
| `failures` | List persisted LLM failures (`--limit`, `--type`, `--source`) |

### Intent Mapping

| You say | MI Dream does |
|---------|---------------|
| Ask a question in the REPL | Recalls relevant strategies, answers, records a `ReasoningTrace` |
| `/compact` | Summarizes the conversation into an `Episode` and resets the context |
| `/learn` | Runs a full learning cycle on pending traces now |
| `/review` | Generates today's stats + integrity report + LLM summary |

---

## Tests

```bash
uv run pytest          # full suite
uv run ruff check src tests
```

Suite: **237 passed / 4 skipped** (unit + integration + load test).

Test coverage includes: sessions, REPL commands, loader/renderer, learning pipeline (reflect/distill/curator), compaction, daily review, knowledge repository/router/vector, trace integrity, security sanitization, memory connection/bootstrap, and health.

---

## Documentation

- **README.md** — this page
- **[README-PT.md](README-PT.md)** — Portuguese (Brazilian) version
- **[docs/architecture.md](docs/architecture.md)** — detailed architecture
- **[SDD v2.4](docs/superpowers/specs/2026-08-06-multi-agent-learning-system-design.md)** — system design document
