# Conferência de Acertos (AgroCenter × MTech)

Ferramenta de extração, normalização em SQLite e conferência automatizada (testes unitários + relatório executivo de homologação) para payloads JSON (`br.com.cvale.sap.extratoaves.v1`) contendo demonstrativos em PDF Base64.

## Estrutura

- `data/raw/`: payloads de entrada (`.txt` / `.json`)
- `data/pdf/`: PDFs decodificados a partir de `PDF64`
- `data/exports/`: planilhas `.csv` e `.xlsx` geradas automaticamente
- `db/acertos.db`: banco SQLite pronto para abrir no **DBeaver**
- `reports/relatorio_homologacao.md`: relatório executivo e lista de issues para a equipe de desenvolvimento
- `tests/`: suíte de testes unitários `pytest`
- `.agents/skills/conferencia-acertos/`: skill local do projeto

## Uso Rápido

```bash
# Processar payloads, atualizar SQLite, gerar CSV/XLSX e relatório
uv run python -m conferencia_acertos.cli run

# Executar testes unitários de conferência
uv run pytest -v
```
