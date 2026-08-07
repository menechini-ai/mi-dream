# Agent Tools (web + filesystem + shell) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dar ao agente do REPL tools reais (adaptadas do `HKUDS/nanobot` → `nanobot/agent/tools`): `web_search`, `web_fetch`, `read_file`, `list_dir`, `edit_file` e `exec` (opt-in). Hoje nenhuma tool é conectada ao agente (o chat chama `ask_llm_full` numa completion única), e o `web_search` nativo do modelo entrou em loop infinito por falta de guard. Esta mudança introduz um **loop de tool-calls com `max_iterations`** e conecta as tools ao caminho de chat.

**Architecture:**
- `llm/client.py`: `chat_turn(messages, tools=None) -> ChatTurn` — completion com `tools` no schema OpenAI; expõe `tool_calls` tipados.
- `agents/loop.py`: `Toolbox` (registry com schemas + execução) e `run_tool_loop(system, user, history, toolbox, max_iterations=5)` — roda LLM ⇄ tools até não haver `tool_calls` ou estourar o limite (guarda anti-loop). `AgentResult` expõe `.content/.total_tokens/.latency_ms` (compatível com `LLMResponse` do REPL).
- `agents/toolbox.py`: 6 tools com **clients injetáveis** (testáveis sem rede/FS real) e escopo de arquivos sob `tool_workdir` (sem path traversal).
- `cli/repl.py`: o caminho de **chat** usa o tool loop; skills/agents/cron seguem single-shot (inalterados).

**Tech Stack:** Python 3.11+, OpenAI SDK (schema de tools), stdlib (urllib/html.parser), pytest, ruff. Sem deps novas.

## Global Constraints

- Loop limitado por `agent_max_iterations` (default 5) — nunca loop infinito.
- `exec` só liga com `ENABLE_SHELL_TOOL=true` (default off).
- Tools de arquivo: path resolvido dentro de `tool_workdir`; bloqueio de `..`/absoluto fora do escopo.
- Nenhuma tool faz rede/FS em testes (clients injetados e mockados).
- Output truncado (web_fetch `max_chars`, read_file cap, exec cap) — contexto controlado.
- Linha <= 100 chars (ruff).

---

### Task 1: `chat_turn` + `ToolCall` no `llm/client.py`

**Files:** Modify `src/mi_dream/llm/client.py`

**Interfaces:**
- `ToolCall(id, name, arguments)`; `ChatTurn(content, tool_calls, total_tokens, latency_ms)`
- `chat_turn(messages, tools=None, max_tokens=...) -> ChatTurn` — envia `tools` no create; parseia `msg.tool_calls`

- [x] **Step 1: Write failing tests** (`tests/test_llm_client.py`)
- [x] **Step 2: Run to verify fail**
- [x] **Step 3: Minimal implementation** — dataclasses + `chat_turn`
- [x] **Step 4: Run to verify pass**

---

### Task 2: `Toolbox` + `run_tool_loop`

**Files:** Create `src/mi_dream/agents/loop.py`

**Interfaces:**
- `Tool` (name/description/parameters/schema()/run(**kwargs)); `Toolbox` (schemas(), execute(name, args_json))
- `run_tool_loop(system, user, history, toolbox, max_iterations=5) -> AgentResult`
- `AgentResult(content, iterations, tool_calls, total_tokens, latency_ms)`

- [x] **Step 1: Write failing tests** (`tests/test_agents_loop.py`)
- [x] **Step 2: Run to verify fail**
- [x] **Step 3: Minimal implementation** — loop com `asyncio.to_thread(chat_turn, ...)`; append assistant `tool_calls` + tool results; guard `max_iterations`
- [x] **Step 4: Run to verify pass**

---

### Task 3: Tools web — `web_search` + `web_fetch`

**Files:** Create `src/mi_dream/agents/toolbox.py`

**Interfaces:**
- `WebSearchTool(search_fn=None)` — `query`, `count` (1–10); default via DuckDuckGo lite (urllib); retorna `n. title\n url\n snippet`
- `WebFetchTool(fetch_fn=None)` — `url`, `max_chars` (default 50000); extrai texto (strip HTML); cap

- [x] **Step 1: Write failing tests** (`tests/test_agents_toolbox.py`)
- [x] **Step 2: Run to verify fail**
- [x] **Step 3: Minimal implementation** — clients injetáveis, default stdlib, erro gracioso
- [x] **Step 4: Run to verify pass**

---

### Task 4: Tools filesystem — `read_file` / `list_dir` / `edit_file`

**Files:** Modify `src/mi_dream/agents/toolbox.py`

**Interfaces:**
- Escopo: `_safe_resolve(workdir, path)` → bloqueia escape; `read_file(path)`, `list_dir(path=".")`, `edit_file(path, old, new)`

- [x] **Step 1: Write failing tests**
- [x] **Step 2: Run to verify fail**
- [x] **Step 3: Minimal implementation**
- [x] **Step 4: Run to verify pass**

---

### Task 5: Tool `exec` (shell, opt-in)

**Files:** Modify `src/mi_dream/agents/toolbox.py`, `src/mi_dream/config.py`

**Interfaces:**
- `ExecTool(enabled)` — desabilitada → erro explícito; `command`, `timeout` (default 30); `subprocess.run` com cap de output

- [x] **Step 1: Write failing tests**
- [x] **Step 2: Run to verify fail**
- [x] **Step 3: Minimal implementation**
- [x] **Step 4: Run to verify pass**

---

### Task 6: Wiring no REPL (chat) + settings

**Files:** Modify `src/mi_dream/cli/repl.py`, `src/mi_dream/config.py`

**Interfaces:**
- `config`: `agent_max_iterations: int = 5`, `enable_shell_tool: bool = False`, `tool_workdir: str = "."`
- `build_chat_toolbox()` (registra as 6 tools, `exec` só se habilitada)
- Chat path usa `run_tool_loop(system, user, history, toolbox)`

- [x] **Step 1: Write failing tests** — atualizar `test_repl_chat_failure_persists_and_continues` (patch em `run_tool_loop`); novo teste de chat com loop
- [x] **Step 2: Run to verify fail**
- [x] **Step 3: Minimal implementation**
- [x] **Step 4: Run to verify pass**

---

### Task 7: Suite completa + lint + safety

- [x] **Step 1:** `uv run pytest` → 264+ novos testes
- [x] **Step 2:** `uv run ruff check src tests` → All checks passed!
- [x] **Step 3:** `uv run pip-audit` → no known vulnerabilities
- [x] **Step 4:** Commit + push (atualiza PR feat/failure-monitoring → develop)

---

## Fora de escopo (adiados)

- Tools `write_stdin`/`list_exec_sessions` (sessões interativas), `spawn`, `message`, `my`, `cron` (já existe `CronManager`), `generate_image`, `run_cli_app`.
- `web_fetch` com JavaScript/SSR e autenticação.
- Tools nas rotas skills/agents/cron (mantidas single-shot; habilitar depois se desejado).
