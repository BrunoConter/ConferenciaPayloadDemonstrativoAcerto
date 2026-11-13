# Graph Report - 13 - ConferenciaAcertos  (2026-11-13)

## Corpus Check
- 16 files · ~15,070 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 6, .lock 1)

## Summary
- 185 nodes · 427 edges · 15 communities (11 shown, 4 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 44 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `42ffb2ab`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_integracao_acertos.py
- PDF Extraction
- JSON Payload Parser
- cli.py
- Playbook Operacional — Conferência de Acertos (QA & Homologação)
- run_pipeline
- database.py
- Project Manifest
- Skill: Conferência de Acertos (AgroCenter × MTech)
- Conferência de Acertos (MTech × AgroCenter → Produtor)
- Agente: QA & Analista de Interfaces (MTech × AgroCenter)
- IDEA & Evolução do Projeto

## God Nodes (most connected - your core abstractions)
1. `validate_payload()` - 23 edges
2. `run_pipeline()` - 19 edges
3. `ParsedPayload` - 18 edges
4. `_build_synthetic_valid_pair()` - 16 edges
5. `parse_payload_file()` - 15 edges
6. `extract_pdf_data()` - 14 edges
7. `_build_issues_rows()` - 13 edges
8. `generate_executive_report()` - 12 edges
9. `generate_html_dashboard()` - 12 edges
10. `test_database_exporter_e_notebooklm_e2e()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `Ciclo de Execução (`run_pipeline`)` --references--> `DemaisDadosModel`  [INFERRED]
  docs/ARQUITETURA.md → src/conferencia_acertos/parser.py
- `4. Execução da Suíte de Testes (`pytest`)` --references--> `test_unicidade_por_aviario_lote()`  [INFERRED]
  docs/PLAYBOOK.md → tests/test_integracao_acertos.py
- `Ciclo de Execução (`run_pipeline`)` --references--> `discover_payload_files()`  [INFERRED]
  docs/ARQUITETURA.md → src/conferencia_acertos/cli.py
- `Ciclo de Execução (`run_pipeline`)` --references--> `run_pipeline()`  [INFERRED]
  docs/ARQUITETURA.md → src/conferencia_acertos/cli.py
- `test_resolve_lote_key_e_export_aditivo_opcao_a()` --calls--> `resolve_lote_key()`  [INFERRED]
  tests/test_integracao_acertos.py → src/conferencia_acertos/exporter.py

## Import Cycles
- None detected.

## Communities (15 total, 4 thin omitted)

### Community 0 - "test_integracao_acertos.py"
Cohesion: 0.13
Nodes (19): ParsedPayload, validate_payload(), _build_synthetic_valid_pair(), _get_pdf_data(), _load_all_cases(), test_batimento_agrocenter_vs_mtech(), test_batimento_aviario_por_codigo(), test_bp_divergente_entre_paginas_e_irn_vazio() (+11 more)

### Community 1 - "PDF Extraction"
Cohesion: 0.13
Nodes (12): resolve_lote_key(), compute_canonical_text_hash(), extract_pdf_data(), _parse_float(), _parse_int(), PdfExtractedData, _search(), _normalize_text() (+4 more)

### Community 2 - "JSON Payload Parser"
Cohesion: 0.14
Nodes (10): _compute_sha256(), _decode_pdf64(), DemaisDadosModel, _error_payload(), _parse_demais_dados(), parse_payload_file(), _read_text_with_fallback(), _split_numero_extrato() (+2 more)

### Community 4 - "cli.py"
Cohesion: 0.14
Nodes (12): main(), _append_bp_diag_section(), _build_issues_rows(), export_tabular(), _filter_inconsistent_resends(), _fmt(), generate_duplicity_diff_report(), generate_executive_report() (+4 more)

### Community 5 - "Playbook Operacional — Conferência de Acertos (QA & Homologação)"
Cohesion: 0.17
Nodes (10): 1. Pré-requisitos e Ambiente, 2. Recebendo Novos Payloads, 3. Execução do Pipeline de Conferência, 4. Execução da Suíte de Testes (`pytest`), 5. Triagem Rápida no SQLite / DBeaver, 6. Revisão Executiva e Envio para Desenvolvimento, 7. Fluxo de Desenvolvimento com `graphify`, 8. Troubleshooting Rápido (+2 more)

### Community 6 - "run_pipeline"
Cohesion: 0.15
Nodes (10): 1. Fluxo de Dados (End-to-End), 2. Módulos e Responsabilidades, 3. Modelo de Dados SQLite (`db/acertos.db`), 4. Catálogo de Regras Conferidas, 5. Governança com `graphify` e Agentes Locais, Arquitetura e Funcionamento — Conferência de Acertos, Ciclo de Execução (`run_pipeline`), discover_payload_files() (+2 more)

### Community 7 - "database.py"
Cohesion: 0.21
Nodes (8): _ensure_current_schema(), init_db(), upsert_record(), ValidationResult, test_database_exporter_e_notebooklm_e2e(), test_query_issues_filtros_e_agrupamentos(), test_reenvio_consistente_nao_gera_issue_e_inconsistente_gera(), test_vw_diagnostico_cod_cliente_bp()

### Community 10 - "Skill: Conferência de Acertos (AgroCenter × MTech)"
Cohesion: 0.50
Nodes (3): Fluxo Padrão de Execução, Regras de Negócio Conferidas, Skill: Conferência de Acertos (AgroCenter × MTech)

### Community 11 - "Conferência de Acertos (MTech × AgroCenter → Produtor)"
Cohesion: 0.33
Nodes (5): Conferência de Acertos (MTech × AgroCenter → Produtor), Contexto e Regra de Negócio, Estrutura do Repositório, Stack & Ferramentas, Uso Rápido

### Community 12 - "Agente: QA & Analista de Interfaces (MTech × AgroCenter)"
Cohesion: 0.50
Nodes (3): Agente: QA & Analista de Interfaces (MTech × AgroCenter), Regra de Negócio Central, Roteiro de Análise

### Community 13 - "IDEA & Evolução do Projeto"
Cohesion: 0.50
Nodes (3): Como a Ideia Evoluiu, IDEA & Evolução do Projeto, Visão Original

## Knowledge Gaps
- **1 isolated node(s):** `conferencia-acertos`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 75 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `test_unicidade_por_aviario_lote()` connect `Playbook Operacional — Conferência de Acertos (QA & Homologação)` to `test_integracao_acertos.py`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `validate_payload()` (e.g. with `test_batimento_agrocenter_vs_mtech()` and `test_batimento_aviario_por_codigo()`) actually correct?**
  _`validate_payload()` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `conferencia-acertos` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_integracao_acertos.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12701612903225806 - nodes in this community are weakly interconnected._
- **Why does `run_pipeline()` connect `run_pipeline` to `test_integracao_acertos.py`, `PDF Extraction`, `JSON Payload Parser`, `cli.py`, `database.py`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `parse_payload_file()` (e.g. with `_load_all_cases()` and `test_parse_payload_encoding_bom_e_latin1()`) actually correct?**
  _`parse_payload_file()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `PDF Extraction` be split into smaller, more focused modules?**
  _Cohesion score 0.12923076923076923 - nodes in this community are weakly interconnected._