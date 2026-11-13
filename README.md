# Conferência de Acertos (MTech × AgroCenter → Produtor)

Plataforma de **QA, auditoria de interoperabilidade e homologação** para os payloads de acerto de aves (`br.com.cvale.sap.extratoaves.v1`) transmitidos do **MTech** para o **AgroCenter** antes da disponibilização ao **produtor**.

---

## Contexto e Regra de Negócio

> Os dados são transmitidos por interface do **MTech** para o **AgroCenter** para que possam ser disponibilizados ao **produtor**.

O motor valida quatro pilares críticos em cada lote:
1. **Segurança & LGPD:** `Cod_Cliente` (JSON) e `BP` (todas as páginas do PDF) devem existir e ser rigorosamente idênticos, evitando expor o extrato de um produtor para outro.
2. **Idempotência & Determinismo (Blockchain-ready):** cada lote composto (`aviario-lote`) deve possuir exatamente **1 IRN único** (`BrimGrowSettlementsIRN`) e **1 hash SHA-256 binário determinístico** de PDF.
3. **Integridade de Contrato & Batimento 1:1:** validação do envelope JSON, `Demais_Dados`, `PDF64` íntegro, lote composto (`Numero_Extrato`), `DataEmissao`, cabeçalho e Termo de Quitação.
4. **Qualidade para o Produtor:** localização PT-BR (data `DD/MM/YYYY` e valor por extenso em português) e consistência zootécnica/financeira.

---

## Stack & Ferramentas

| Camada | Tecnologia / Biblioteca | Papel no Projeto |
| :--- | :--- | :--- |
| **Linguagem & Runtime** | Python `>=3.11` (`uv`) | Execução do pipeline, CLI e testes |
| **Contrato & Validação** | `pydantic >= 2.9.0` | Validação estrutural de `Demais_Dados` (com `extra="allow"`) |
| **Extração & Parsing PDF** | `pypdf >= 5.0.0`, `pdfplumber >= 0.11.4` | Integridade estrutural, extração com `layout=True` e diff |
| **Persistência Analítica** | `sqlite3` (stdlib) | Banco `db/acertos.db` com tabelas e views para **DBeaver** |
| **Dados & Exports** | `pandas >= 2.2.3`, `openpyxl >= 3.1.5` | Geração de CSVs e planilha Excel consolidada |
| **Testes Automatizados** | `pytest >= 8.3.0` | Suíte unitária e parametrizada sobre `data/raw/` |
| **Grafo de Conhecimento** | `graphifyy >= 0.9.108` | Mapeamento AST do código (`graphify-out/`) para desenvolvimento |

---

## Estrutura do Repositório

- `src/conferencia_acertos/`: motor de ingestão, extração, validação, persistência e geração de relatórios
- `tests/`: suíte `pytest` ([test_integracao_acertos.py](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/tests/test_integracao_acertos.py))
- `data/raw/`: payloads de entrada (`.txt` / `.json`, inclusive em subpastas)
- `data/pdf/`: dossiês por payload (`<payload>.pdf`, `payload.json` e `relatorio_acuracia.md`)
- `data/exports/`: `conferencia_acertos.xlsx`, `conferencia_acertos.csv`, `divergencias_acertos.csv`, `duplicidades_lote.csv`
- `db/acertos.db`: banco SQLite pronto para consulta no **DBeaver**
- `reports/`: `relatorio_homologacao.md`, `relatorio_homologacao.html`, `issues_dev.md`, `issues_dev.csv`, `diff_duplicidades.md` e `notebooklm/`
- `docs/`: [ARQUITETURA.md](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/docs/ARQUITETURA.md) e [PLAYBOOK.md](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/docs/PLAYBOOK.md)
- `.agents/skills/`: skills locais ([conferencia-acertos](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/.agents/skills/conferencia-acertos/SKILL.md) e [qa-analista-interfaces](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/.agents/skills/qa-analista-interfaces/SKILL.md))
- `graphify-out/`: grafo de conhecimento do repositório (`graph.html`, `GRAPH_REPORT.md`, `graph.json`)

---

## Uso Rápido

```bash
# 1. Processar payloads de data/raw/, atualizar SQLite, exports e relatórios
.venv/bin/python -m conferencia_acertos.cli run

# 2. Executar suíte de testes unitários e de integração
.venv/bin/pytest -v

# 3. Atualizar ou consultar o grafo de conhecimento (após alterações de código)
.venv/bin/graphify update
.venv/bin/graphify query "Como funciona o batimento Cod_Cliente vs BP?"
```

Para detalhes técnicos e passo a passo operacional, consulte:
- **[docs/ARQUITETURA.md](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/docs/ARQUITETURA.md)** — Stack, fluxo de dados, modelo SQLite e catálogo de regras.
- **[docs/PLAYBOOK.md](file:///home/bruno/Documentos/1_C.VALE/2%20-%20PROJETOS/13%20-%20ConferenciaAcertos/docs/PLAYBOOK.md)** — Playbook operacional de QA para novos payloads, triagem de issues e uso do `graphify`.

---

## Regra de Negócio: Granja × Aviário (Proprietário vs Responsável — `Cod_Cliente` × `BP`)

- Uma **granja** possui **aviários**. Cada aviário possui um **Proprietário** (com seu `cod_BP_Proprietario`), e a granja possui um **Responsável** (integrado, também com seu `cod_BP_Responsavel`).
- A base oficial de referência dessa relação fica em `data/cod_bp/cod_BP_integracao.md` (extraída para `data/cod_bp/cod_BP_integracao.csv` e tabela SQLite `ref_aviario_bp`).
- **Premissa de integração (LGPD):** a coluna/papel de BP utilizada no JSON (`Cod_Cliente`) deve ser **exatamente a mesma** utilizada no PDF (`BP`), evitando divergência entre `cod_BP_Proprietario` e `cod_BP_Responsavel`.
- **Consistência entre reenvios:** reenvios de um mesmo `aviario-lote` são aceitos quando mantêm o mesmo `BrimGrowSettlementsIRN` e o mesmo hash binário SHA-256 do PDF Base64.
