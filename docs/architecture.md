# Arquitetura — mi-dream

**Sistema Multi-Agente com Memória de Aprendizado Contínuo.**

O sistema orquestra agentes LLM cuja memória de longo prazo **aprende com a própria execução**: cada conversa/tarefa gera um `ReasoningTrace`, um pipeline assíncrono converte traces em `Lesson` e depois em `Strategy`, e um `Curator` governa a promoção até `ACTIVE` — de onde as estratégias voltam a informar a execução via recall semântico (vetorial). O conhecimento nasce da experiência operacional, não de ingestão de documentos.

- **Design de referência:** [SDD v2.2](../docs/superpowers/specs/2026-08-06-multi-agent-learning-system-design.md)
- **Stack:** Python 3.11+ · Neo4j 5.26 · `deepagents` (LangGraph) · `neo4j-graphrag` · OpenAI-compatible proxy

---

## 1. Visão Arquitetural

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
            │  DeepAgents      │                 │  Reflector (LLM)   │
            │  Supervisor      │                 │  Scheduler (lotes) │
            │  Tools:          │                 │  Distiller         │
            │   recall_strategy│                 │  Curator           │
            │   save_trace     │                 │                    │
            └────────┬─────────┘                 └─────────┬──────────┘
                     │                                     │
                     ▼                                     ▼
                 ┌──────────────────────────────────────────────┐
                 │                 Neo4j 5.26                    │
                 │  ReasoningTrace · Lesson · Strategy           │
                 │  vector index strategy_embedding (1536-d)     │
                 └──────────────────────────────────────────────┘
```

Dois caminhos independentes por design:

1. **Execution Path (baixa latência, SLO recall < 500ms P95)** — conversa, recall de estratégias, gravação de traces. Nunca é bloqueado por falhas do pipeline de aprendizado.
2. **Learning Pipeline (assíncrono, cron/CLI)** — degradação de traces → lessons → strategies → governança. Falha aqui **nunca** bloqueia execução (degradação graciosa).

---

## 2. Componentes por Módulo

### 2.1 `src/mi_dream/config.py`
Configuração central via `pydantic-settings` + `python-dotenv`. Singleton `settings` consumido por todos os módulos.

### 2.2 `src/mi_dream/cli/` — Interface de linha de comando
| Arquivo | Responsabilidade |
|---|---|
| `app.py` | CLI typer: `chat`, `sessions`, `init`, `reflect`, `distill`, `curator` |
| `repl.py` | Loop interativo (`prompt_toolkit`): slash commands, recall antes de responder, grava trace por mensagem, sessões |
| `session.py` | `SessionManager` + `new_session_id()` — sessões persistentes em JSON (`~/.mi-dream/sessions/*.json`) |
| `commands.py` | Registro de slash commands (`COMMANDS` + `dispatch`) |
| `completer.py` | Autocomplete de `/comandos` no prompt |
| `renderer.py` | Saída rich (tabelas, painéis, Markdown, health check) |

### 2.3 `src/mi_dream/agents/` — Camada de agentes (DeepAgents)
| Arquivo | Responsabilidade |
|---|---|
| `supervisor.py` | `create_supervisor()` — grafo DeepAgents: Supervisor + sub-agent `research`, com prompt que obriga `recall_strategy` antes de planejar e `save_reasoning_trace` após executar |
| `tools.py` | Tools langchain: `recall_strategy` (router vetorial) e `save_reasoning_trace` (persistência sanitizada) |

> **Nota de implementação:** a rota de chat interativo do REPL hoje chama `ask_llm` diretamente (com prompt montado a partir do `ExecutionContext`); o grafo DeepAgents completo (`create_supervisor`) é o harness de execução de tarefas multi-agente (SDD §6) e está acessível via `tests/integration/test_real_llm.py`.

### 2.4 `src/mi_dream/knowledge/` — Domínio de Conhecimento
| Arquivo | Responsabilidade |
|---|---|
| `models.py` | Modelos Pydantic: `Strategy`, `StrategyCreate`, `Lesson`, enums `StrategyState`/`CuratorDecision`, `VALID_TRANSITIONS` |
| `repository.py` | `StrategyRepository` — CRUD Cypher parametrizado (nunca string interpolada) |
| `service.py` | `StrategyService` — regras de negócio: promoção, transição validada, supersessão |
| `router.py` | `StrategyRouter` + `ExecutionContext` — contrato de runtime entre retrieval e agentes |
| `vector.py` | `StrategyVectorRetriever` — adapter **async** sobre o `VectorCypherRetriever` do `neo4j-graphrag` (sync, roda em `to_thread`) |
| `distiller.py` | `KnowledgeDistiller` — consolida `Lesson` → `Strategy` EXPERIMENTAL + link `SUPPORTED_BY` (KM-002) |
| `curator.py` | `Curator` — integridade, máquina de estados, dedup, promoção EXPERIMENTAL→ACTIVE, imutabilidade de traces |

### 2.5 `src/mi_dream/learning/` — Pipeline de Aprendizado
| Arquivo | Responsabilidade |
|---|---|
| `evaluator.py` | `Evaluator` — pontua traces para reflexão (heurística determinística: comprimento, outcome, falha) |
| `reflector.py` | `Reflector` — sintetiza `Lesson` via LLM (`ask_llm`); fallback heurístico quando o provider falha; descarta score < 0.5 |
| `scheduler.py` | `ReflectionScheduler` — ciclo: seleciona traces sem lesson (lote de 50) → avalia → reflete → cria `Lesson` + `DERIVED_FROM`. `start()` roda em loop com intervalo configurável |

### 2.6 `src/mi_dream/memory/` — Persistência e Memória
| Arquivo | Responsabilidade |
|---|---|
| `connection.py` | `get_driver()` — singleton do driver async Neo4j (Bolt) |
| `bootstrap.py` | `bootstrap_schema()`/`ensure_schema()` — constraints + vetor indexes 1536-d cosine; idempotente e cacheado em processo |
| `reasoning.py` | `trace_fingerprint()` — SHA-256 determinístico do payload do trace (suporta INV-001) |
| `embeddings.py` | `build_embedder()` — `OpenAIEmbeddings` do `neo4j-graphrag`, reutiliza o proxy OpenAI-compatible |

### 2.7 `src/mi_dream/llm/client.py`
`get_client()` (singleton `OpenAI`) + `ask_llm()` — chamada chat com system/user, executada fora do loop via executor quando necessário.

### 2.8 `src/mi_dream/health.py`
`check_all()` → `check_neo4j()` + `check_llm_provider()`; usado pelo `/status` do REPL.

### 2.9 `src/mi_dream/security/sanitizer.py`
Sanitização regex de PII (email, telefone, SSN, API keys, bearer) antes de qualquer gravação de trace (SDD §18.2). `sanitize()` + `contains_pii()`.

---

## 3. Modelo de Dados (Neo4j)

### 3.1 Nós
| Nó | Propriedades | Criado por |
|---|---|---|
| `ReasoningTrace` | `id, content, metadata (JSON string), outcome, content_hash, created_at, tenant_id` | tools/save_reasoning_trace, REPL |
| `Lesson` | `id, summary, decision (CREATE/REINFORCE/REFINE/CONTRADICT), source_trace_ids, confidence, tenant_id, created_at` | ReflectionScheduler |
| `Strategy` | `id, title, description, domain, content, state, support_count, success_rate, created_at, updated_at, tenant_id, superseded_by, embedding (1536-d)` | KnowledgeDistiller |

### 3.2 Relações
| Relação | Origem → Destino | Significado |
|---|---|---|
| `DERIVED_FROM` | `Lesson` → `ReasoningTrace` | a lesson conhece suas origens |
| `SUPPORTED_BY` | `Lesson` → `Strategy` | lesson suporta a strategy (KM-002) |
| `SUPERSEDES` | `Strategy` → `Strategy` | versionamento (KM-006) |

### 3.3 Máquina de estados da Strategy (`VALID_TRANSITIONS`)
```
EXPERIMENTAL ──(support_count≥3, success_rate≥0.6)──▶ ACTIVE
ACTIVE ──(sem uso 90d)──▶ STALE
STALE ──(reforçada)──▶ ACTIVE        STALE ──(90d+ sem uso, support<3)──▶ ARCHIVED
ACTIVE ──(sucessora melhor)──▶ SUPERSEDED ──(90d+)──▶ ARCHIVED
ACTIVE ──(revalidação falha, sem sucessora)──▶ DEPRECATED   [Fase 3]
```

---

## 4. Fluxo de Execução (Chat)

```
Usuário digita / <mensagem>
   │
   ▼
REPL (repl.py:98)
   ├─ comando slash → dispatch() / render_*  (skills, agents, help, session, clear, exit, status)
   └─ mensagem normal →
        add_message("user", msg)                         → SessionManager (JSON)
        recall_context(msg)                              → StrategyRouter.retrieve()
        │                                                  ├─ vector-first: StrategyVectorRetriever.search(goal, tenant, domain, ACTIVE)
        │                                                  └─ fallback: list_by_domain(ACTIVE)  [se vetorial falhar/vazio]
        build_system_prompt(ctx)                          → injeta strategies no system prompt
        ask_llm(system, user)                             → provider (executor thread)
        add_message("assistant", msg) + render            → SessionManager + rich
        save_reasoning_trace(...)                         → Neo4j ReasoningTrace (sanitizado, content_hash)
```

**Degradação graciosa:** se o Neo4j ou o router falhar, `recall_context` retorna `ExecutionContext` vazio e o chat continua do zero. Falha ao gravar trace nunca interrompe a resposta.

---

## 5. Learning Pipeline

```
ReasoningTrace (append-only, sanitizado)
   │  cron: /reflect (ReflectionScheduler.run_cycle)  — lote de até 50 traces SEM lesson
   ▼
Evaluator.evaluate()      → pontua (0..1): conteúdo>200ch +0.3, outcome +0.4, falha +0.3
   ▼
Reflector.reflect()       → LLM sintetiza Lesson (decision + confidence); fallback heurístico
   ▼
(Learning:Lesson) + (l)-[:DERIVED_FROM]->(t)          persistido pelo scheduler
   │  cron: /distill (KnowledgeDistiller)
   ▼
Distiller                 → CREATE: Strategy EXPERIMENTAL + SUPPORTED_BY + embedding
                            REINFORCE/REFINE: match por título → update_metrics (+1) / cria nova
                            CONTRADICT: só registra na Lesson (sem mutação)  [FailurePattern: Fase 2]
   │  cron: /curator (Curator)
   ▼
Curator                   → run_integrity_checks (KM-002, KM-006, INV-001)
                            process_experimental_candidates (EXPERIMENTAL→ACTIVE, INV-002)
                            run_state_machine (STALE/SUPERSEDED/ARCHIVED)
                            deduplicate (merge SUPPORTED_BY + delete duplicado)
   │
   ▼
Strategy ACTIVE  ──▶  disponível para o recall vetorial (embedding já gravado no CREATE)
```

> **Ordem operacional recomendada:** `reflect` → `distill` → `curator`. O Distiller grava o embedding do Strategy no momento do CREATE (via `build_embedder()`), garantindo que estratégias ACTIVE sejam alcançáveis pelo recall vetorial.

---

## 6. Recall Vetorial

`StrategyVectorRetriever` (vector.py) adapta o `VectorCypherRetriever` do `neo4j-graphrag`:

- Índice `strategy_embedding` (1536-d, cosine) definido no bootstrap.
- Query de retrieval (`RETRIEVAL_QUERY`) resolve `superseded_by` via `OPTIONAL MATCH (node)-[:SUPERSEDES]->(succ)` e usa projeção de mapa com `.id` (shorthand exige `.`; chave sem ponto vira variável).
- Filtros na busca: `{tenant_id, state: ACTIVE, domain}`.
- Retriever subjacente é **síncrono** → roda em `asyncio.to_thread`.
- **Workaround conhecido:** bug upstream do `neo4j-graphrag` 1.18.0 em que `_node_embedding_property` nunca é populado — o adapter o copia de `_embedding_node_property` em `_build()` (vector.py:69).
- `Strategy.score` (cosine similarity) é preenchido pelo retriever; o Router expõe o contexto via `ExecutionContext.to_json()`.

---

## 7. CLI

### Comandos (typer)
| Comando | Ação |
|---|---|
| `mi-dream chat [-s <sessão>]` | REPL interativo (sessão nova aleatória, resumível) |
| `mi-dream sessions` | Lista sessões salvas |
| `mi-dream init` | Bootstra do schema Neo4j (constraints + índices) |
| `mi-dream reflect` | Um ciclo Evaluator→Reflector→Lesson |
| `mi-dream distill` | Lessons pendentes → Strategies EXPERIMENTAL |
| `mi-dream curator [--tenant]` | Governança (integridade, estado, dedup) |

### Slash commands (REPL)
`/skills` `/agents` `/commands` `/help` `/session [<id>]` `/clear` `/status` `/exit`

### Sessões
- `new_session_id()` gera `MMDDHHMM-xxxx` (ex.: `08061257-a1b2`) — resumível com `/session <id>`.
- Persistência em JSON (`~/.mi-dream/sessions/`); `/session` sem args cria sessão nova.

---

## 8. Segurança e Invariantes

### Segurança (SDD §18)
- **PII/Secrets:** `sanitize()` aplicado antes de gravar qualquer `ReasoningTrace`; `trace_fingerprint` cobre o payload completo.
- **Tenant:** todo nó carrega `tenant_id`; o Router filtra por escopo antes do recall (ACL Neo4j: Fase 2).
- **Injection:** apenas Cypher parametrizado (nenhuma interpolação de string).
- **Aprovação humana:** promoção para ACTIVE é governada pelo Curator (Fase 1 manual; workflow de aprovação: Fase 2).

### Invariantes garantidos pelo Curator
| ID | Regra | Onde |
|---|---|---|
| INV-001 / KM-001 | ReasoningTrace imutável (append-only + `content_hash`) | `check_trace_immutability` |
| INV-002 | ACTIVE exige `support_count >= 3` | `process_experimental_candidates` |
| INV-002a | `support_count` monotonicamente não-decrescente (clamp no Cypher) | `update_metrics` |
| INV-003 | SUPERSEDED aponta para exatamente uma sucessora | `mark_superseded` |
| KM-002 | ACTIVE possui ≥ 1 Lesson `SUPPORTED_BY` | `INTEGRITY_CHECKS` |
| KM-006 | `SUPERSEDES` forma DAG (sem ciclos) | `INTEGRITY_CHECKS` |

---

## 9. Configuração (`.env`)

| Variável | Default | Uso |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Conexão Bolt |
| `NEO4J_USER` / `NEO4J_PASSWORD` | `neo4j` / — | Credenciais |
| `NEO4J_DATABASE` | `neo4j` | Database |
| `TENANT_ID` | `default` | Escopo de conhecimento |
| `REFLECTION_CRON` | `0 */6 * * *` | Cadência de reflexão |
| `LLM_PROVIDER` | `anthropic` | Provider |
| `LLM_BASE_URL` | `http://localhost:20128/v1` | Endpoint OpenAI-compatible |
| `LLM_API_KEY` | — | Chave (obrigatória para chat) |
| `LLM_MODEL` | `claude-sonnet-4-6` | Modelo |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Modelo de embedding |
| `EMBEDDING_DIMENSIONS` | `1536` | Dimensões do vetor |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` | (usa LLM) | Override do proxy de embedding |

Infra: `docker-compose.yml` sobe `neo4j:5.26` com APOC, heaps 1G/512M e healthcheck.

---

## 10. Testes

`pytest` (asyncio_mode=auto), `ruff` como lint. 138 passed / 4 skipped.

| Grupo | Cobre |
|---|---|
| `tests/test_*.py` (unitários) | config, connection, models, repository, service, router, vector, curator, distiller, reflection, scheduler, security, health, CLI (app, commands, repl, session, renderer, entry) |
| `tests/integration/test_phase1_flow.py` | fluxo Fase 1 com Neo4j mocado |
| `tests/integration/test_cli_integration.py` | REPL end-to-end (Neo4j/LLM reais ou mocks) |
| `tests/integration/test_load_chat_learning.py` | load test chat→contexto→aprendizado (`LOAD_TEST_MESSAGES`=30, `LOAD_TEST_CONCURRENCY`=5) |
| `tests/integration/test_real_llm.py` | chamada real ao provider |

Comandos:
```bash
uv sync --extra dev      # instala deps + dev deps (NOTA: --dev sozinho não instala dev deps)
.venv/bin/python -m pytest          # suite
.venv/bin/ruff check src tests      # lint
```

---

## 11. Roadmap (SDD §15)

- **Fase 1 (atual):** DeepAgents, Neo4j bolt, Strategy CRUD + estado, Reflection cron, Distiller determinístico, Curator, Lesson como nó de primeira classe, recall vetorial.
- **Fase 2:** Pattern Miner (clustering), Distiller com LLM (authoring), Knowledge Librarian (Leiden, compactação, reindexação), `FailurePattern`/`BestPractice`/`Workflow`, relações `VALIDATES`/`CONTRADICTS`/`ABSTRACTS`, observability (Langfuse/OTel).
- **Fase 3:** Capability Graph, cross-tenant, Online Validation (`Validation`, KM-008), Adaptive Retrieval.

---

## 12. Decisões de Arquitetura Relevantes (resumo)

- **Cypher direto no Bolt, não NAMS hospedado** — necessário para Curator (dedup, SUPERSEDES, integridade).
- **Reflexão em lote (cron), nunca por episódio isolado** — evita ruído de lessons triviais.
- **`metadata` como JSON string + `outcome` primitivo** — Neo4j rejeita Map como propriedade; outcome vira propriedade pontuável pelo Evaluator.
- **Distiller determinístico na Fase 1** — a decisão já vem do Reflector; authoring LLM é Fase 2.
- **KM-002 restrito a ACTIVE** — EXPERIMENTAL nasce sem lesson de suporte por construção.
- **Execution Context como objeto de runtime**, não do grafo — trocar o Router não altera os agentes.
- **`prompt_session`/`sess` com nomes distintos no REPL** — evita shadowing que derrubava `prompt_async` (regressão corrigida).
- **Scheduler em lotes de 50** (`LIMIT`) — ciclo idempotente (`NOT EXISTS { (:Lesson)-[:DERIVED_FROM]->(t) }`).
