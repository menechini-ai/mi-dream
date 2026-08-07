<h1 align="center">MI Dream</h1>

<p align="center">
  <strong>Sistema Multi-Agente com Memória de Aprendizado Contínuo.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/graph-Neo4j-4581c3?logo=neo4j&logoColor=white" alt="Neo4j"/>
  <img src="https://img.shields.io/badge/tests-218%20passed-green" alt="Tests"/>
</p>

<p align="center">
  <a href="#vis%C3%A3o-geral">Visão Geral</a> •
  <a href="#funcionalidades">Funcionalidades</a> •
  <a href="#como-funciona">Como Funciona</a> •
  <a href="#arquitetura">Arquitetura</a> •
  <a href="#instala%C3%A7%C3%A3o-e-uso">Instalação e Uso</a> •
  <a href="#configura%C3%A7%C3%A3o">Configuração</a> •
  <a href="#comandos">Comandos</a> •
  <a href="#testes">Testes</a> •
  <a href="#documenta%C3%A7%C3%A3o">Documentação</a>
</p>

---

## Visão Geral

Um sistema multi-agente cuja memória de longo prazo **aprende com a própria execução**: cada conversa/tarefa gera um `ReasoningTrace`; um pipeline assíncrono converte traces em `Lesson` e depois em `Strategy`; um `Curator` governa a promoção até `ACTIVE` — de onde as estratégias voltam a informar a execução via recall semântico (vetorial). O conhecimento nasce da experiência operacional, não de ingestão de documentos.

### O que há dentro

| Funcionalidade | Descrição |
|---------|-------------|
| **CLI interativa** | REPL com slash commands, autocomplete e sessões persistentes e resumíveis (`/session <id>`) |
| **Memória de raciocínio** | Cada troca gera um `ReasoningTrace` imutável, PII-sanitizado e com fingerprint de integridade (INV-001) |
| **Learning Pipeline assíncrono** | `Evaluator → Reflector → Distiller → Curator` (cron/CLI) |
| **Knowledge Graph** | `ReasoningTrace → Lesson → Strategy` com máquina de estados, versionamento (`SUPERSEDES`) e deduplicação |
| **Memória episódica** | Compactação de conversa em `Episode` acima de um limite — auto-compact + auto-learn acionados por contexto |
| **Daily Review** | Stats do dia + checagens de integridade + resumo narrativo via LLM (`mi-dream review` / `/review`) |
| **Failure Monitoring** | Falhas de LLM viram traces de falha com tipo/fonte do erro, inspecionáveis via `/failures` e `mi-dream failures` |
| **Recall vetorial** | `strategy_embedding` (1536-d cosine) com fallback por domínio — degradação graciosa nunca bloqueia a execução |
| **Multi-tenant** | Isolamento via `tenant_id` em todos os nós (scaffold) |

---

## Funcionalidades

### 💬 REPL interativo

- Slash commands com autocomplete; sessões persistentes salvas em JSON (`/session <id>`)
- **Auto-learning por contexto**: roda `run_learning_cycle()` a cada `LEARN_TRACE_THRESHOLD` traces
- **Auto-compactação** em `Episode` quando o contexto passa de `COMPACT_THRESHOLD_CHARS` (o intervalo por tempo `REFL_INTERVAL_MINUTES` permanece como fallback)

### 🧠 Memória de raciocínio

- Cada troca → `ReasoningTrace` imutável, PII-sanitizado (email, telefone, SSN, API keys, bearer) antes de qualquer gravação
- Fingerprint de integridade via `trace_fingerprint()` (SHA-256 determinístico, suporta INV-001)

### ⚙️ Learning Pipeline

- `Evaluator → Reflector → Distiller → Curator`, cada etapa isolada em `try/except`
- Falhas nunca bloqueiam a execução — degradação graciosa por design
- `ReflectionScheduler.run_cycle()` processa lotes de até 50 traces sem lesson; `run_learning_cycle()` orquestra reflect → distill → curator

### 🧩 Knowledge Graph

- `ReasoningTrace → Lesson → Strategy` com máquina de estados (`EXPERIMENTAL → ACTIVE → STALE / SUPERSEDED / DEPRECATED → ARCHIVED`)
- Versionamento via `SUPERSEDES`, deduplicação, checagens de integridade
- O `Curator` promove strategies `EXPERIMENTAL` com `support_count ≥ 3` e `success_rate ≥ 0.6`

### 📦 Memória episódica

- `ConversationCompactor` resume (LLM) e compacta acima de um limite de caracteres, mantendo as últimas trocas verbatim
- `persist_episode()` grava `(:Episode)` mais um `ReasoningTrace` derivado

### 📅 Daily Review

- `DailyReviewer`: stats diárias de produção + saúde do pipeline + integridade (`Curator`) + resumo narrativo via LLM
- Persistência idempotente `(:DailyReview {date})`; execute via `/review` ou `mi-dream review --once`

### 🔍 Recall vetorial

- `StrategyVectorRetriever` — adaptador assíncrono sobre `neo4j-graphrag`, apoiado em índice 1536-d cosine
- Fallback de listagem por domínio quando vetores não estão disponíveis

---

## Como Funciona

```
┌───────────────────────────────────────────────────────────┐
│                      MI Dream Core                         │
├──────────────────────────┬────────────────────────────────┤
│      Execution Path      │   Learning Pipeline (async)     │
│  chat → recall → trace   │   traces → lessons → strategies │
├──────────────────────────┴────────────────────────────────┤
│      cli/app.py · repl.py (CLI unificada)                  │
│      chat · reflect · distill · curator · learn · review   │
│      · sessions · init · failures                          │
├────────────────────────────────────────────────────────────┤
│  Memória: Neo4j Bolt + vector index · guarda PII · .env    │
└────────────────────────────────────────────────────────────┘
```

### Execution Path (baixa latência, SLO de recall < 500 ms P95)

```
entrada do usuário
  → add_message + recall de strategies (vetorial, fallback por domínio)
  → ask_llm (system prompt montado a partir do ExecutionContext)
  → save_reasoning_trace (PII-sanitizado + fingerprint de integridade)
  → auto-learn / auto-compact quando os limites são atingidos
```

### Learning Pipeline (assíncrono)

```
run_learning_cycle()
  → reflect:  ReasoningTraces sem lesson (lote de 50) → Evaluator → Reflector → Lesson
  → distill:  Lessons pendentes → Strategy EXPERIMENTAL (+ link SUPPORTED_BY)
  → curator:  checagens de integridade → máquina de estados → dedup → promoção para ACTIVE
```

---

## Arquitetura

Dois caminhos independentes por design:

1. **Execution Path** (baixa latência, SLO de recall < 500 ms P95) — conversa, recall de estratégias, gravação de traces.
2. **Learning Pipeline** (assíncrono) — traces → lessons → strategies → governança; falhas aqui nunca bloqueiam a execução.

```
ReasoningTrace ──▶ Lesson ──▶ Strategy (EXPERIMENTAL) ──▶ ACTIVE
                        ▲                                  │
                        │            (recall vetorial)     ▼
                      Execução de chat ◀── REPL / langchain tools
```

### Componentes principais

| Componente | Arquivo | Função |
|-----------|------|----------|
| **CLI Entry** | `cli/app.py` | comandos typer: `chat`, `sessions`, `init`, `reflect`, `distill`, `curator`, `learn`, `review` |
| **REPL** | `cli/repl.py` | Loop interativo (`prompt_toolkit`): slash commands, recall antes de responder, trace por mensagem, auto-learn/auto-compact, task de daily review |
| **Sessions** | `cli/session.py` | `SessionManager` — sessões JSON persistentes (`~/.midream/sessions/*.json`) |
| **Learning** | `learning/scheduler.py` | `ReflectionScheduler.run_cycle()` + orquestrador `run_learning_cycle()` |
| **Compactor** | `learning/compactor.py` | `ConversationCompactor` — resume + compacta + `persist_episode()` |
| **Reviewer** | `learning/reviewer.py` | `DailyReviewer` — stats diárias + integridade + resumo LLM |
| **Failure Monitor** | `learning/failure_analyzer.py` | `get_failures()` — últimas `ReasoningTrace` com falha, filtrável por tipo/fonte |
| **Knowledge** | `knowledge/` | `models`, `repository`, `router`, `vector`, `distiller`, `curator` |
| **Memory** | `memory/` | `connection` (driver Bolt), `bootstrap` (schema), `embeddings`, `reasoning` (fingerprint) |
| **LLM** | `llm/client.py` | `ask_llm_full` / `ask_llm` — wrapper de chat OpenAI-compatible |
| **Security** | `security/sanitizer.py` | Redação de PII por regex antes de qualquer gravação de trace |

### Estrutura do Repositório

```
src/mi_dream/
├── agents/           # Agents YAML (implementation, research, review) + langchain tools
├── cli/              # typer, REPL, sessões, renderer, completer, slash commands, cron, loader
├── knowledge/        # Strategy, Lesson, repository, router, vector, distiller, curator
├── learning/         # Evaluator, Reflector, Scheduler, Compactor, Reviewer, FailureAnalyzer
├── llm/              # cliente OpenAI-compatible (ask_llm)
├── memory/           # conexão Neo4j, bootstrap do schema, embeddings, fingerprint de traces
├── security/         # sanitização de PII
├── skills/           # Skills YAML (brainstorming, systematic-debugging, TDD, writing-plans)
├── config.py         # configuração (pydantic-settings)
└── health.py         # health checks
```

---

## Instalação e Uso

### Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (gerenciador de ambiente)
- Docker (para o Neo4j)
- Um endpoint LLM compatível com OpenAI e `LLM_API_KEY`

### Setup

```bash
# 1. Suba o Neo4j
docker compose up -d

# 2. Instale as dependências (inclui dev deps)
uv sync --extra dev

# 3. Configure o ambiente
cp .env.example .env
#   edite .env: NEO4J_PASSWORD, LLM_API_KEY, etc.

# 4. Bootstrap do schema (constraints + vector indexes)
uv run mi-dream init
```

> **Nota:** `uv sync --dev` não instala as dev dependencies neste projeto — use `uv sync --extra dev`.

### Comece a Conversar

```bash
uv run mi-dream chat
```

Depois é só conversar — e acompanhar o conhecimento que a conversa vai construindo:

> Faça o deploy desse serviço e me diga o que você sabe sobre debugging de K8s.
>
> Que strategies o sistema já possui?
>
> Rode um ciclo de aprendizado e o daily review.

---

## Configuração

Recursos remotos exigem um Neo4j funcionando e um endpoint LLM compatível com OpenAI. Configure via `.env` (veja `.env.example`). Todas as variáveis são opcionais, exceto `NEO4J_PASSWORD` e `LLM_API_KEY`.

### Neo4j

| Variável | Padrão | Usado por |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://localhost:7687` | `memory/connection.py` |
| `NEO4J_USER` | `neo4j` | `memory/connection.py` |
| `NEO4J_PASSWORD` | — | `memory/connection.py` |
| `NEO4J_DATABASE` | `neo4j` | Todas as queries do grafo |
| `TENANT_ID` | `default` | Escopo de conhecimento em todos os nós |

### LLM e Embeddings

| Variável | Padrão | Usado por |
|----------|---------|---------|
| `LLM_PROVIDER` | `anthropic` | `llm/client.py` |
| `LLM_BASE_URL` | `http://localhost:20128/v1` | `llm/client.py` |
| `LLM_API_KEY` | — | `llm/client.py` (obrigatória para o chat) |
| `LLM_MODEL` | `claude-sonnet-4-6` | `llm/client.py` |
| `LLM_MAX_TOKENS` | `4096` | `llm/client.py` |
| `LLM_TEMPERATURE` | `0.7` | `llm/client.py` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | `memory/embeddings.py` |
| `EMBEDDING_DIMENSIONS` | `1536` | Índice vetorial do schema |
| `EMBEDDING_BASE_URL` | `LLM_BASE_URL` | `memory/embeddings.py` |
| `EMBEDDING_API_KEY` | `LLM_API_KEY` | `memory/embeddings.py` |

### Learning e Runtime

| Variável | Padrão | Função |
|----------|---------|---------|
| `REFL_INTERVAL_MINUTES` | `10` | Intervalo de auto-ciclo no REPL (gatilho de fallback) |
| `COMPACT_THRESHOLD_CHARS` | `8000` | Tamanho de contexto que dispara a compactação |
| `COMPACT_KEEP_RECENT` | `8` | Últimas trocas mantidas verbatim após compactar |
| `LEARN_TRACE_THRESHOLD` | `10` | Traces desde o último ciclo que disparam auto-learn |
| `DAILY_REVIEW_HOUR` | `8` | Hora (0–23) da task de daily review |
| `VECTOR_TOP_K` | `5` | Top-K do recall vetorial |
| `SKILLS_DIR` | `.midream/skills` | Diretório de skills YAML |
| `AGENTS_DIR` | `.midream/agents` | Diretório de agents YAML |

### Configuração local via `.midream/`

O diretório `.midream/` guarda configurações e dados locais do CLI (gitignored):

| Arquivo | Função |
|---------|--------|
| `agents/*.yaml` | Definem agents especializados com `name`, `description` e `prompt` |
| `skills/*.yaml` | Skills reutilizáveis (brainstorming, systematic-debugging, TDD, writing-plans) |
| `cron.json` | Jobs agendados (`/cron add <interval> "<prompt>"`) |
| `history` | Histórico de sessões do REPL |
| `scripts/` | Scripts executáveis por cron jobs |

Agents e skills são YAMLs simples — fácil de adicionar ou customizar sem tocar no código.

---

## Comandos

Um único ponto de entrada:

```bash
uv run mi-dream <comando> [args]
```

### Slash Commands do REPL

| Comando | Ação |
|---------|--------|
| `/help` | Ajuda |
| `/skills` `/agents` `/commands` | Listas |
| `/session [<id>]` | Cria sessão nova ou resume uma existente |
| `/clear` | Limpa o contexto da sessão |
| `/compact` | Compacta a conversa num resumo (`Episode`) e limpa o contexto |
| `/learn` | Roda um ciclo de aprendizado (reflect → distill → curator) na hora |
| `/review` | Roda o Daily Review (stats do dia + integridade + resumo LLM) na hora |
| `/failures [<tipo>]` | Lista as últimas 20 falhas de LLM (opcionalmente filtradas por tipo de erro) |
| `/status` | Health check (Neo4j + LLM) |
| `/exit` | Sai (a sessão é salva com seu ID) |

### Comandos CLI

| Comando | O que faz |
|---------|--------------|
| `chat` | Inicia o REPL interativo |
| `sessions` | Lista sessões salvas |
| `init` | Bootstrap do schema Neo4j (constraints + vector indexes) |
| `reflect` | Roda um ciclo de reflexão: `Evaluator → Reflector → Lesson` |
| `distill` | Consolida Lessons pendentes em Strategies `EXPERIMENTAL` |
| `curator` | Governança: integridade, máquina de estados, dedup |
| `learn` | Daemon: reflexão automática contínua (reflect → distill → curator) |
| `review` | Daily Review (stats + integridade + resumo LLM); use `--once` para revisão única |
| `failures` | Lista falhas de LLM persistidas (`--limit`, `--type`, `--source`) |

### Mapa de Intenções

| Você diz | MI Dream faz |
|---------|---------------|
| Faz uma pergunta no REPL | Recupera strategies relevantes, responde, grava um `ReasoningTrace` |
| `/compact` | Resume a conversa num `Episode` e reseta o contexto |
| `/learn` | Roda um ciclo completo de aprendizado nos traces pendentes |
| `/review` | Gera o relatório do dia (stats + integridade + resumo LLM) |

---

## Testes

```bash
uv run pytest          # suite completa
uv run ruff check src tests
```

Suite: **218 passed / 4 skipped** (unitários + integração + load test).

Cobertura inclui: sessões, comandos do REPL, loader/renderer, learning pipeline (reflect/distill/curator), compactação, daily review, knowledge repository/router/vector, integridade de traces, sanitização de segurança, conexão/bootstrap de memória e health.

---

## Documentação

- **README.md** — esta página (em inglês)
- **[README-PT.md](README-PT.md)** — versão em português (Brasil)
- **[docs/architecture.md](docs/architecture.md)** — arquitetura detalhada
- **[SDD v2.4](docs/superpowers/specs/2026-08-06-multi-agent-learning-system-design.md)** — documento de design do sistema
