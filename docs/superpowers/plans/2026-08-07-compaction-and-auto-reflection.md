# Compaction & Reflexão Automática — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conversas longas são compactadas em `Episode` (memória episódica durável) mantendo o contexto limpo, e o Learning Pipeline roda automaticamente (background no REPL + daemon `mi-dream learn`). Corrigir as lacunas de promoção que impediam o bot de lembrar fatos entre sessões. **v2:** disparo do aprendizado por *contexto* (N traces / estouro do threshold de compactação) + Daily Review diário (stats + integridade + resumo LLM).

**Architecture:** Compactor condensa o contexto via LLM quando excede threshold; o resumo persiste como `(:Episode)` (índice `episode_embedding` já no schema) + `ReasoningTrace` derivado. Recall injeta strategies ACTIVE + `recent_traces` + `episodes` no system prompt. `run_learning_cycle()` orquestra reflect→distill→curator em background; falha nunca bloqueia o chat.

**Tech Stack:** Python 3.11+, Neo4j 5.26 (Bolt), `neo4j-graphrag`, `prompt_toolkit`/`typer` (CLI), pytest (asyncio_mode=auto), ruff.

## Global Constraints

- Python >= 3.11 (pyproject.toml floor)
- Parameterized Cypher only (INV-001, sem injection)
- Todos os nós carry `tenant_id`
- PII sanitization em todo write (`sanitize()`, §18.2)
- Estado da máquina (state machine) validado apenas no Curator
- Degradação graciosa: falha do pipeline nunca bloqueia a execução
- `support_count` monotonicamente não-decrescente (INV-002a)

---

### Task 1: Configuração nova

**Files:**
- Modify: `src/mi_dream/config.py`

**Interfaces:**
- Consumes: `Settings`
- Produces: `settings.refl_interval_minutes`, `settings.compact_threshold_chars`, `settings.compact_keep_recent`

```python
refl_interval_minutes: int = 10
compact_threshold_chars: int = 8000
compact_keep_recent: int = 8
```

- [ ] **Step 1: Write the failing test** (`tests/test_config.py`)

```python
def test_compaction_settings_defaults():
    s = Settings(compact_threshold_chars=4000, compact_keep_recent=4)
    assert s.compact_threshold_chars == 4000
    assert s.compact_keep_recent == 4
    assert s.refl_interval_minutes == 10
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write minimal implementation** (add 3 fields to `Settings`)
- [ ] **Step 4: Run test to verify it passes**

---

### Task 2: Evaluator — bônus para sucesso curto

**Files:**
- Modify: `src/mi_dream/learning/evaluator.py`

**Interfaces:**
- Consumes: `trace` dict
- Produces: `reflection_score` (0..1)

- [ ] **Step 1: Write the failing test** (`tests/test_learning_reflection.py`)

```python
def test_evaluator_short_success_reaches_threshold():
    e = Evaluator()
    trace = {"content": "Q: meu nome é adilson\nA: Prazer, Adilson", "outcome": "success"}
    scored = e.evaluate([trace])
    assert scored[0]["reflection_score"] >= 0.5
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Minimal implementation** — `_score_trace` ganha `if outcome == "success": score += 0.1`
- [ ] **Step 4: Run test to verify it passes**

---

### Task 3: Distiller — seeding de métricas

**Files:**
- Modify: `src/mi_dream/knowledge/distiller.py`

**Interfaces:**
- Consumes: `Lesson`, `StrategyRepository`
- Produces: `Strategy` com `support_count >= 1`, `success_rate` real

- [ ] **Step 1: Write the failing test** (`tests/test_knowledge_distiller.py`)

```python
@pytest.mark.asyncio
async def test_distill_create_seeds_metrics():
    # após _create: update_metrics(id, 1, 1.0) é chamado
    # query "support_count = s.support_count" aparece no fluxo de CREATE
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Minimal implementation**
  - `_create`: após `add_supported_by` → `await self._repo.update_metrics(strategy.id, 1, 1.0)`
  - `_reinforce`: `update_metrics(target.id, 1, 1.0)` (era `target.success_rate`)
- [ ] **Step 4: Run test to verify it passes**

---

### Task 4: Recall de traces + episodes

**Files:**
- Modify: `src/mi_dream/knowledge/router.py`, `src/mi_dream/cli/repl.py`

**Interfaces:**
- Consumes: `AsyncSession`, `StrategyRepository`, `StrategyVectorRetriever`
- Produces: `ExecutionContext` com `recent_traces` e `episodes`; system prompt com histórico

- [ ] **Step 1: Write the failing tests** (`tests/test_knowledge_router.py`, `tests/test_cli_repl.py`)

```python
def test_build_system_prompt_includes_recent_traces():
    ctx = ExecutionContext(goal="x", recent_traces=[{"role": "user", "content": "meu nome é Adilson"}])
    prompt = build_system_prompt(ctx)
    assert "Recent conversation history" in prompt
    assert "Adilson" in prompt

def test_build_system_prompt_includes_episodes():
    ctx = ExecutionContext(goal="x", episodes=[{"summary": "Usuário se chama Adilson"}])
    prompt = build_system_prompt(ctx)
    assert "Prior session summary" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation**
  - `router.py`: `recent_traces: list[dict]`, `episodes: list[dict]` em `ExecutionContext`
  - `repl.py::recall_context`: query `MATCH (t:ReasoningTrace {tenant_id}) RETURN ... ORDER BY created_at DESC LIMIT 20` + `MATCH (e:Episode {tenant_id}) RETURN ... ORDER BY created_at DESC LIMIT 5`
  - `repl.py::build_system_prompt`: seções "Recent conversation history" e "Prior session summary"
  - Passar `StrategyVectorRetriever()` ao `StrategyRouter` (fix RCA-6)
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 5: Compactor (`learning/compactor.py`)

**Files:**
- Create: `src/mi_dream/learning/compactor.py`

**Interfaces:**
- Consumes: `ask_llm_full`, `get_driver`, `build_embedder`, `sanitize`
- Produces: `compact()` → lista de mensagens; `persist_episode()` → `(:Episode)` + `ReasoningTrace`

- [ ] **Step 1: Write the failing tests** (`tests/test_learning_compactor.py`)

```python
async def test_compact_truncates_and_preserves_recent():
    c = ConversationCompactor()
    with patch("mi_dream.learning.compactor.ask_llm_full", return_value=...):
        result = await c.compact(msgs, threshold_chars=100, keep_recent=2)
    assert len(result) == 3  # summary + 2 recent
    assert result[0]["role"] == "system"

async def test_persist_episode_creates_episode_and_trace():
    # verifica Cypher CREATE (:Episode) e CREATE (:ReasoningTrace) com sanitize
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** (summary prompt preserva fatos; sanitize no resumo)
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 6: `run_learning_cycle` + auto-learn

**Files:**
- Create/Modify: `src/mi_dream/learning/scheduler.py`, `src/mi_dream/cli/app.py`, `src/mi_dream/cli/repl.py`

**Interfaces:**
- Consumes: `ReflectionScheduler`, `KnowledgeDistiller`, `Curator`
- Produces: dict de resultados por etapa

- [ ] **Step 1: Write the failing tests** (`tests/test_learning_scheduler.py`, `tests/test_cli_app.py`)
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation**
  - `run_learning_cycle()`: reflect → distill (embedder) → curator (state machine + integrity + dedup + promote); cada etapa em `try/except`
  - `app.py`: comando `learn` (daemon loop, intervalo `-i/--interval-minutes`, `--once` para ciclo único)
  - `repl.py`: background task `_auto_learn()` (intervalo `refl_interval_minutes`) + ciclo no `/exit` + `/learn`
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 7: Session resume + `/compact` + `/learn`

**Files:**
- Modify: `src/mi_dream/cli/repl.py`, `src/mi_dream/cli/commands.py`

**Interfaces:**
- Consumes: `SessionManager`, `ConversationCompactor`
- Produces: sessão resumida preservada; `/compact`; `/learn`

- [ ] **Step 1: Write the failing tests** (`tests/test_cli_repl.py`, `tests/test_cli_repl_unit.py`)
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation**
  - `repl.py::run`: só cria sessão nova se a atual estiver vazia (preserva resume do `app.py chat --session`)
  - `/session <id>` no REPL chama `self._session_mgr.resume(args)`
  - `/compact` força compactação + persist Episode
  - `/learn` roda um ciclo de aprendizado
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 8: Suite completa + lint + safety

- [x] **Step 1:** `uv run pytest` → 212 passed, 4 skipped
- [x] **Step 2:** `uv run ruff check src tests` → All checks passed!
- [x] **Step 3:** safety scan → `pip-audit` instalado como dev dep; "No known vulnerabilities found" (mi-dream local não está no PyPI, esperado)
- [ ] **Step 4:** Commit

---

### Task 9: Config — gatilhos por contexto + Daily Review

**Files:**
- Modify: `src/mi_dream/config.py`

**Interfaces:**
- Produces: `settings.learn_trace_threshold` (auto-learn a cada N traces), `settings.daily_review_hour` (hora fixa do Daily Review, 0-23)

```python
learn_trace_threshold: int = 10
daily_review_hour: int = 8
```

- [x] **Step 1:** Write the failing test (`tests/test_config.py`): defaults `learn_trace_threshold == 10`, `daily_review_hour == 8`
- [x] **Step 2:** Add fields to `Settings`
- [x] **Step 3:** Test passes

### Task 10: DailyReviewer (learning/reviewer.py)

**Files:**
- Create: `src/mi_dream/learning/reviewer.py`

**Design:** Revisão diária com stats de produção (traces/episodes/lessons de hoje, strategies por estado, promovidas hoje), health do pipeline (traces não processados, lessons pendentes, candidatos a promoção `support_count>=3 AND success_rate>=0.6`), integridade via `Curator.run_integrity_checks`, resumo narrativo via LLM, e persistência de `(:DailyReview {date, report, tenant_id, created_at})`.

**Interfaces:**
- `class DailyReviewer(session, use_llm=True)` → `async review(tenant_id) -> dict`
- `async run_daily_review(tenant_id=None) -> dict` (module function, `get_driver()`)
- `async reviewed_dates(tenant_id=None) -> set[str]` (datas já revisadas no grafo)
- `daily_review_due(now_hour, reviewed_dates, today) -> bool` (função pura p/ scheduler)

- [x] **Step 1:** Write failing tests (`tests/test_learning_reviewer.py`): coleta de stats, violações de integridade, resumo LLM (on/off), persistência de DailyReview, `run_daily_review` via driver, `daily_review_due` + `reviewed_dates`
- [x] **Step 2:** Implement module
- [x] **Step 3:** Tests pass

### Task 11: Gatilhos por contexto no REPL + /review + CLI review

**Files:**
- Modify: `src/mi_dream/cli/repl.py`, `src/mi_dream/cli/app.py`, `src/mi_dream/cli/commands.py`

**Design:** Após salvar o trace no loop: (a) se contexto >= `compact_threshold_chars` → auto-compact + persist Episode + `run_learning_cycle`; (b) se `_traces_since_learn >= learn_trace_threshold` → `run_learning_cycle` e reset. Mantém `_auto_learn` por tempo como fallback. Novo `_daily_review` task: ao iniciar, se `now.hour >= daily_review_hour` e hoje não revisado (seed via `reviewed_dates()`), roda `run_daily_review`; depois checa a cada 60min. Comandos `/review` (REPL) e `mi-dream review [--once]` (CLI).

- [x] **Step 1:** Write failing tests (`tests/test_cli_repl.py`, `tests/test_cli_app.py`): auto-compact em threshold, auto-learn em N traces, `/review`, help inclui `review`
- [x] **Step 2:** Implement REPL handlers + background tasks + CLI command + COMMANDS registry
- [x] **Step 3:** Tests pass

### Task 12: Suite completa + lint + safety

- [x] **Step 1:** `uv run pytest` → 224 passed, 4 skipped
- [x] **Step 2:** `uv run ruff check src tests` → All checks passed!
- [x] **Step 3:** `uv run pip-audit` → No known vulnerabilities found
- [ ] **Step 4:** Commit

---

## Notas de validação (demo manual)

```bash
uv run mi-dream chat
# "meu nome é Adilson" → sai → volta
# "qual o meu nome ?"  → deve responder "Adilson" via recent_traces
uv run mi-dream learn          # daemon de reflexão (tempo)
uv run mi-dream review --once  # Daily Review imediato
# conversa longa → auto-compact + learn automático (gatilho por contexto)
```
