# Phase 1 Remediation + SDD Completion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the existing mi-dream Phase 1 + CLI codebase (already written, never committed, suite never ran) and complete the SDD-mandated gaps: real DeepAgents Supervisor, Execution Context wiring in the REPL, governance/pipeline CLI commands, and a green test + lint baseline.

**Baseline findings (review of `docs/superpowers/`):**
- SDD v2.1 (`2026-08-06-multi-agent-learning-system-design.md`) + two plans (`phase1-implementation`, `cli-implementation`).
- All source exists under `src/`; **zero commits**; `.superpowers/.../progress.md` all "pending".
- Dev deps (pytest, ruff, respx) were not installed; the suite had 18 failing tests (most were pre-existing plan/test bugs plus real breakage).

**Approved decisions (user):**
1. Reflector: keep LLM synthesis + **heuristic fallback** (deterministic, offline-safe); LLM call via `asyncio.to_thread`.
2. DeepAgents: real integration using `deepagents 0.7.5` (`create_deep_agent`) + `langchain-openai` `ChatOpenAI` pointed at the OpenAI-compatible proxy in `.env`.
3. `test_real_llm.py`: keep, fix imports/asserts, gated by a connectivity/empty-response skip fixture.

**Global Constraints (from SDD + Phase 1 plan):**
- Parameterized Cypher only; ReasoningTrace immutable (INV-001).
- PII sanitized on all trace writes (§18.2).
- Graceful degradation: pipeline/Router offline → plan from scratch, never block execution (§13).
- State machine transitions validated in Curator, never in agents.
- `tenant_id` scaffold on all knowledge nodes (multi-tenant Fase 2).

---

## Task 1: Documentation + Baseline (DONE)

- [x] **Step 1:** Create this plan and the task ledger (`.superpowers/sdd/2026-08-06-phase1-remediation/`).
- [x] **Step 2:** Install dev deps: `uv sync --extra dev` (pytest 9, pytest-asyncio 1.4, ruff 0.16, respx).
- [x] **Step 3:** Add `langchain-openai>=0.2` to `pyproject.toml` + `uv sync`.
- [x] **Step 4:** Run baseline suite → documented failures (18).

## Task 2: Stabilization Bug Fixes (DONE)

- [x] `src/mi_dream/llm/client.py` — add `chat()` alias of `ask_llm` (CLI/test compat).
- [x] `src/mi_dream/learning/reflector.py` — LLM via `asyncio.to_thread`; **heuristic fallback** `_synthesize_heuristic` on any LLM error; `_build_lesson` shared.
- [x] `src/mi_dream/knowledge/curator.py` — dedup now redirects `SUPPORTED_BY` (fixed type) + `DETACH DELETE`; removed invalid `MERGE ... TYPE(r)` dynamic rel-type.
- [x] `src/mi_dream/agents/tools.py` — `save_reasoning_trace` sanitizes content (SDD §18.2).
- [x] `src/mi_dream/knowledge/repository.py` — remove unused `datetime` import + dead `now`.
- [x] `src/mi_dream/cli/commands.py` — `/status` removed from help text (live REPL command, not registry).
- [x] `src/mi_dream/memory/bootstrap.py` — **add missing imports** (`settings`, `get_driver`); module was broken at runtime.

## Task 3: Test Suite Stabilization (DONE)

- [x] `tests/conftest.py` — autouse fixture resets the `_driver` singleton between tests; helpers `mock_async_cm()` / `make_driver_mock()` (correct async-CM mocking pattern).
- [x] `tests/test_learning_reflection.py` — async Reflector tests; deterministic via fallback (patch `ask_llm` to raise) + LLM-path and invalid-JSON cases.
- [x] `tests/test_phase1_flow.py` — await `reflector.reflect`; heuristic fallback path.
- [x] `tests/test_real_llm.py` — `llm_available` module fixture (skip if no key / unreachable / empty response); fixed lesson ids (`lesson-t-real-1` etc.).
- [x] `tests/test_cli_app.py` — mock `REPL.run` returns a real coroutine for `asyncio.run`.
- [x] `tests/test_cli_repl.py`, `tests/integration/test_cli_integration.py` — `CompleteEvent()` (prompt_toolkit 3.0.53 API).
- [x] `tests/test_cli_session.py` — save after each `create` in `test_list_sessions`.
- [x] `tests/test_curator.py` — `run_state_machine` mock uses `single.side_effect` per query.
- [x] `tests/test_health.py` — `make_driver_mock`; patch `mi_dream.llm.client.get_client`.
- [x] `tests/test_memory_connection.py` — `close_driver` uses `side_effect` two drivers; bootstrap uses `make_driver_mock`.
- [x] `tests/test_agents_supervisor.py` — `make_driver_mock`; added PII-sanitization test for `save_reasoning_trace`.
- [x] `tests/test_knowledge_router.py` — keyword-arg assertion for `list_by_domain`.
- [x] **Verify:** `pytest tests/ -q` → **83 passed, 4 skipped** (real_llm skips while provider returns empty).

## Task 4: DeepAgents Supervisor Real (SDD §6)

**Files:**
- Modify: `src/mi_dream/knowledge/router.py` (add `ExecutionContext.to_dict()` / `to_json()`)
- Modify: `src/mi_dream/agents/tools.py` (tool factories with dep injection)
- Rewrite: `src/mi_dream/agents/supervisor.py`
- Test: `tests/test_agents_supervisor.py`

**Interfaces:**
- `make_recall_strategy_tool(tenant_id) -> BaseTool` — opens own session, `StrategyRouter(retrieve)`, returns JSON `ExecutionContext`; graceful degradation → empty context on error.
- `make_save_reasoning_trace_tool(tenant_id) -> BaseTool` — persists sanitized trace.
- `create_supervisor(task_description, tenant_id="default")` — `ChatOpenAI(model, base_url, api_key)` from settings; `create_deep_agent(model, tools, system_prompt, subagents=[Research])`; Research sub-agent via `GeneralPurposeSubagentProfile`.

- [ ] **Step 1:** Write failing tests (patch `create_deep_agent`; assert tool factories call router/driver correctly).
- [ ] **Step 2:** Run tests → FAIL.
- [ ] **Step 3:** Implement per interfaces above.
- [ ] **Step 4:** Run `pytest tests/test_agents_supervisor.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: real DeepAgents supervisor with recall_strategy + save_reasoning_trace tools`.

## Task 5: Execution Context in REPL (SDD §6 / §8)

**Files:**
- Modify: `src/mi_dream/cli/repl.py`

**Interfaces:**
- Before LLM call: `recall_strategy(goal, context, tenant_id)` → inject retrieved strategies into system prompt.
- After reply: `save_reasoning_trace(...)` with sanitized content.
- **Graceful degradation** (§13): any Router/Neo4j error → continue with empty context, never block chat.

- [ ] **Step 1:** Write/extend test for the new REPL flow helper (pure function for building the system prompt from `ExecutionContext`).
- [ ] **Step 2:** Run test → FAIL.
- [ ] **Step 3:** Implement wiring in `repl.py`.
- [ ] **Step 4:** Run `pytest tests/test_cli_repl.py tests/integration/test_cli_integration.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: wire Execution Context (recall/save) into chat REPL`.

## Task 6: Governance + Pipeline CLI Commands (SDD §9/§10/§14)

**Files:**
- Modify: `src/mi_dream/learning/scheduler.py` (async-safe: `asyncio.to_thread` for `reflect`)
- Modify: `src/mi_dream/cli/app.py`
- Test: `tests/test_cli_app.py`

**Interfaces (typer commands):**
- `mi-dream init` → `bootstrap_schema()` (Neo4j constraints + vector indexes).
- `mi-dream reflect` → one `ReflectionScheduler.run_cycle()`.
- `mi-dream curator --tenant default` → `run_integrity_checks` + `run_state_machine` + `deduplicate`; print report.

- [ ] **Step 1:** Failing tests for new commands (patch modules; `CliRunner`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest tests/test_cli_app.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: init/reflect/curator CLI commands`.

## Task 7: Lint + Final Validation

- [ ] **Step 1:** Fix remaining `ruff check src/ tests/` violations (baseline ~87, mostly unused imports in tests + line length).
- [ ] **Step 2:** `ruff check src/ tests/` → clean.
- [ ] **Step 3:** `pytest tests/ -q` → all pass (4 skipped real-LLM while proxy empty).
- [ ] **Step 4:** Smoke: `mi-dream --help`; `mi-dream init` (if Neo4j up); `mi-dream chat -s test` + Ctrl+C clean (no `asyncio.run` error).
- [ ] **Step 5:** Update `.superpowers/.../progress.md` ledger; mark tasks in this plan.
- [ ] **Step 6:** Commit final `chore: lint clean + docs`.

---

## Self-Review

**SDD coverage after plan:**
- §4 Domains: bootstrap schema (Task 2) ✓
- §6 Execution Components: real Supervisor + tools + Execution Context (Tasks 4-5) ✓
- §8 Fluxo: Reflection pipeline (Task 6) ✓
- §9 Responsibilities: Curator/Router/Librarian scaffolding (Tasks 2, 6) ✓
- §10 State Machine: models + Curator (Task 2) ✓
- §13 NFRs: graceful degradation (Tasks 4-5) ✓
- §18 Security: PII sanitize on writes (Task 2), tenant scaffold ✓

**Open items (Phase 2+, not in scope):**
- Knowledge Librarian (Leiden, compaction), Pattern Miner, formal Lesson node, vector-embedding generation, Langfuse/OTel, ACL multi-tenant.
