---
name: conferencia-acertos
description: Processa novos payloads JSON (AgroCenter x MTech) em data/raw/, atualiza o banco SQLite para o DBeaver, executa a suíte de testes unitários pytest e gera o relatório executivo de homologação com issues para desenvolvimento.
---

# Skill: Conferência de Acertos (AgroCenter × MTech)

Use esta skill sempre que o usuário trouxer novos arquivos de payload em `data/raw/`, pedir para atualizar a base do DBeaver, rodar a conferência dos dados ou gerar/atualizar o relatório executivo de homologação e issues para a equipe de desenvolvimento.

## Fluxo Padrão de Execução

1. **Verificar novos arquivos em `data/raw/`**:
   - Aceita arquivos `.txt` ou `.json` (inclusive em subpastas) no padrão `Schema: "br.com.cvale.sap.extratoaves.v1"`.
2. **Rodar o pipeline de ingestão, banco SQLite, exports e relatório**:
   ```bash
   .venv/bin/python -m conferencia_acertos.cli run
   ```
   Isso sincroniza (incluindo remoção de órfãos) e atualiza:
   - `db/acertos.db` (tabelas `payloads`, `acertos_json`, `acertos_pdf`, `validacoes` e views `vw_conferencia_completa`, `vw_divergencias` e `vw_duplicidades_lote`)
   - `data/pdf/<nome_payload>/` (subpasta por payload contendo `<nome_payload>.pdf`, `payload.json` e `relatorio_acuracia.md`)
   - `data/exports/conferencia_acertos.xlsx`, `conferencia_acertos.csv`, `divergencias_acertos.csv` e `duplicidades_lote.csv`
   - `reports/relatorio_homologacao.md`, `relatorio_homologacao.html`, `issues_dev.csv`, `issues_dev.md` e `diff_duplicidades.md`
   - `reports/notebooklm/` (fontes Markdown, datasets CSV e `PROMPTS_NOTEBOOKLM.md` prontos para NotebookLM)
3. **Executar a suíte de testes unitários (`pytest`)**:
   ```bash
   .venv/bin/pytest -v
   ```
   - Os testes parametrizados validam automaticamente cada payload em `data/raw/` (incluindo cardinalidade `1:1`, lote composto `aviario-lote`, `BP` multi-página, consistência zootécnica/financeira e unicidade de IRN/hash binário).
4. **Atualizar o grafo de conhecimento (`graphify`) se houve mudança de código**:
   ```bash
   .venv/bin/graphify update
   ```
5. **Consultar divergências rapidamente via SQLite**:
   ```bash
   sqlite3 db/acertos.db "SELECT arquivo_origem, regra, status, severidade, valor_json, valor_pdf FROM vw_divergencias;"
   ```

## Regras de Negócio Conferidas

- **JSON Raiz e Contrato:** `Schema` em `SUPPORTED_SCHEMAS` e `Data` não vazio.
- **Cardinalidade `1:1`:** exatamente 1 item em `Data` correspondendo a 1 binário PDF íntegro.
- **`Demais_Dados` e Lote Composto (`aviario-lote`):** `Demais_Dados` válido, `BrimGrowSettlementsIRN` não vazio, `Numero_Extrato` no formato `<aviario>-<lote>` consistente com `Lote`.
- **`PDF64`:** Base64 válido, assinatura `%PDF`, abertura sem erros e texto extraível.
- **Batimento AgroCenter × MTech (LGPD & Integridade):**
  - `BP` consistente em todas as páginas do PDF e **rigorosamente igual** a `Cod_Cliente` (JSON) — ambos obrigatórios
  - `Aviario` (JSON) == `PRODUTOR` ou código `AVIÁRIO` (PDF)
  - `Numero_Extrato` (`aviario-lote`) == cabeçalho `AVIÁRIO`/`LOTE` (pág. 1) **e** Termo de Quitação (última pág.)
  - `DataEmissao` (JSON) == `DATA` (PDF)
- **Consistência Zootécnica/Financeira & Localização:**
  - `aves_abatidas <= aves_alojadas`, `mortalidade_pct + viabilidade_pct ≈ 100%` e `valor_liquido <= valor_lote`
  - Alertas de localização PT-BR: `PDF_DATA_FORMATO_EUA` (`MM/DD/YYYY`) e `PDF_VALOR_EXTENSO_IDIOMA` (extenso em inglês)
