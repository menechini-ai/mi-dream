# Failure Monitoring (v2.5) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Falhas de LLM (chat, skill, agent, cron) são persistidas como `ReasoningTrace {outcome:"failure"}` com detalhes estruturados e inspecionáveis via `/failures` (REPL) e `mi-dream failures` (CLI). SDD §23.

**Architecture:** `extract_llm_error()` classifica a exceção em `(error_type, message)`; `save_reasoning_trace` grava `error_type`/`error_source` como propriedades do nó; `get_failures()` consulta por filtro; o REPL usa helpers comuns `_ask_llm` + `_trace_outcome` nos 4 caminhos LLM (chat/skill/agent/cron). Falhas não abortam o loop (degradação graciosa) e alimentam o pipeline (Evaluator já pontua `outcome=="failure"` +0.3).

**Tech Stack:** Python 3.11+, Neo4j 5.26 (Bolt), pytest (asyncio_mode=auto), ruff.

## Global Constraints

- Python >= 3.11 (pyproject.toml floor)
- Parameterized Cypher only (INV-001, sem injection)
- Todos os nós carry `tenant_id`
- PII sanitization em todo write (`sanitize()`, §18.2)
- Degradação graciosa: falha de LLM nunca bloqueia o REPL
- `_trace_outcome` nunca levanta
- Linha <= 100 chars (ruff line-length)

---

### Task 1: `extract_llm_error` (llm/client.py)

**Files:**
- Modify: `src/mi_dream/llm/client.py`

**Interfaces:**
- Consumes: exceção de `ask_llm_full`/SDK OpenAI
- Produces: `extract_llm_error(exc) -> tuple[str, str]` (`error_type`, mensagem truncada 300 chars)

- [x] **Step 1: Write the failing test** (`tests/test_llm_client.py`)

```python
def test_extract_llm_error_connection():
    from mi_dream.llm.client import extract_llm_error
    t, m = extract_llm_error(ConnectionError("provider unreachable"))
    assert t == "connection_error"
    assert "unreachable" in m

def test_extract_llm_error_openai_rate_limit():
    from unittest.mock import MagicMock
    from openai import RateLimitError
    from mi_dream.llm.client import extract_llm_error
    exc = RateLimitError("429 too many requests", response=MagicMock(), body={})
    t, m = extract_llm_error(exc)
    assert t == "rate_limit_error"

def test_extract_llm_error_unknown():
    from mi_dream.llm.client import extract_llm_error
    assert extract_llm_error(RuntimeError("weird"))[0] == "unknown_error"

def test_extract_llm_error_truncates_message():
    from mi_dream.llm.client import ERROR_TYPE_MESSAGE_MAX, extract_llm_error
    _, m = extract_llm_error(RuntimeError("x" * 1000))
    assert len(m) <= ERROR_TYPE_MESSAGE_MAX
```

- [x] **Step 2: Run tests to verify they fail**
- [x] **Step 3: Minimal implementation** — `ERROR_TYPE_MESSAGE_MAX = 300`; mapear `APIConnectionError`/`ConnectionError`→`connection_error`, `APITimeoutError`/`TimeoutError`→`timeout_error`, `RateLimitError`→`rate_limit_error`, `AuthenticationError`→`auth_error`, `PermissionDeniedError`→`permission_error`, `APIError`→`api_error`, `ValueError`→`config_error`, resto→`unknown_error`; mensagem `str(exc)` truncada
- [x] **Step 4: Run tests to verify they pass**

---

### Task 2: `save_reasoning_trace` — propriedades `error_type`/`error_source`

**Files:**
- Modify: `src/mi_dream/agents/tools.py`

**Interfaces:**
- Produces: nó `(:ReasoningTrace)` com `error_type` (nullable) e `error_source` (nullable) além de `outcome`

- [x] **Step 1: Write the failing test** (`tests/test_agents_supervisor.py`)

```python
@pytest.mark.asyncio
async def test_save_reasoning_trace_stores_error_props():
    from conftest import make_driver_mock
    mock_session = AsyncMock()
    driver = make_driver_mock(mock_session)
    await save_reasoning_trace(
        "t1", "c",
        {"tenant_id": "default", "outcome": "failure",
         "error_type": "rate_limit_error", "error_source": "skill"},
        driver,
    )
    kwargs = mock_session.run.call_args[1]
    assert kwargs["error_type"] == "rate_limit_error"
    assert kwargs["error_source"] == "skill"
```

- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Minimal implementation** — extrair `metadata.get("error_type")`/`metadata.get("error_source")`, adicionar ao Cypher CREATE e aos params
- [x] **Step 4: Run test to verify it passes**

---

### Task 3: `get_failures` (learning/failure_analyzer.py)

**Files:**
- Create: `src/mi_dream/learning/failure_analyzer.py`

**Interfaces:**
- Consumes: `get_driver()`, `settings`
- Produces: `async get_failures(tenant_id, limit=20, error_type=None, source=None, driver=None) -> list[dict]`
- Fallback de campos ausentes (nós pré-v2.5) via `metadata`; `"unknown"` quando nada disponível

- [x] **Step 1: Write the failing test** (`tests/test_learning_failure_analyzer.py`)

```python
@pytest.mark.asyncio
async def test_get_failures_filters_and_parses():
    from conftest import FakeAsyncIter, make_driver_mock
    from mi_dream.learning.failure_analyzer import get_failures

    session = AsyncMock()
    session.run.return_value = FakeAsyncIter([
        FakeRecord({"id": "t1", "content": "Q: x\nA: [ERROR: boom]",
                    "outcome": "failure", "error_type": "api_error",
                    "error_source": "skill",
                    "metadata": '{"error_message": "boom", "tokens": 9, "source": "skill"}',
                    "created_at": "2026-08-07T10:00:00Z"}),
    ])
    driver = make_driver_mock(session)
    rows = await get_failures("default", limit=20, error_type="api_error",
                              source="skill", driver=driver)
    assert rows[0]["id"] == "t1"
    assert rows[0]["error_type"] == "api_error"
    assert rows[0]["error_message"] == "boom"
    assert rows[0]["source"] == "skill"
    q = session.run.call_args.args[0]
    assert "t.outcome = 'failure'" in q
    assert "$limit" in q

@pytest.mark.asyncio
async def test_get_failures_fallback_for_missing_props():
    # nó sem error_type/error_source → fallback metadata / "unknown"
    ...

@pytest.mark.asyncio
async def test_get_failures_empty_when_no_matches():
    ...
```

- [x] **Step 2: Run tests to verify they fail**
- [x] **Step 3: Minimal implementation** — Cypher paramétrico com `WHERE t.outcome = 'failure' [AND t.error_type = $error_type] [AND t.error_source = $source]`, ORDER BY created_at DESC LIMIT $limit; parse de `metadata` JSON por registro
- [x] **Step 4: Run tests to verify they pass**

---

### Task 4: Renderer + commands

**Files:**
- Modify: `src/mi_dream/cli/renderer.py`, `src/mi_dream/cli/commands.py`

**Interfaces:**
- `render_failures(failures)` → tabela `Quando | Tipo | Source | Erro | Tokens`
- `_handle_skills`/`_handle_agents` passam a usar `load_skills()`/`load_agents()` (remove listas hardcoded)
- `COMMANDS["failures"]` (handler string: "Use /failures in REPL…") + help atualizado

- [x] **Step 1: Write the failing tests** (`tests/test_cli_commands.py`)

```python
def test_skills_uses_loader():
    result = dispatch("skills")
    assert any(s["name"] == "brainstorming" for s in result)  # do .midream/skills

def test_failures_registered():
    assert "failures" in COMMANDS
    assert "failures" in dispatch("help")

def test_all_commands_registered():
    required = [... + "failures"]
```

- [x] **Step 2: Run tests to verify they fail**
- [x] **Step 3: Minimal implementation**
  - `_handle_skills` → `return load_skills()`; `_handle_agents` → `return load_agents()`
  - `_handle_failures(args) -> str` + registro em `COMMANDS`
  - help adiciona `/failures [error_type]`
- [x] **Step 4: Run tests to verify they pass**

---

### Task 5: Instrumentação do REPL

**Files:**
- Modify: `src/mi_dream/cli/repl.py`

**Interfaces:**
- `_ask_llm(system, user, history)` — executor único
- `_trace_outcome(source, name, content, outcome, error_type=None, error_message=None, tokens=0, latency_ms=0.0)` — nunca levanta; incrementa `_traces_since_learn`
- `_run_prompt` e chat regular e cron: try/except com `extract_llm_error` + trace de sucesso/falha
- `_handle_failures(args)` + `elif cmd == "failures"` no loop

- [x] **Step 1: Write the failing tests** (`tests/test_cli_repl.py`)

```python
@pytest.mark.asyncio
async def test_run_prompt_success_saves_success_trace(tmp_path):
    # patch ask_llm_full → LLMResponse("oi", total_tokens=10, latency_ms=50)
    # patch save_reasoning_trace (AsyncMock) → metadata outcome == "success",
    #   source == "skill", _traces_since_learn incrementado

@pytest.mark.asyncio
async def test_run_prompt_failure_saves_failure_trace(tmp_path):
    # ask_llm_full levanta ConnectionError → metadata outcome == "failure",
    #   error_type == "connection_error", render_error chamado, sem message assistant

@pytest.mark.asyncio
async def test_chat_failure_persists_and_continues(tmp_path):
    # via run() com fake_prompt ["oi", SystemExit]; ask_llm_full levanta
    # → save_reasoning_trace com outcome "failure"; _traces_since_learn >= 1

@pytest.mark.asyncio
async def test_handle_failures_renders(tmp_path):
    # patch get_failures + render_failures → chamados
```

- [x] **Step 2: Run tests to verify they fail**
- [x] **Step 3: Minimal implementation**
  - helpers `_ask_llm`/`_trace_outcome`
  - `_run_prompt`: try/except + `_trace_outcome`
  - chat regular: try/except + `_trace_outcome` (remove bloco `save_reasoning_trace` inline)
  - cron: try/except + `_trace_outcome(source="cron", name=job.id)`
  - `_handle_failures` + dispatch inline `elif cmd == "failures"`
- [x] **Step 4: Run tests to verify they pass**

---

### Task 6: CLI `failures`

**Files:**
- Modify: `src/mi_dream/cli/app.py`

**Interfaces:**
- `mi-dream failures [--limit N] [--type T] [--source S]`

- [x] **Step 1: Write the failing test** (`tests/test_cli_app.py`) — subcomando registrado e chamada a `get_failures` via typer runner/clize
- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Minimal implementation** — `@app.command() def failures(...)` usando `asyncio.run(get_failures(...))`; imprime linha por falha
- [x] **Step 4: Run test to verify it passes**

---

### Task 7: Suite completa + lint + safety

- [x] **Step 1:** `uv run pytest` → 237 passed, 4 skipped (+19 novos)
- [x] **Step 2:** `uv run ruff check src tests` → All checks passed!
- [x] **Step 3:** `uv run pip-audit` → No known vulnerabilities found
- [x] **Step 4:** Commit

---

## Notas de validação (demo manual)

```bash
uv run mi-dream chat
# LLM down → mensagem de erro + trace de falha salvo
# /failures → tabela com a falha
# /failures rate_limit_error → filtrado
uv run mi-dream failures --limit 10 --source chat
```
