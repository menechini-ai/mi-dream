# mi-dream

**Sistema Multi-Agente com Memória de Aprendizado Contínuo.**

Um sistema multi-agente cuja memória de longo prazo **aprende com a própria execução**: cada conversa/tarefa gera um `ReasoningTrace`; um pipeline assíncrono converte traces em `Lesson` e depois em `Strategy`; um `Curator` governa a promoção até `ACTIVE` — de onde as estratégias voltam a informar a execução via recall semântico (vetorial). O conhecimento nasce da experiência operacional, não de ingestão de documentos.

---

## Funcionalidades

- **CLI interativa** (REPL) com slash commands, autocomplete e sessões persistentes e resumíveis (`/session <id>`).
- **Memória de raciocínio**: cada troca de mensagem gera um `ReasoningTrace` imutável, PII-sanitizado e com fingerprint de integridade (INV-001).
- **Learning Pipeline assíncrono** (cron/CLI): `Evaluator → Reflector → Distiller → Curator`.
- **Knowledge Graph em Neo4j**: `ReasoningTrace → Lesson → Strategy` com máquina de estados, versionamento (`SUPERSEDES`) e deduplicação.
- **Recall vetorial** (`strategy_embedding`, 1536-d cosine) com fallback por domínio — degradação graciosa nunca bloqueia a execução.
- **Isolamento multi-tenant** via `tenant_id` em todos os nós (scaffold).

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ |
| Orquestração de agentes | `deepagents` (LangGraph) |
| Grafo + vetores | Neo4j 5.26 (Bolt, vector index nativo) |
| Retrieval semântico | `neo4j-graphrag` (`VectorCypherRetriever`) |
| LLM | OpenAI-compatible proxy (`openai` SDK) |
| Embeddings | `text-embedding-3-small` (1536-d) |
| CLI | `typer` + `prompt_toolkit` + `rich` |
| Config | `pydantic-settings` |

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (gerenciador de ambiente)
- Docker (para o Neo4j)
- Endpoint LLM compatível com OpenAI e `LLM_API_KEY`

## Setup

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

## Uso

### REPL (chat interativo)

```bash
uv run mi-dream chat
```

Slash commands dentro do REPL:

| Comando | Ação |
|---|---|
| `/help` | Ajuda |
| `/skills` `/agents` `/commands` | Listas |
| `/session [<id>]` | Cria sessão nova ou resume uma existente |
| `/clear` | Limpa o contexto da sessão |
| `/status` | Health check (Neo4j + LLM) |
| `/exit` | Sai (a sessão é salva com seu ID) |

### Learning Pipeline

```bash
uv run mi-dream reflect    # ciclo: Evaluator → Reflector → Lesson
uv run mi-dream distill    # Lessons pendentes → Strategies EXPERIMENTAL
uv run mi-dream curator    # governança: integridade, máquina de estados, dedup
```

### Outros

```bash
uv run mi-dream sessions   # lista sessões salvas
uv run mi-dream init       # bootstrap do schema Neo4j
```

## Arquitetura

Dois caminhos independentes por design:

1. **Execution Path** (baixa latência, SLO recall < 500ms P95) — conversa, recall de estratégias, gravação de traces.
2. **Learning Pipeline** (assíncrono) — traces → lessons → strategies → governança; falha aqui nunca bloqueia a execução.

```
ReasoningTrace ──▶ Lesson ──▶ Strategy (EXPERIMENTAL) ──▶ ACTIVE
                        ▲                                  │
                        │            (recall vetorial)     ▼
                      Execução de chat ◀── Supervisor/REPL
```

Documentação completa: [docs/architecture.md](docs/architecture.md) e o [SDD v2.2](docs/superpowers/specs/2026-08-06-multi-agent-learning-system-design.md).

## Testes

```bash
uv run pytest          # suite completa
uv run ruff check src tests
```

Suite: 141 passed / 4 skipped (unitários + integração + load test).

## Estrutura do Projeto

```
src/mi_dream/
├── agents/       # DeepAgents Supervisor + tools (recall_strategy, save_reasoning_trace)
├── cli/          # typer, REPL, sessões, renderer, completer, slash commands
├── knowledge/    # Strategy, Lesson, repository, service, router, vector, distiller, curator
├── learning/     # Evaluator, Reflector, Scheduler
├── llm/          # cliente OpenAI-compatible (ask_llm)
├── memory/       # conexão Neo4j, bootstrap do schema, embeddings, fingerprint de traces
├── security/     # sanitização de PII
├── config.py     # configuração (pydantic-settings)
└── health.py     # health checks
```

## Roadmap

- **Fase 2:** Pattern Miner, Distiller com LLM, Knowledge Librarian (Leiden/compactação), `FailurePattern`/`BestPractice`/`Workflow`, observability.
- **Fase 3:** Capability Graph, cross-tenant, Online Validation, Adaptive Retrieval.
