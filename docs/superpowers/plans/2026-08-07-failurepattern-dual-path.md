# FailurePattern Dual-Path (Phase 2a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalizar o caminho negativo de aprendizado (SDD §20.3, §23.7): falhas deixam de ser apenas **monitoramento** e passam a gerar `(:FailurePattern)` — conhecimento negativo de primeira classe — que alimenta o mesmo `StrategyRouter` (recall negativo). O agente passa a receber não só "o que costuma funcionar", mas também "o que historicamente falha neste contexto".

**Architecture:** `FailureAnalyzer` agrega `ReasoningTrace {outcome:"failure"}` em `FailurePattern` (agrupamento determinístico por `error_type` + `domain` + assinatura normalizada, idempotente via `ATTRIBUTED_TO`). O `StrategyRouter.retrieve()` consulta tanto `Strategy` (positivo) quanto `FailurePattern` (negativo) → `ExecutionContext.previous_failures` → seção "Known failure patterns" no system prompt. O ciclo roda dentro de `run_learning_cycle()` como etapa isolada (degradação graciosa). Leiden, LLM authoring e clustering fuzzy ficam adiados (§15) — aqui só clustering determinístico.

**Tech Stack:** Python 3.11+, Neo4j 5.26 (Bolt), pytest (asyncio_mode=auto), ruff.

## Global Constraints

- Python >= 3.11 (pyproject.toml floor)
- Parameterized Cypher only (INV-001, sem injection)
- Todos os nós carry `tenant_id`
- PII sanitization em todo write (`sanitize()`, §18.2)
- Degradação graciosa: falha do pipeline nunca bloqueia execução
- Determinístico na Phase 2a (sem LLM/clustering probabilístico)
- `failure_count` monotonicamente não-decrescente (espelha INV-002a)
- Linha <= 100 chars (ruff)

---

### Task 1: Schema + modelo `FailurePattern`

**Files:**
- Modify: `src/mi_dream/memory/bootstrap.py`, `src/mi_dream/knowledge/models.py`

**Interfaces:**
- Produces: constraint `failure_pattern_id` (UNIQUE em `FailurePattern.id`); dataclasses `FailurePatternCreate`/`FailurePattern`
- Nó: `(:FailurePattern {id, tenant_id, error_type, domain, pattern, failure_count, last_seen, created_at, signature})`

- [ ] **Step 1: Write the failing test** (`tests/test_bootstrap.py`, `tests/test_knowledge_models.py`)

```python
def test_failure_pattern_constraint_in_schema():
    assert "CONSTRAINT failure_pattern_id" in _schema_cypher()

def test_failure_pattern_model():
    fp = FailurePattern(id="fp1", tenant_id="default", error_type="rate_limit_error",
                        domain="general", pattern="Rate limit no provider",
                        failure_count=3, last_seen=datetime.now(UTC))
    assert fp.failure_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** — constraint no `_schema_cypher()`; `FailurePatternCreate` (error_type, domain, pattern, tenant_id) + `FailurePattern` (id, failure_count, last_seen, created_at, signature) espelhando o padrão de `Strategy`
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 2: `FailurePatternRepository`

**Files:**
- Create: `src/mi_dream/knowledge/failure_patterns.py`

**Interfaces:**
- `create(data) -> FailurePattern`
- `get(id) -> FailurePattern | None`
- `list_by_domain(domain, tenant_id) -> list[FailurePattern]`
- `list_by_error_type(error_type, tenant_id) -> list[FailurePattern]`
- `increment(id) -> FailurePattern` — `failure_count += 1`, `last_seen = datetime()` (clamp: nunca decresce)
- `attributed_trace_ids(signature, tenant_id) -> set[str]` — traces já atribuídos a um padrão
- `link_trace(trace_id, pattern_id) -> None` — `MERGE (t)-[:ATTRIBUTED_TO]->(p)`

- [ ] **Step 1: Write the failing tests** (`tests/test_knowledge_failure_patterns.py`) — com session mock (`FakeAsyncIter`/`FakeRecord`)
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** — Cypher paramétrico espelhando `StrategyRepository`; `increment` com clamp `failure_count + CASE WHEN ... `
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 3: `FailureAnalyzer` (agregação determinística)

**Files:**
- Modify: `src/mi_dream/learning/failure_analyzer.py`

**Interfaces:**
- `failure_signature(error_type, domain, message) -> str` — função pura: normaliza (lower, remove pontuação, top-5 palavras > 3 chars), `sha256(...)[:16]`
- `async run_failure_analysis(tenant_id, limit=50) -> dict` — seleciona `ReasoningTrace {outcome:"failure"}` sem `ATTRIBUTED_TO`, agrupa por `(error_type, domain, signature)`, cria/atualiza `FailurePattern` (idempotente) e cria `ATTRIBUTED_TO`
- Retorna `{"failures_processed", "patterns_created", "patterns_updated"}`

- [ ] **Step 1: Write the failing tests** (`tests/test_learning_failure_analyzer.py`)

```python
def test_failure_signature_normalizes():
    sig1 = failure_signature("rate_limit_error", "general", "Too Many Requests 429")
    sig2 = failure_signature("rate_limit_error", "general", "too many requests")
    assert sig1 == sig2

def test_failure_signature_differs_by_error_type():
    assert failure_signature("api_error", "general", "boom") != \
           failure_signature("connection_error", "general", "boom")

@pytest.mark.asyncio
async def test_run_failure_analysis_groups_and_links():
    # 2 traces failure + 1 sucesso → 1 FailurePattern (failure_count=2), 2 ATTRIBUTED_TO
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** — query de traces sem `ATTRIBUTED_TO`, agrupamento em Python por signature, repo create/increment, `link_trace`
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 4: Recall negativo no Router + system prompt

**Files:**
- Modify: `src/mi_dream/knowledge/router.py`, `src/mi_dream/cli/repl.py`

**Interfaces:**
- `StrategyRouter.__init__(..., failure_repo=None)` — opcional; quando presente, `retrieve()` também consulta `FailurePattern` (domain + error_type) e preenche `ExecutionContext.previous_failures`
- `build_system_prompt` ganha seção "Known failure patterns" a partir de `previous_failures`

- [ ] **Step 1: Write the failing tests** (`tests/test_cli_repl.py`, `tests/test_knowledge_router.py`)

```python
def test_build_system_prompt_includes_failure_patterns():
    ctx = ExecutionContext(goal="x", previous_failures=[
        {"error_type": "rate_limit_error", "pattern": "Rate limit no provider"}])
    prompt = build_system_prompt(ctx)
    assert "Known failure patterns" in prompt
    assert "Rate limit" in prompt

@pytest.mark.asyncio
async def test_router_includes_failure_patterns_when_present():
    # failure_repo mockado → previous_failures preenchido; sem failure_repo → []
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** — fallback gracioso (se `failure_repo` ausente ou query falha → `previous_failures=[]`, sem impacto no recall positivo)
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 5: Integração no `run_learning_cycle`

**Files:**
- Modify: `src/mi_dream/learning/scheduler.py`

**Interfaces:**
- `run_learning_cycle` adiciona etapa `failure_analysis` (isolada em try/except, SDD §20.3) entre reflection e distill
- `report["failure_analysis"]` no dict de retorno

- [ ] **Step 1: Write the failing tests** (`tests/test_learning_scheduler.py`)

```python
@pytest.mark.asyncio
async def test_run_learning_cycle_includes_failure_analysis():
    # patch run_failure_analysis → report["failure_analysis"] presente

@pytest.mark.asyncio
async def test_run_learning_cycle_failure_analysis_isolated():
    # run_failure_analysis levanta → report["failure_analysis"]["error"] e distill segue
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** — etapa isolada com `try/except` no padrão existente
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 6: Exposição CLI/REPL

**Files:**
- Modify: `src/mi_dream/cli/app.py`, `src/mi_dream/cli/commands.py`, `src/mi_dream/cli/repl.py`, `src/mi_dream/cli/renderer.py`

**Interfaces:**
- `mi-dream failure-patterns [--limit N] [--type T] [--domain D]` — lista padrões persistidos
- `/patterns [error_type]` no REPL (renderer `render_failure_patterns`)
- `render_failure_patterns(patterns)` — tabela `Tipo | Domínio | Padrão | Contagem | Última`

- [ ] **Step 1: Write the failing tests** (`tests/test_cli_app.py`, `tests/test_cli_commands.py`, `tests/test_cli_repl.py`)
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Minimal implementation** — `FailurePatternRepository.list_by_*` + comando typer; handler `/patterns` inline (async, como `/failures`)
- [ ] **Step 4: Run tests to verify they pass**

---

### Task 7: Suite completa + lint + safety

- [ ] **Step 1:** `uv run pytest` → baseline 237 passed, 4 skipped + novos testes
- [ ] **Step 2:** `uv run ruff check src tests` → All checks passed!
- [ ] **Step 3:** `uv run pip-audit` → No known vulnerabilities found
- [ ] **Step 4:** Commit + push (atualiza PR feat/failure-monitoring → develop)

---

## Fora de escopo (adiados, SDD §15/§23.7)

- **Leiden / community detection** — só com volume real de dados.
- **Clustering fuzzy / LLM authoring** — agrupamento determinístico cobre Phase 2a.
- **Relação `AVOIDS` automática** entre Strategy ↔ FailurePattern (fica Phase 2c; repo pode expor `link_avoids` se necessário).
- **Embedding vetorial em FailurePattern** — recall por domain/error_type nesta fase.

## Notas de validação (demo manual)

```bash
uv run mi-dream learn --once        # roda failure_analysis junto
uv run mi-dream failure-patterns    # lista padrões agregados
# REPL: /patterns; prompt com "Known failure patterns" após recall negativo
```
