# Playbook Operacional — Conferência de Acertos (QA & Homologação)

Guia passo a passo para executar a conferência quando chegarem novos payloads, auditar divergências no banco e manter o repositório atualizado.

---

## 1. Pré-requisitos e Ambiente

```bash
# Se o ambiente ainda não estiver sincronizado:
uv sync

# Verificar se Python da venv e pytest respondem:
.venv/bin/python --version
.venv/bin/pytest --version
```

> **Nota:** caso `uv` não esteja no `PATH` da sessão, adicione `export PATH="$HOME/.local/bin:$PATH"` ou use diretamente `.venv/bin/python` e `.venv/bin/pytest`.

---

## 2. Recebendo Novos Payloads

1. Copie os novos arquivos `.txt` ou `.json` para `data/raw/` (pode organizar em subpastas por data/lote, ex.: `data/raw/2026-11-14/`).
2. Se desejar **descartar** um payload antigo da homologação, remova o arquivo correspondente de `data/raw/`.
   - Na próxima execução do pipeline, o registro será automaticamente removido de `db/acertos.db` e de `data/pdf/`.

---

## 3. Execução do Pipeline de Conferência

```bash
.venv/bin/python -m conferencia_acertos.cli run
```

**O que é atualizado automaticamente:**
- `db/acertos.db` (base SQLite para DBeaver)
- `data/pdf/<arquivo>/` (PDF decodificado, `payload.json` resumido e `relatorio_acuracia.md`)
- `data/exports/` (`conferencia_acertos.xlsx`, `conferencia_acertos.csv`, `divergencias_acertos.csv`, `duplicidades_lote.csv`)
- `reports/` (`relatorio_homologacao.md`, `relatorio_homologacao.html`, `issues_dev.md`, `issues_dev.csv`, `diff_duplicidades.md`)
- `reports/notebooklm/` (fontes atualizadas para NotebookLM)

---

## 4. Execução da Suíte de Testes (`pytest`)

```bash
.venv/bin/pytest -v
```

**Como interpretar os resultados:**
- **Testes unitários do motor** (`test_motor_*`, `test_lgpd_*`, `test_data_pdf_*`, `test_consistencia_*`, `test_parse_float_*`, `test_database_*`): devem passar **100%**. Qualquer falha aqui indica regressão no código do motor QA.
- **Testes parametrizados por payload** (`test_contrato_*`, `test_cardinalidade_*`, `test_demais_dados_*`, `test_pdf64_*`, `test_batimento_*`, `test_unicidade_por_aviario_lote`): validam cada arquivo real em `data/raw/`. Falhas aqui indicam **não conformidades na integração MTech × AgroCenter**.

---

## 5. Triagem Rápida no SQLite / DBeaver

Abra `db/acertos.db` no **DBeaver** ou consulte via terminal:

```bash
# Resumo por payload
sqlite3 -header -column db/acertos.db \
  "SELECT arquivo_origem, json_cod_cliente, pdf_bp, json_numero_extrato, qtd_falhas, qtd_alertas, status_homologacao FROM vw_conferencia_completa;"

# Divergências e alertas abertos
sqlite3 -header -column db/acertos.db \
  "SELECT arquivo_origem, regra, status, severidade, valor_json, valor_pdf FROM vw_divergencias;"

# Idempotência e hashes por aviário-lote
sqlite3 -header -column db/acertos.db \
  "SELECT aviario_lote, qtd_payloads, qtd_irns_distintos, qtd_hashes_pdf_binario_distintos, qtd_hashes_conteudo_canonico_distintos, diagnostico_duplicidade FROM vw_duplicidades_lote;"
```

---

## 6. Revisão Executiva e Envio para Desenvolvimento

1. Abra [relatorio_homologacao.html](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/reports/relatorio_homologacao.html) no navegador para visão executiva (use os filtros *Todos / Reprovados / Com Alerta / Aprovados*).
2. Utilize [issues_dev.md](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/reports/issues_dev.md) ou importe [issues_dev.csv](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/reports/issues_dev.csv) no Jira/Azure DevOps.
3. Em caso de duplicidade com hashes binários diferentes, anexe [diff_duplicidades.md](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/reports/diff_duplicidades.md) como evidência para a equipe MTech.

---

## 7. Fluxo de Desenvolvimento com `graphify`

Sempre que alterar código em `src/` ou `tests/`:

```bash
# Atualizar grafo de conhecimento incrementalmente
.venv/bin/graphify update

# Consultar relações/impacto antes de editar
.venv/bin/graphify query "Quais funções dependem de ParsedPayload?"
```

Para inspeção visual da arquitetura de código, abra `graphify-out/graph.html` no navegador.

---

## 8. Troubleshooting Rápido

| Sintoma | Causa Provável | Ação |
| :--- | :--- | :--- |
| `uv: comando não encontrado` | `~/.local/bin` fora do `PATH` | Use `.venv/bin/python` / `.venv/bin/pytest` ou `export PATH="$HOME/.local/bin:$PATH"` |
| `BATIMENTO_COD_CLIENTE_BP` em `FALHA` | `Cod_Cliente` do JSON difere do `BP` do PDF (ou está ausente) | **Bloqueante LGPD:** acionar MTech/AgroCenter antes de expor ao produtor |
| `REENVIO_CONTEUDO_IDENTICO_ORDEM_DIFERENTE` | Mesmo conteúdo com tabelas sem `ORDER BY` ou metadados variáveis | Acionar MTech (ordenar queries/fixar metadados do PDF) e AgroCenter (idempotência por IRN) |
| Payload removido de `data/raw/` ainda aparece | Banco antigo antes da sincronização | Rode `.venv/bin/python -m conferencia_acertos.cli run` |
