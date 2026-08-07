# Software Design Document (SDD)
## Sistema Multi-Agente com Memória de Aprendizado Contínuo

**Versão:** 2.4
**Status:** Draft

> **v2.4** — gatilhos de aprendizado por *contexto* (auto-learn a cada N traces + auto-compactação no threshold), fallback por tempo mantido, e **Daily Review** diário (stats + integridade + resumo LLM, `(:DailyReview {date})`). Continua tudo do v2.3 (Compaction/Episode, reflexão automática, recall de traces/episodes, correções de promoção, session resume).

---

## 1. Visão Geral

Sistema multi-agente cuja memória aprende com a própria execução (**Learning Pipeline**), em vez de apenas consumir conhecimento pré-carregado de documentação (**Knowledge Pipeline**).

O diferencial arquitetural: o grafo Neo4j evolui a partir de *reasoning traces* de agentes em produção, não apenas de ingestão de documentos. Conhecimento nasce da experiência operacional.

---

## 2. Architecture Principles

- Learning is asynchronous.
- Execution must remain deterministic.
- Memory is append-only; knowledge is curated.
- Every knowledge promotion must be explainable.
- Human feedback is an independent signal.
- Knowledge is versioned, never overwritten.
- Retrieval is optimized for execution latency.
- Learning Pipeline failure degrades gracefully, never blocks execution.
- ReasoningTrace nunca é perdido.
- Knowledge nunca é apagado, apenas arquivado.
- Toda promoção é reversível.
- Toda decisão é rastreável.
- Toda abstração aponta para sua origem.

---

## 3. Stack

| Camada | Tecnologia | Motivo |
|---|---|---|
| Orquestração de agentes | `deepagents` (LangGraph por baixo) | Harness pronto (planning, sub-agents, filesystem); LangGraph moderno resolve a objeção de "framework esconde execução" |
| Memória (short/long/reasoning) | `neo4j-agent-memory`, self-hosted/bolt | 100% Python, `pip install`, permite Cypher direto pro que o SDK não expõe |
| Grafo | Neo4j 5.20+ | Vector index nativo + Cypher |
| Observability de prompt/versão | Langfuse/OTel (fora do grafo) | Não polui o grafo de conhecimento com metadados de engenharia |

---

## 4. Domínios do Neo4j

```
Memory Domain
    Episode
    ReasoningTrace
Semantic Memory
    Entity (POLE+O)
Knowledge Domain
    Strategy
    FailurePattern
    BestPractice
    Workflow
    Capability
Governance Domain
    Validation
    Supersession
    Metrics
```

> **Nota:** `Entity` pertence a Semantic Memory (POLE+O), não ao Memory Domain. No `neo4j-agent-memory`, Entity representa memória semântica de longo prazo, não memória episódica.

---

## 4.1 Knowledge Metamodel

> Contrato arquitetural do Knowledge Graph: tipos de conhecimento, relações permitidas, cardinalidades e invariantes que o Curator deve garantir. Números de seção preservados para não quebrar referências cruzadas em código e planos.

### 4.1.1 Objetivo

O Knowledge Graph representa conhecimento consolidado, não memória bruta de execução. Organiza estratégias, capacidades e padrões operacionais para recuperação eficiente durante a execução dos agentes. Os níveis formam uma cadeia de abstração crescente:

```
ReasoningTrace
        │
        ▼
Lesson
        │
        ▼
Strategy
        │
        ▼
BestPractice
        │
        ▼
Workflow
        │
        ▼
Capability
```

### 4.1.2 Tipos de Nós

| Domínio | Tipo | Descrição | Implementação |
|---|---|---|---|
| Memory | Episode | Execução completa de uma tarefa (conversa compactada/resumo) | Fase 1 ✓ (Compactor, v2.3) |
| Memory | ReasoningTrace | Cadeia imutável de raciocínio produzida durante a execução | Fase 1 ✓ |
| Semantic Memory | Entity | Entidades semânticas (POLE+O) | Fase 2 |
| Knowledge | Lesson | Aprendizado derivado de um ou mais traces. **Nó de primeira classe desde a Fase 1** | Fase 1 ✓ (scheduler) |
| Knowledge | Strategy | Procedimento reutilizável para resolver um problema | Fase 1 ✓ |
| Knowledge | FailurePattern | Estratégia negativa (o que evitar) | Fase 2 |
| Knowledge | BestPractice | Estratégia consolidada por múltiplas evidências | Fase 2 |
| Knowledge | Workflow | Sequência de estratégias | Fase 2 |
| Knowledge | Capability | Conjunto de workflows relacionados a uma competência | Fase 3 |
| Governance | Validation | Resultado de revalidação de Strategy | Fase 3 |
| Governance | Supersession | Histórico de substituição entre Strategies (relação `SUPERSEDES`) | Fase 2 |
| Governance | Metrics | Métricas de suporte/uso por Strategy (`support_count`, `success_rate`) | Fase 1 ✓ (propriedades) |
| Operations | DailyReview | Relatório diário idempotente por data (`date`, `report`, `created_at`) | Fase 1 ✓ (Reviewer, v2.4) |

> `PromptVersion`, `Evaluation` e `Experiment` **ficam fora do grafo**, na camada de observability (Langfuse/OTel, ver §17) — não são tipos de nó do metamodelo, pois poluem o grafo com metadados de engenharia.

### 4.1.3 Relações Permitidas

| Relação | Origem | Destino | Implementação |
|---|---|---|---|
| `DERIVED_FROM` | Lesson | ReasoningTrace | Fase 1 ✓ — criada pelo scheduler (lesson conhece suas origens) |
| `SUPPORTED_BY` | Lesson | Strategy | Fase 1 ✓ — criada pelo Distiller (e merged no dedup do Curator) |
| `VALIDATES` | Lesson | Strategy | Fase 2 — a partir do Decision da Lesson |
| `CONTRADICTS` | Lesson | Strategy | Fase 2 — a partir do Decision da Lesson |
| `SUPERSEDES` | Strategy | Strategy | Fase 1 ✓ — relação criada por `mark_superseded` |
| `ABSTRACTS` | BestPractice | Strategy | Fase 2 — Knowledge Librarian |
| `BELONGS_TO` | Strategy | Workflow | Fase 2 |
| `COMPOSES` | Workflow | Strategy | Fase 2 |
| `IMPLEMENTS` | Workflow | Capability | Fase 3 |
| `APPLIES_TO` | Strategy | Capability | Fase 3 |
| `GENERATED` | Episode | Lesson | Fase 2 — Compactor também grava um `ReasoningTrace` derivado do resumo (v2.3), permitindo que o Episode entre no pipeline via `DERIVED_FROM` |
| `DETECTED_FROM` | FailurePattern | Lesson | Fase 2 |

**Decisão de direção (SUPPORTED_BY):** `(l:Lesson)-[:SUPPORTED_BY]->(s:Strategy)` — "lesson suporta strategy". Integrity checks e dedup do Curator usam `(s)<-[:SUPPORTED_BY]-(:Lesson)` (entrada). Unificada na direção do código.

### 4.1.4 Cardinalidades

| De → Para | Cardinalidade |
|---|---|
| Episode → ReasoningTrace | 1..N |
| ReasoningTrace → Lesson | N..1 |
| Lesson → Strategy | N..1 |
| Strategy → BestPractice | N..1 |
| Strategy → Workflow | N..N |
| Workflow → Capability | N..1 |

### 4.1.5 Invariantes do Modelo (KM-*)

| ID | Regra | Status |
|---|---|---|
| KM-001 | ReasoningTrace é imutável (= INV-001) | Fase 1 ✓ (append-only + `content_hash` + check no Curator) |
| KM-002 | Toda Strategy **ACTIVE** possui ≥ 1 Lesson `SUPPORTED_BY` | Fase 1 ✓ (check no Curator) |
| KM-003 | BestPractice nunca referencia Episode/ReasoningTrace diretamente, apenas via Strategy (= INV-004) | Fase 2 |
| KM-004 | Workflow nunca referencia ReasoningTrace | Fase 2 |
| KM-005 | Capability nunca referencia Lesson diretamente | Fase 3 |
| KM-006 | `SUPERSEDES` forma um DAG — nunca pode haver ciclo (A→B→A) | Fase 1 ✓ (check no Curator) |
| KM-007 | FailurePattern nunca `VALIDATES` Strategy — apenas `CONTRADICTS` | Fase 2 |
| KM-008 | Strategy ACTIVE exige `support_count ≥ 3`, `success_rate ≥ 0.6` e (Fase 3) Validation recente | Fase 1 parcial; Validation é Fase 3 |

> **Escopo de KM-002 (correção):** a revisão original dizia "toda Strategy". Estratégias `EXPERIMENTAL` nascem sem Lesson de suporte por construção — o Curator só exige `SUPPORTED_BY` para `ACTIVE` (curator.py). Invariante alinhada ao código.
>
> **KM-008 sem dono:** o nó `Validation` não existe em Fase 1 (depende de Online Validation, §16 "Revalidação ativa"). Até lá, a "validação" é representada pelas métricas existentes. Mantida como contrato de Fase 3.

### 4.1.6 Ciclo de Promoção

Cada promoção pertence a um componente específico:

| Promoção | Responsável | Status |
|---|---|---|
| Trace → Lesson | Reflector | Fase 1 ✓ |
| Lesson → Strategy | Knowledge Distiller | Fase 1 ✓ |
| Strategy → ACTIVE | Curator | Fase 1 ✓ |
| Strategy → BestPractice | Knowledge Librarian | Fase 2 |
| BestPractice → Workflow | Knowledge Librarian | Fase 2 |
| Workflow → Capability | Knowledge Librarian | Fase 3 |

### 4.1.7 Governança do Grafo

**Curator** garante: integridade estrutural (checks KM-002/KM-006 + SUPERSEDED sem sucessora), deduplicação, versionamento, máquina de estados, consistência das relações, remoção de referências órfãs, detecção de ciclos e atualização de métricas.

**Knowledge Librarian** garante: reindexação de embeddings, community detection (Leiden), compactação hierárquica, atualização de projeções de consulta, reconstrução de índices vetoriais e materialização de visões.

### 4.1.8 Lacunas Fase 1 vs Metamodel (migração)

| Item | Fase 1 (hoje) | Metamodel (canônico) | Migração |
|---|---|---|---|
| Trace→Lesson | `DERIVED_FROM` ✓ (lesson→trace) | `DERIVED_FROM` | ✓ resolvido em Fase 1 |
| SUPERSEDES | relação `SUPERSEDES` ✓ (cycle-check e orphan-check funcionais) | relação `SUPERSEDES` | ✓ resolvido em Fase 1 |
| SUPPORTED_BY | Distiller cria ao promover Lesson→Strategy ✓ | Distiller cria ao promover Lesson→Strategy | ✓ resolvido em Fase 1 (KM-002 sem exceção para estratégias promovidas) |
| Lesson | nó de primeira classe ✓ | — | ✓ resolvido em Fase 1 |

---

## 5. Capability Model

```
Capability ("Diagnose Kubernetes")
    └─ Workflow
         └─ BestPractice
              └─ Strategy
                   └─ Lesson
```

Permite responder perguntas como "quais estratégias existem para diagnóstico de Kubernetes?" sem depender apenas de similaridade semântica.

---

## 6. Componentes de Execução

```
DeepAgents Supervisor/Planner
  ├─ Research Agent (sub-agent)
  └─ Execution Agent (sub-agent)
```

**Tools do Supervisor:**
- `recall_strategy` — consulta o Strategy Router antes de planejar. Recuperação vetorial com `StrategyVectorRetriever` (embedding via `OpenAIEmbeddings`, índice `strategy_embedding` 1536-d cosine, filtros `{tenant_id, state: ACTIVE, domain}`); se o vector search falhar ou voltar vazio, cai para `StrategyRepository.list_by_domain(domain, tenant_id, ACTIVE)`. Embedding das Strategies é gravado pelo Knowledge Distiller no CREATE.
- `save_reasoning_trace` — grava trace via `memory.reasoning`

**Execution Context (contrato de runtime):**
- `goal` — objetivo da tarefa
- `entities` — entidades semânticas relevantes (Semantic Memory)
- `strategies` — estratégias recuperadas do Knowledge Graph
- `constraints` — restrições operacionais
- `capabilities` — capacidades disponíveis
- `previous_failures` — FailurePatterns relevantes
- `best_practices` — BestPractices aplicáveis
- `recent_traces` — últimas `ReasoningTrace`s do tenant (memória crua de conversa recente, v2.3)
- `episodes` — resumos de conversas anteriores (`Episode`, memória episódica compactada, v2.3)

Esse contrato facilita trocar o Router sem alterar os agentes.

**Regra de discrepância:** se o Research Agent trouxer dado que contradiz a Strategy retornada, o Supervisor sinaliza a discrepância explicitamente na resposta, em vez de escolher silenciosamente uma fonte.

---

## 7. Contratos entre Componentes

```
Pattern Miner
  input:  ReasoningTrace[]
  output: PatternCandidate[]

Knowledge Distiller
  input:  PatternCandidate[] (Fase 1: Lesson[] — sem Pattern Miner)
  output: ExperimentalStrategy[] (com link SUPPORTED_BY, KM-002)

Curator
  input:  ExperimentalStrategy[]
  output: GovernedStrategy[]

Knowledge Librarian
  input:  (nenhum — serviço contínuo, não recebe do pipeline)
  atua diretamente sobre: Neo4j Knowledge Graph
```

---

## 8. Fluxo Arquitetural

```
                         DeepAgents
                              │
                    Supervisor / Planner
                              │
         ┌────────────────────┴────────────────────┐
         │                                         │
  Research Agent                           Execution Agent
         │                                         │
         └───────────────┬─────────────────────────┘
                         │
                 Neo4j Agent Memory (self-hosted/bolt)
                         │
         ┌───────────────┼─────────────────────┐
         │               │                     │
  short_term       long_term (POLE+O +    reasoning
  (Episodic)     Strategy/FailurePattern)  (Traces, :TOUCHED)
                         │
                 ═══ Learning Pipeline (cron) ═══
                         │
       Evaluator → Reflection → Pattern Miner
                         │
              Knowledge Distiller (LLM decide)
                         │
                      Curator
        (dedup, versionamento, máquina de estados,
         resolução de conflito, métricas,
         integridade estrutural)
                         │
              Neo4j Knowledge Graph
                         │
           ┌─────────────┴─────────────┐
           ▼                           │
   Strategy Router            Knowledge Librarian
           │                (serviço contínuo:
           ▼                 reindexação, Leiden,
  DeepAgents Supervisor       compactação hierárquica)
```

**Nota estrutural:** o Knowledge Librarian atua diretamente sobre o Knowledge Graph como serviço contínuo (reindexação, detecção de comunidades, manutenção de índices), independente da criação de novas estratégias — não é uma etapa sequencial do pipeline.

---

## 9. Responsabilidades por Componente

| Componente | Faz | Não faz |
|---|---|---|
| **Pattern Miner** | `cluster_by_workflow_pattern()` + `is_complex_and_repeatable()` | Não decide conteúdo, só filtra candidatos |
| **Reflector** | Sintetiza Lessons a partir de ReasoningTraces | Não agrupa padrões, não cria Strategies |
| **Knowledge Distiller** | Cria Strategy EXPERIMENTAL a partir de Lesson (decidido pelo Reflector) + link `SUPPORTED_BY` (KM-002). Fase 1: determinístico, sem LLM | Não governa qualidade a longo prazo; authoring via LLM é Phase 2 |
| **Curator** | Dedup (MERGE), versionamento (SUPERSEDES), máquina de estados, resolução de conflito, métricas, integridade estrutural | Não indexa nem otimiza retrieval |
| **Knowledge Librarian** | Community Detection (Leiden) → Hierarchy → Embedding Refresh → Projection Cache → Materialized Views | Não decide o que é válido/inválido |
| **Strategy Router** | Retrieval vector-first (neo4j-graphrag `VectorCypherRetriever` sobre `strategy_embedding`, filtros tenant/domain/ACTIVE), fallback para `list_by_domain`; escolhe nível de abstração | Não grava nada, só lê |

---

## 10. Máquina de Estados (Strategy)

```
EXPERIMENTAL ──(support_count≥3, success_rate≥0.6)──▶ ACTIVE

ACTIVE ──(sem uso 90d)──▶ STALE
STALE ──(reforçada de novo)──▶ ACTIVE
STALE ──(+90d sem uso, support_count baixo)──▶ ARCHIVED

ACTIVE ──(nova Strategy melhor)──▶ SUPERSEDED
SUPERSEDED ──(+90d)──▶ ARCHIVED

ACTIVE ──(revalidação falha, sem sucessora)──▶ DEPRECATED
```

> **Nota:** SUPERSEDED não vai direto para ARCHIVED. Estratégias superseded precisam existir para auditoria — elas só deixam de ser a estratégia de execução, não deixam de existir.

---

## 11. Event Model

*(referência para implementação futura via filas, não implementado na Fase 1)*

```
TraceCreated
  → PatternDetected
    → StrategyCreated
      → StrategyPromoted
        → StrategyDeprecated
          → KnowledgeArchived
```

**Eventos negativos (adicionados v2.1):**

| Evento | Trigger |
|---|---|
| `StrategyRejected` | Curator rejeita ExperimentalStrategy |
| `StrategyArchived` | State machine move para ARCHIVED |
| `ConflictDetected` | Duas Strategies contradizem-se |
| `GraphCompacted` | Librarian executa compactação |
| `EmbeddingRebuilt` | Librarian reconstrói índices vetoriais |

---

## 12. Invariantes

| ID | Regra |
|---|---|
| INV-001 | ReasoningTrace é **append-only** e possui fingerprint determinístico verificável. Alteração do conteúdo após persistência deve ser detectável. |
| INV-002 | Strategy `ACTIVE` sempre possui `support_count >= 3`. |
| INV-002a | `support_count` é monotonicamente não-decrescente. |
| INV-003 | `SUPERSEDED` sempre aponta para exatamente uma Strategy sucessora. |
| INV-004 | `BestPractice` nunca referencia diretamente `ReasoningTrace` (apenas via `Strategy`). |

**Enforcement (Fase 1):**

- **INV-001 — append-only + detecção.** Todo `ReasoningTrace` é criado via `CREATE` (não existe caminho de UPDATE/DELETE no código) e recebe `content_hash` (SHA-256 determinístico de `content`/`outcome`/`metadata` — `mi_dream/memory/reasoning.trace_fingerprint`). O Curator roda `check_trace_immutability` dentro de `run_integrity_checks`, recomputando o fingerprint e sinalizando qualquer divergência (mutação externa) ou trace sem `content_hash` (pré-feature). *Nota: bloqueio no nível do grafo via `apoc.trigger` foi avaliado e descartado — bug no APOC 5.26.29 + Neo4j 5.26 (event data com tipo inconsistente, `drop` assíncrono quebrado com FOLLOWER). Fica como hardening futuro se o APOC for corrigido.*
- **INV-002a — clamp no grafo.** `update_metrics` usa `support_count = support_count + CASE WHEN $delta < 0 THEN 0 ELSE $delta END`: deltas negativos são descartados no nível do Cypher, então `support_count` nunca decresce independentemente do caller.

---

## 13. Non-Functional Requirements (NFRs)

**Latency**
- `recall_strategy` < 500ms (P95)

**Availability**
- Learning Pipeline pode ficar indisponível sem afetar execução.
- Comportamento de degradação explícito: se a Learning Pipeline estiver offline, `Strategy Router` retorna vazio e o Supervisor planeja do zero — nunca bloqueia a execução.

**Scalability**
- 10 milhões de nós
- 100 milhões de relações

**Consistency**
- Estratégias são promovidas apenas por jobs assíncronos.

**Auditability**
- Toda promoção possui origem rastreável.

**Explainability**
- Toda Strategy deve apontar para os episódios que a originaram.

**Security**
- Knowledge Isolation por tenant (ACL no grafo)
- PII/Secrets em ReasoningTrace: nunca armazenar; sanitizar antes de gravar
- Human Approval: promoções para ACTIVE requerem aprovação humana (Fase 1: manual; Fase 2: workflow de aprovação)
- Fora de escopo Fase 1: implementação de ACL multi-tenant — arquitetura deve permitir adição futura sem migração de dados

---

## 14. Service Level Objectives (SLOs)

| SLI | SLO |
|---|---|
| Reflection Cadence | roda a cada ≤ 6h (cron configurável) |
| Distiller → Curator Latency | < 30 min, uma vez que o job de reflexão já rodou |
| Graph Availability | 99.9% |
| Recall Latency | 95% < 500ms |
| Knowledge Freshness | 95% < 24h |

> **Nota:** "Reflection Cadence" e "Distiller→Curator Latency" são medidos separadamente — o primeiro depende da frequência do cron (horas), o segundo é o tempo de processamento uma vez que o job já disparou (minutos). "Knowledge Freshness" mede o tempo entre descoberta de uma Strategy e sua disponibilidade para o Router.

---

## 15. Roadmap

```
Phase 1 (implementado)
  - LangChain tools / REPL (DeepAgents substituído em v2.4)
  - Neo4j Agent Memory (self-hosted/bolt)
  - Strategy (CRUD básico)
  - Reflection (cron simples)
  - Knowledge Distiller básico (Lesson → Strategy EXPERIMENTAL + SUPPORTED_BY)
  - Curator (dedup + máquina de estados básica + integridade estrutural)
  - Lesson como nó de primeira classe (já implementado — scheduler cria `(l:Lesson)` + `DERIVED_FROM`)
  - v2.3: Episode (compaction de conversa) + reflexão automática + recall de traces/episodes
  - v2.4: gatilhos por contexto (traces + auto-compact) + Daily Review (`DailyReview`)
  - v2.5: Failure Monitoring (`ReasoningTrace {outcome:"failure"}` + `/failures` + `mi-dream failures`)

Phase 2
  - Reflector (separado de Reflection)
  - FailurePattern (entidade formal) + Failure Analyzer — caminho negativo dual-path (§20.3, §23.7)
  - Pattern Miner (clustering fuzzy) — convergência success/failure
  - Distiller com LLM (authoring de conteúdo)
  - Knowledge Librarian (compactação, reindexação) — **Leiden adiado** até haver volume real de dados
  - Workflow / BestPractice (abstrações emergentes)
  - `VALIDATES` / `CONTRADICTS` / `ABSTRACTS`

Phase 3
  - Capability Graph
  - Cross-Tenant
  - Online Validation (nó Validation, KM-008)
  - Adaptive Retrieval
```

> **Leiden (Phase 2 → adiado).** Community detection só entra depois de coletar dados reais: centenas/milhares de Strategies com `support_count`, `success_rate`, `failure_rate`, `usage`. Sem esse volume, Leiden vira complexidade operacional sem benefício mensurável. Decisão registrada em §17.

---

## 16. Pontos em Aberto

1. **Revalidação ativa**: não há mecanismo seguro de re-testar uma Strategy sem reexecutar a ação no mundo real. Decisão provisória: revalidação = reprocessar traces históricos com a lógica de decisão atual, não replay ao vivo.
2. **Threshold de compactação**: quando um cluster de Strategy vira BestPractice ainda não tem número definido — requer calibração com dado real de volume.
3. **Escopo multi-tenant**: se o sistema vier a servir múltiplos usuários/times, falta decidir escopo de `user_identifier` no design de Strategy compartilhada vs. privada.

---

## 17. Decisões Registradas (Rationale)

- **Self-hosted (bolt), não NAMS** — Cypher direto é obrigatório para o Curator (dedup customizado, SUPERSEDES, integridade estrutural) e não está disponível no backend hospedado.
- **`attributes={}` no `add_entity`** para criação; Cypher manual para PATCH incremental — comportamento de merge do SDK não é documentado o suficiente para depender dele.
- **Reflexão em lote (cron), nunca por episódio isolado** — evita ruído de lições triviais geradas a partir de eventos únicos.
- **Reflector separado de Reflection**: Reflection coordena o pipeline (Evaluator → Reflector → Pattern Miner); Reflector sintetiza Lessons. Separação de responsabilidades.
- **`PromptVersion`/`Evaluation`/`Experiment` ficam fora do grafo**, na camada de observability (Langfuse/OTel) — evita poluir o grafo de conhecimento operacional com metadados de engenharia de prompt.
- **Knowledge Librarian como serviço contínuo**, não etapa do pipeline — desacopla manutenção de grafo (deve rodar sempre) de criação de conhecimento (acionada por trace).
- **Decision como propriedade de Lesson**, não nó separado — Decision sem componente que o produza vira nó sem dono. A decisão CREATE/REINFORCE/REFINE/CONTRADICT do Distiller já existe implicitamente; registrá-la como propriedade do Lesson preserva auditabilidade sem criar um nó desacoplado.
- **Lesson como nó de primeira classe desde a Fase 1** — o scheduler já cria `(l:Lesson)` + `DERIVED_FROM`; o metamodelo (§4.1) formaliza a cadeia Experience → Learning → Strategy e a explicabilidade de toda promoção.
- **`DERIVED_FROM` como relação canônica Lesson→Trace** — o trace nasce antes da lesson (na escrita a criação é dirigida pelo trace), mas a leitura é `(l)-[:DERIVED_FROM]->(t)` (lesson conhece suas origens). Implementado na Fase 1; seleção do scheduler usa `NOT EXISTS { (:Lesson)-[:DERIVED_FROM]->(t) }` (idempotente).
- **KM-002 restrito a `ACTIVE`** — Estratégia `EXPERIMENTAL` nasce sem Lesson de suporte por construção; o Curator só exige `SUPPORTED_BY` para estratégias ativas.
- **`SUPERSEDES` como relação** — o cycle-check (KM-006) e o orphan-check consultam `[:SUPERSEDES]`; `mark_superseded` cria a relação (e derruba a anterior, INV-003) e `get()` resolve `superseded_by` via projeção do mapa. Implementado na Fase 1.
- **`metadata` como JSON string + `outcome` como propriedade primitiva** — Neo4j rejeita Map como valor de propriedade; o `ReasoningTrace` serializa `metadata` (JSON) e expõe `outcome` como propriedade para o Evaluator pontuar. Sem isso, traces de produção nunca seriam refletidos.
- **Distiller determinístico na Fase 1** — a decisão CREATE/REINFORCE/REFINE/CONTRADICT já é tomada pelo Reflector; o Distiller materializa a Strategy (EXPERIMENTAL) e cria `SUPPORTED_BY` (KM-002). REINFORCE/REFINE incrementam `support_count` da Strategy correspondente (match por título normalizado) ou criam uma nova. Authoring via LLM é Phase 2.
- **SUPERSEDED → ARCHIVED**: Strategy superseded precisa existir para auditoria. Ela só deixa de ser a estratégia de execução, não deixa de existir.
- **Execution Context como objeto de runtime**, não do grafo — pertence à interface da camada de agentes, não ao metamodelo do Knowledge Graph.
- **`Episode` como memória episódica compactada (v2.3)** — o nó já existia no schema com índice vetorial (`episode_embedding`) sem uso; a compactação de conversa é o primeiro consumidor. O resumo vira `Episode` (durável, recall entre sessões) **e** um `ReasoningTrace` derivado (entra no pipeline), fechando o ciclo episódico → conhecimento.
- **Compactação por threshold de caracteres, não por contagem de mensagens (v2.3)** — `COMPACT_THRESHOLD_CHARS` (8000) é simples e determinístico; calibração por tokens fica como ajuste fino futuro.
- **Reflexão automática em background, com falha silenciosa (v2.3)** — `run_learning_cycle` isola cada etapa em `try/except`; o ciclo nunca bloqueia o chat (alinhado a §13 Availability). Intervalo via `REFLECTION_INTERVAL_MINUTES` no REPL e `REFLECTION_CRON` no daemon `mi-dream learn`.
- **Bônus `+0.1` para `outcome=="success"` no Evaluator (v2.3)** — conversas curtas de sucesso (fatos, nomes, preferências) passam a atingir o threshold do Reflector; traces longos/falhas seguem pontuando mais alto.
- **Seeding de métricas no Distiller (v2.3)** — `success_rate` nunca era escrito (ficava 0.0), tornando INV-002/KM-008 inalcançável. `_create`/`_reinforce` agora registram o primeiro reforço (`support_count=1, success_rate=1.0`); o portão de promoção é preservado.
- **Leiden adiado (v2.5)** — community detection só após volume real de Strategies com `support_count`/`success_rate`/`failure_rate`/`usage` (centenas/milhares). Sem dados, Leiden é complexidade operacional sem benefício mensurável.
- **FailurePath como conhecimento negativo (v2.5)** — falha e sucesso são sinais distintos: `FailurePattern` não é o "inverso" de `Strategy`. O caminho negativo (`FailureTrace → FailureAnalysis → FailurePattern`) tem métricas próprias (`failure_count`, `last_seen`) e alimenta o mesmo Strategy Router (recall negativo). Phase 2.

---

## 18. Segurança

> **Escopo:** Fora de escopo Fase 1. Arquitetura deve permitir adição sem migração de dados.

### 18.1 Knowledge Isolation

- Cada Strategy, Lesson, e entidade de conhecimento carrega `tenant_id` ou `scope`.
- Queries do Strategy Router filtram por escopo antes de retrieval.
- ACL no Neo4j: role-based access por tenant.

### 18.2 PII e Secrets

- **Proibido** armazenar PII (emails, nomes, telefones) em ReasoningTrace ou Lesson.
- **Proibido** armazenar secrets (API keys, tokens, senhas) em qualquer nó do grafo.
- Sanitização antes de gravar: regex-based scrub no pipeline de ingestão de traces.
- Audit log de tentativas de gravação com PII detectado.

### 18.3 Human Approval

- Promoções para `ACTIVE` requerem aprovação humana (Fase 1: manual via CLI/API; Fase 2: workflow de aprovação com multi-eye review).
- Promoções automáticas permitidas apenas de EXPERIMENTAL → STALE (rollback, não promoção).

### 18.4 Threat Model (incompleto)

| Ameaça | Mitigação | Status |
|---|---|---|
| Leak de conhecimento entre tenants | tenant_id em todos os nós + ACL Neo4j | Fase 2 |
| Poisoning via traces maliciosos | Human approval para ACTIVE | Fase 1 |
| Exfiltration via ReasoningTrace | Sanitização PII | Fase 1 |
| Graph corruption (cypher injection) | Parameterized queries only | Fase 1 |

---

## 19. Conversation Compaction & Episodic Memory (v2.3)

### 19.1 Objetivo

Conversas longas crescem sem limite no contexto do LLM (custos + degradação de qualidade). A compactação condensa os turnos antigos em um **resumo episódico**, mantendo o contexto limpo sem perder fatos-chave. O resumo é persistido como nó `Episode` no grafo e reutilizado no recall de sessões futuras.

```
context longa
   │  > COMPACT_THRESHOLD_CHARS (default 8000)
   ▼
Compactor.summarize(messages)  ── LLM condensa, preservando fatos-chave
   │
   ├─▶ [{"role":"system","content":"[Resumo] ..."}, *recent]   (context limpo)
   │
   └─▶ persist_episode()
        ├─▶ (:Episode {id, summary, session_id, tenant_id, created_at, embedding})
        └─▶ cria ReasoningTrace derivado do resumo  →  entra no Learning Pipeline
```

### 19.2 Componentes

| Componente | Responsabilidade | Implementação |
|---|---|---|
| `ConversationCompactor` | `summarize()` (LLM via `ask_llm_full`) + `compact()` (threshold + keep_recent) | `learning/compactor.py` (novo) |
| `EpisodeRepository` | CRUD Cypher de `Episode` + embedding (`episode_embedding`, 1536-d cosine — já no schema) | `knowledge/repository.py` ou módulo próprio |
| REPL | auto-compactação no loop + `/compact` manual; persiste Episode (fire-and-forget) | `cli/repl.py`, `cli/commands.py` |
| Recall | `ExecutionContext.episodes` populado por recência (fallback vetorial) | `knowledge/router.py`, `cli/repl.py` |

### 19.3 Regras

- **Trigger:** contexto excede `COMPACT_THRESHOLD_CHARS` (auto) ou `/compact` (manual).
- **Preservação:** o prompt de sumarização instrui a reter nomes, preferências, decisões, snippets e fatos objetivos; condensar o resto.
- **`COMPACT_KEEP_RECENT`** (default 8): turnos recentes mantidos verbatim após o resumo.
- **Idempotência de recall:** Episodes recentes são injetados no system prompt junto com `recent_traces` e strategies ACTIVE.
- **PII:** o resumo passa por `sanitize()` antes de persistir (mesma política de `ReasoningTrace`, §18.2).

---

## 20. Reflexão Automática (v2.3)

### 20.1 Objetivo

O Learning Pipeline (trace → lesson → strategy → governança) deixa de depender de execução manual (`reflect`/`distill`/`curator`) e roda sozinho: em background dentro do chat e/ou como daemon standalone.

### 20.2 Modos de execução

| Modo | Disparo | Quando |
|---|---|---|
| Background REPL | `asyncio.create_task(_auto_learn())` | a cada `REFLECTION_INTERVAL_MINUTES` (default 10) + no `/exit` |
| Por contexto (v2.4) | pós-turno no REPL | (a) `_traces_since_learn >= LEARN_TRACE_THRESHOLD`; (b) contexto >= `COMPACT_THRESHOLD_CHARS` (auto-compact + Episode + ciclo) |
| Daemon | `uv run mi-dream learn` | loop infinito, intervalo via `-i/--interval-minutes` (default 10 min); `--once` para ciclo único |
| Manual | `/learn` (REPL) | sob demanda |

> O disparo **por contexto** (v2.4) é o gatilho primário; o intervalo por tempo permanece como rede de segurança (fallback) quando o processo fica ocioso.

### 20.3 Ciclo (`run_learning_cycle`)

**Alvo arquitetural (dual-path):**

```
                         ReasoningTrace
                              │
                    ┌─────────┴──────────┐
                    │                    │
                Success               Failure
                    │                    │
                    ▼                    ▼
               Evaluator          FailureAnalyzer      [Phase 2]
                    │                    │
                    ▼                    ▼
               Reflector          FailurePattern       [Phase 2]
                    │                    │
                    └─────────┬──────────┘
                              ▼
                        Pattern Miner                   [Phase 2]
                              │
                              ▼
                     Knowledge Distiller
                              │
                              ▼
                           Curator
                              │
                              ▼
                        Knowledge Graph
```

**Fase 1 (implementado)** — caminho linear:

```
ReflectionScheduler.run_cycle()     traces → Lessons (DERIVED_FROM)
        │
KnowledgeDistiller.distill(...)     Lessons → Strategy EXPERIMENTAL + SUPPORTED_BY + embedding
        │
Curator                             integridade → state machine → dedup → EXPERIMENTAL→ACTIVE
```

Falhas em Fase 1 persistem como `ReasoningTrace {outcome:"failure"}` (monitoramento, §23), sem entidade `FailurePattern` ainda.

Cada etapa é isolada com `try/except`: a falha do pipeline **nunca** bloqueia a execução (degradação graciosa, §13 Availability).

### 20.4 Correções de promoção (v2.3)

- **Evaluator:** traces curtos com `outcome="success"` recebem `+0.1` (bônus) → atingem o threshold 0.5 do Reflector. Conversas curtas de fato (ex.: "meu nome é X") agora viram Lesson.
- **Distiller:** `_create` e `_reinforce` semeiam `support_count`/`success_rate` (`update_metrics(id, 1, 1.0)`) — sem isso `success_rate` nunca saía de 0.0 e o portão KM-008/INV-002 (`support_count ≥ 3, success_rate ≥ 0.6`) era inalcançável.
- **KM-008** permanece o portão de promoção; agora é atingível por reforços acumulados.

### 20.5 Auto-compactação por contexto (v2.4)

No REPL, após cada troca de mensagens, se `sum(len(content)) do contexto >= COMPACT_THRESHOLD_CHARS`, o `ConversationCompactor` roda automaticamente: condensa → substitui o contexto pela versão compactada → persiste `(:Episode)` → dispara `run_learning_cycle()` (o resumo vira `ReasoningTrace` derivado e entra no pipeline).

---

## 21. Configuração nova (v2.3)

| Variável | Default | Uso |
|---|---|---|
| `REFLECTION_INTERVAL_MINUTES` | `10` | intervalo do ciclo automático no REPL (fallback) |
| `COMPACT_THRESHOLD_CHARS` | `8000` | tamanho que dispara a compactação (auto ou `/compact`) |
| `COMPACT_KEEP_RECENT` | `8` | turnos mantidos verbatim após compactar |
| `LEARN_TRACE_THRESHOLD` | `10` | nº de traces desde o último ciclo que dispara auto-learn (v2.4) |
| `DAILY_REVIEW_HOUR` | `8` | hora (0-23) do Daily Review diário (v2.4) |

---

## 22. Daily Review (v2.4)

### 22.1 Objetivo

Revisão diária automatizada ("daily") do que foi aprendido e produzido no dia: verifica se o pipeline processou corretamente (sem traces órfãos/pendentes), se a integridade do grafo se mantém e se há conhecimento estagnado que merece atenção.

> **Posicionamento:** Daily Review é **observabilidade operacional** do sistema de aprendizado (human-facing), não o mecanismo de aprendizado em si. Mantém-se separado do Learning Pipeline: execução (`runtime`) / aprendizado (`async`) / revisão (`human-facing`) são planos distintos.

### 22.2 Componentes

- `DailyReviewer(session, use_llm=True)` — coleta stats + integridade + resumo LLM + persistência.
- `run_daily_review(tenant_id=None)` — função módulo que abre driver e executa a revisão.
- `reviewed_dates(tenant_id) -> set[str]` — datas já revisadas no grafo (`(:DailyReview {date})`).
- `daily_review_due(now_hour, reviewed_dates, today) -> bool` — função pura do scheduler.

### 22.3 Conteúdo do relatório

| Bloco | Descrição |
|---|---|
| `stats` | traces/episodes/lessons de hoje; strategies por estado; promovidas hoje; total |
| `health` | traces não processados (sem `DERIVED_FROM`), lessons pendentes (sem `SUPPORTED_BY`), candidatos a promoção (`support_count ≥ 3 AND success_rate ≥ 0.6`) |
| `integrity_violations` | saída de `Curator.run_integrity_checks` (KM-*, INV-001) |
| `summary` | parágrafo narrativo gerado via LLM (opcional, `use_llm`) |

### 22.4 Persistência e schedule

- `MERGE (:DailyReview {date, tenant_id}) SET report, created_at` — idempotente por dia.
- **Hora fixa + catch-up:** se `now.hour >= DAILY_REVIEW_HOUR` e a data atual ainda não tem `DailyReview` no grafo, a revisão roda ao iniciar o REPL/daemon; depois o scheduler checa a cada 60 min. Isso cobre o caso de o processo não estar aberto exatamente às 08:00.

### 22.5 Interfaces

| Comando | Onde | Efeito |
|---|---|---|
| `/review` | REPL | roda `run_daily_review` imediatamente |
| `uv run mi-dream review [--once]` | CLI | revisão imediata; daemon diário sem `--once` |

---

## 23. Monitoramento de Falhas (v2.5)

### 23.1 Objetivo

Tornar falhas de execução visíveis e aprendizáveis. Toda chamada LLM que falha (chat, skill, agent, cron) persiste um `ReasoningTrace` com `outcome="failure"` e detalhes estruturados do erro; o REPL e a CLI expõem `failures` para inspeção e a análise agrega por tipo. Falhas já recebem bônus no `Evaluator` (§12/§20.3, +0.3) — persistir a falha alimenta o pipeline de reflexão.

### 23.2 Componentes

- `extract_llm_error(exc) -> (error_type, message)` — `llm/client.py`: classifica exceções do SDK OpenAI/builtins em tipo curto (`connection_error`, `timeout_error`, `rate_limit_error`, `auth_error`, `permission_error`, `api_error`, `config_error`, `unknown_error`) com mensagem truncada (300 chars).
- `save_reasoning_trace` (agent/tools) — além de `outcome`, grava propriedades `error_type` e `error_source` no nó (nullable), habilitando filtro Cypher sem parse de JSON.
- `get_failures(tenant_id, limit=20, error_type=None, source=None) -> list[dict]` — `learning/failure_analyzer.py`: consulta `(:ReasoningTrace {outcome:"failure"})` mais recentes primeiro; opcionalmente filtra por `t.error_type` e `t.error_source`.
- `render_failures(failures)` — `cli/renderer.py`: tabela `Quando | Tipo | Source | Erro | Tokens`.
- Handler `/failures [error_type]` no REPL + comando `mi-dream failures`.

### 23.3 Instrumentação (`repl.py`)

Todos os caminhos LLM usam um helper comum:

- `_ask_llm(system, user, history)` — executa `ask_llm_full` no executor (único ponto de chamada).
- `_trace_outcome(source, name, content, outcome, error_type=None, error_message=None, tokens=0, latency_ms=0.0)` — persiste o trace (nunca levanta, sanitize §18.2) e incrementa `_traces_since_learn` tanto em sucesso quanto em falha.

| Caminho | `source` | `outcome=success` | `outcome=failure` |
|---|---|---|---|
| chat regular | `chat` | conteúdo normal | `[ERROR: msg]` no content + `error_type`/`error_message` |
| `/skill` | `skill` | idem | idem |
| `@agent` | `agent` | idem | idem |
| cron job | `cron` | idem | idem |

Em falha: `render_error` mostra a mensagem e o loop continua (degradação graciosa, §13).

### 23.4 Filtros e agrupamento

- `t.error_type` e `t.error_source` são propriedades no nó (Cypher paramétrico, INV-001).
- Nós criados antes da v2.5 não têm as propriedades → `get_failures` faz fallback para `metadata.error_type`/`metadata.source` e retorna `"unknown"`.
- `error_type` aceita: `connection_error`, `timeout_error`, `rate_limit_error`, `auth_error`, `permission_error`, `api_error`, `config_error`, `unknown_error`.
- `source` aceita: `chat`, `skill`, `agent`, `cron`.

### 23.5 Interfaces

| Comando | Onde | Efeito |
|---|---|---|
| `/failures [error_type]` | REPL | tabela com as últimas 20 falhas (filtra por tipo se passado) |
| `uv run mi-dream failures [--limit N] [--type T] [--source S]` | CLI | lista de falhas persistidas |

### 23.6 Invariantes

- Falha de LLM **nunca** aborta o REPL: apenas `render_error` + trace de falha (INV: degradação graciosa).
- `_trace_outcome` nunca levanta (qualquer exceção de persistência é engolida).
- `content` do trace de falha é PII-sanitizado (§18.2); `error_message` não contém secrets (origem: exceção, truncada).

### 23.7 FailurePattern — conhecimento negativo (Phase 2)

Fase 1 trata falhas como **monitoramento** (§23.1-23.6). Phase 2 formaliza o caminho de falha como **aprendizado** — sinais positivos e negativos são distintos e não devem ser fundidos:

```
LLM Failure → FailureTrace (outcome="failure")
              → FailureAnalysis (agrega por tipo/origem/contexto)
              → FailurePattern (:FailurePattern {tenant_id, error_type, pattern, failure_count, last_seen})
```

- `FailurePattern` é nó de primeira classe, **não** o inverso de `Strategy` — tem métricas próprias (`failure_count`, `last_seen`) e ciclo de vida independente.
- `FailureAnalyzer` agrega `FailureTrace`s (via `PatternMiner`, clustering fuzzy) em padrões reincidentes.
- O **Strategy Router** passa a consultar tanto `Strategy` (positivo) quanto `FailurePattern` (negativo): o agente recebe "o que costuma funcionar" **e** "o que historicamente falha neste contexto".
- Relação opcional `AVOIDS` liga `Strategy` ↔ `FailurePattern` (Phase 2).

---
