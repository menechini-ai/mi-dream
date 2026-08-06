# SDD ledger — plan: docs/superpowers/plans/2026-08-06-phase1-remediation.md

Task 1: done — Documentation + Baseline (deps, langchain-openai, baseline run)
Task 2: done — Stabilization Bug Fixes (reflector fallback, curator dedup, PII, bootstrap imports)
Task 3: done — Test Suite Stabilization (83 passed, 4 skipped)
Task 4: done — DeepAgents Supervisor Real (SDD §6) — create_supervisor + langchain tool factories; 7 tests
Task 5: done — Execution Context in REPL (build_system_prompt, recall_context, sanitized trace save)
Task 6: done — Governance + Pipeline CLI Commands (init/reflect/curator; scheduler await fix)
Task 7: done — Lint + Final Validation (ruff clean, 93 passed, 4 skipped, CLI smoke-tested)
Task 8: done — Knowledge Distiller Fase 1 + DERIVED_FROM + SUPPORTED_BY (115 passed, 4 skipped; SDD v2.2 §4.1)
Task 9: done — INV-001 + INV-002a enforcement: content_hash/fingerprint no ReasoningTrace + check_trace_immutability no Curator + clamp de delta negativo no update_metrics (124 passed, 4 skipped; ruff clean; verificação ao vivo OK). Trigger APOC avaliado e descartado (bug APOC 5.26.29 + Neo4j 5.26).
Task 10: done — Vector recall via neo4j-graphrag (StrategyVectorRetriever/VectorCypherRetriever sobre strategy_embedding, filtros tenant/domain/ACTIVE, fallback list_by_domain; KnowledgeDistiller grava s.embedding no CREATE; cli distill wired com build_embedder). Workaround do bug upstream #540 (_node_embedding_property nunca populado) e do shorthand de map projection (chaves com '.', senão Cypher trata como variável). Verificação ao vivo OK (distill→embedding 1536→promote ACTIVE→search retorna strategy). 135 passed, 4 skipped; ruff clean.
