# Software Design Document (SDD)
## Sistema Multi-Agente com Memória de Aprendizado Contínuo

**Versão:** 2.2
**Status:** Draft

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
| Memory | Episode | Execução completa de uma tarefa | Nó (schema) — gravação Fase 2 |
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
| `GENERATED` | Episode | Lesson | Fase 2 |
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
| INV-001 | ReasoningTrace nunca é alterado. |
| INV-002 | Strategy `ACTIVE` sempre possui `support_count >= 3`. |
| INV-002a | `support_count` é monotonicamente não-decrescente. |
| INV-003 | `SUPERSEDED` sempre aponta para exatamente uma Strategy sucessora. |
| INV-004 | `BestPractice` nunca referencia diretamente `ReasoningTrace` (apenas via `Strategy`). |

**Enforcement (Fase 1):**

- **INV-001 — append-only + detecção.** Todo `ReasoningTrace` é criado via `CREATE` e recebe `content_hash` (SHA-256 determinístico de `content`/`outcome`/`metadata` — `mi_dream/memory/reasoning.trace_fingerprint`). Não existe caminho de escrita de update/delete no código. O Curator roda `check_trace_immutability` dentro de `run_integrity_checks`, recomputando o fingerprint e sinalizando qualquer divergência (mutação externa) ou trace sem `content_hash` (pré-feature). *Nota: bloqueio no nível do grafo via `apoc.trigger` foi avaliado e descartado — bug no APOC 5.26.29 + Neo4j 5.26 (event data com tipo inconsistente, `drop` assíncrono quebrado com FOLLOWER). Fica como hardening futuro se o APOC for corrigido.*
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
Phase 1
  - DeepAgents (Supervisor + sub-agents)
  - Neo4j Agent Memory (self-hosted/bolt)
  - Strategy (CRUD básico)
  - Reflection (cron simples)
  - Knowledge Distiller básico (Lesson → Strategy EXPERIMENTAL + SUPPORTED_BY)
  - Curator (dedup + máquina de estados básica + integridade estrutural)
  - Lesson como nó de primeira classe (já implementado — scheduler cria `(l:Lesson)` + `DERIVED_FROM`)

Phase 2
  - Reflector (separado de Reflection)
  - Pattern Miner (clustering fuzzy)
  - Distiller com LLM (authoring de conteúdo)
  - Knowledge Librarian (Leiden, compactação)
  - Workflow / BestPractice (abstrações emergentes)

Phase 3
  - Capability Graph
  - Cross-Tenant
  - Online Validation (nó Validation, KM-008)
  - Adaptive Retrieval
```

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
