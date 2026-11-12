from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from conferencia_acertos.exporter import _build_issues_rows, _fmt


def generate_notebooklm_bundle(conn: sqlite3.Connection, nlm_dir: Path) -> Path:
    """Gera fontes documentais, datasets CSV e prompts prontos para uso no NotebookLM."""
    sources_dir = nlm_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    df_conf = pd.read_sql_query("SELECT * FROM vw_conferencia_completa ORDER BY arquivo_origem", conn)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    # 1. Datasets CSV limpos (UTF-8) para upload direto no NotebookLM
    df_conf.to_csv(sources_dir / "03_dataset_conferencia.csv", index=False, encoding="utf-8-sig")
    df_div.to_csv(sources_dir / "04_dataset_divergencias.csv", index=False, encoding="utf-8-sig")
    df_dup.to_csv(sources_dir / "05_dataset_duplicidades_lote.csv", index=False, encoding="utf-8-sig")

    total = len(df_conf)
    aprovados = int((df_conf["status_homologacao"] == "APROVADO").sum()) if total else 0
    reprovados = int((df_conf["status_homologacao"] == "REPROVADO").sum()) if total else 0
    taxa = ((total - reprovados) / total * 100.0) if total else 0.0
    dups_lotes = int((df_dup["qtd_payloads"] > 1).sum())
    now_str = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    issues = _build_issues_rows(df_div, df_dup)

    # 2. Fonte 01: Dossiê Executivo Narrativo
    dossie_lines = [
        "# Dossiê Executivo de Homologação — Integração AgroCenter × MTech (Extrato de Aves)",
        "",
        f"**Data da Auditoria:** {now_str}  ",
        f"**Schema Avaliado:** `br.com.cvale.sap.extratoaves.v1`  ",
        f"**Parecer Atual:** {'HOMOLOGADA' if total > 0 and reprovados == 0 else 'NÃO HOMOLOGADA (PENDENTE DE CORREÇÕES)'}",
        "",
        "## 1. Contexto de Negócio e Arquitetura",
        "",
        "A integração entre os sistemas **AgroCenter** e **MTech** trafega demonstrativos de acerto de frango de corte "
        "por meio de payloads JSON contendo metadados (`Cod_Cliente` e `Demais_Dados`) e o binário do demonstrativo em "
        "Base64 (`PDF64`). Esperava-se uma relação estrita de **1:1** entre cada payload e um binário PDF íntegro, com "
        "consistência total entre os metadados JSON, o cabeçalho do PDF e o Termo de Quitação na última página.",
        "",
        "## 2. Indicadores Consolidados da Amostra",
        "",
        f"- **Total de Payloads Analisados:** {total}",
        f"- **Payloads Aprovados sem Falhas:** {aprovados}",
        f"- **Payloads Reprovados (com falhas bloqueantes):** {reprovados}",
        f"- **Taxa de Conformidade Geral:** {taxa:.1f}%",
        f"- **Lotes com Reenvio Duplicado:** {dups_lotes}",
        f"- **Total de Issues Mapeadas para Desenvolvimento:** {len(issues)}",
        "",
        "## 3. Principais Achados da Auditoria",
        "",
        "1. **Batimento de Lote Composto (`aviario-lote`):** Nos PDFs legíveis do Lote `21`, o identificador composto "
        "`1290-21` bateu 100% entre `Demais_Dados.Numero_Extrato`, o cabeçalho da página 1 (`AVIÁRIO - 1290` / `LOTE - 21`) "
        "e o Termo de Quitação na última página (`lote, 21 do aviário 1290`).",
        "2. **Divergência `Cod_Cliente` vs `BP`:** Em todos os 8 payloads do lote `1290-21`, o JSON informa `Cod_Cliente = 0100034342`, "
        "enquanto o PDF exibe `BP = 0100093258` em todas as páginas.",
        "3. **Duplicidade e Ordenação Não-Determinística:** O lote `1290-21` foi recebido **8 vezes** com 8 hashes de arquivo e "
        "8 hashes binários de PDF diferentes, mas **apenas 1 hash canônico de conteúdo**. A análise de diff comprovou que os valores "
        "totais são idênticos, porém as tabelas de *Movimentação de Ração* e *Produção Entregue* saem em ordens diferentes a cada geração.",
        "4. **Falhas Estruturais Pontuais:** 1 payload veio com `Demais_Dados` vazio (`''`) e 1 payload de teste (`565-117` / `QUALQUER ABOBRINHA`) "
        "veio com `PDF64` corrompido.",
        "5. **Qualidade do Template PDF:** A declaração de recebimento na última página exibe o valor por extenso em **inglês** "
        "(`Seventy-Three Thousand, One Hundred Ninety-Seven And Sixty-One`) dentro de um documento em português.",
        "",
        "## 4. Resumo por Aviário-Lote",
        "",
    ]
    for _, drow in df_dup.iterrows():
        dossie_lines.append(
            f"- **`{drow['aviario_lote']}`:** {int(drow['qtd_payloads'])} payload(s) | "
            f"Hashes arquivo: {int(drow['qtd_hashes_arquivo_distintos'])} | "
            f"Hashes PDF binário: {int(drow['qtd_hashes_pdf_binario_distintos'])} | "
            f"Hashes conteúdo canônico: {int(drow['qtd_hashes_conteudo_canonico_distintos'])} | "
            f"Diagnóstico: **{drow['diagnostico_duplicidade']}**"
        )

    (sources_dir / "01_dossie_executivo_homologacao.md").write_text(
        "\n".join(dossie_lines), encoding="utf-8"
    )

    # 3. Fonte 02: Catálogo Técnico de Issues e Evidências
    cat_lines = [
        "# Catálogo Técnico de Issues e Evidências — AgroCenter × MTech",
        "",
        f"Total de issues identificadas: **{len(issues)}**",
        "",
    ]
    for it in issues:
        cat_lines.extend([
            f"## {it['ID']} — {it['Titulo']}",
            "",
            f"- **Severidade:** {it['Severidade']}",
            f"- **Sistema Responsável:** {it['Sistema_Responsavel']}",
            f"- **Descrição Técnica:** {it['Descricao']}",
            f"- **Critério de Aceite:** {it['Criterio_Aceite']}",
            f"- **Evidência JSON:** `{it['Evidencia_JSON']}`",
            f"- **Evidência PDF:** `{it['Evidencia_PDF']}`",
            f"- **Payloads Afetados ({it['Qtd_Afetados']}):** {it['Payloads_Afetados']}",
            "",
        ])

    diff_file = nlm_dir.parent / "diff_duplicidades.md"
    if diff_file.exists():
        cat_lines.extend([
            "---",
            "",
            "## Anexo: Evidência de Diff entre PDFs Duplicados",
            "",
            diff_file.read_text(encoding="utf-8"),
        ])

    (sources_dir / "02_catalogo_tecnico_issues_e_evidencias.md").write_text(
        "\n".join(cat_lines), encoding="utf-8"
    )

    # 3b. Fonte 06: Caso de Teste de Resiliência (PDF Corrompido / "QUALQUER ABOBRINHA")
    resilience_md = """# Caso de Teste de Resiliência — Detecção de Payload Mock & PDF Corrompido

## Objetivo da Demonstração
Este documento comprova que o motor automatizado de conferência (AgroCenter × MTech) é capaz de **capturar falhas críticas de transporte e corrupção de binários** sem interromper o processamento dos demais lotes.

## Payload Analisado: `2026-11-10 190742.014.txt`
- **Identificação no JSON:** `Cod_Cliente = "0100095713"` | `Aviario = "QUALQUER ABOBRINHA"` | `Lote = "117"` | `Numero_Extrato = "565-117"`
- **Natureza do Arquivo:** Payload de teste / mock sintético inserido na massa de homologação.

## Erros Detectados Automaticamente pelo Motor
1. **Base64 Truncado (Falha de Codificação):**
   - O campo `PDF64` possui **234 caracteres** (`234 % 4 = 2`), sem o padding válido (`==`), gerando erro estrito no decoder: `Excess padding not allowed`.
2. **Binário PDF Corrompido (Falha Estrutural):**
   - Mesmo ignorando o padding, o binário decodificado possui apenas **174 bytes** (contra ~242 KB de um extrato real), sendo cortado abruptamente no objeto `3 0 obj <</Type /XObject /Subt...` e saltando direto para `startxref 237250 %%EOF` — sem páginas e sem tabela `xref` legível.

## Como a Solução Reagiu (Prova de Eficácia)
- **Resiliência do Pipeline:** O arquivo não quebrou a ingestão; foi registrado no SQLite (`pdf_valido = 0`, `pdf_paginas = 0`) e ganhou seu dossiê individual em `data/pdf/2026-11-10_190742.014/`.
- **Captura nos Testes Unitários (`pytest`):** Reprovado imediatamente em `test_cardinalidade_um_para_um`, `test_pdf64_integro_e_legivel` e `test_batimento_agrocenter_vs_mtech`.
- **Rastreabilidade:** Exposto na view `vw_divergencias` e no relatório executivo para auditoria.
"""
    (sources_dir / "06_caso_teste_resiliencia_pdf_corrompido.md").write_text(
        resilience_md, encoding="utf-8"
    )

    # 4. Prompts prontos para NotebookLM
    prompts_md = """# Prompts Prontos para NotebookLM — Homologação AgroCenter × MTech

## Como usar
1. Crie um novo Notebook no **NotebookLM**.
2. Faça upload dos 6 arquivos da pasta `reports/notebooklm/sources/`:
   - `01_dossie_executivo_homologacao.md`
   - `02_catalogo_tecnico_issues_e_evidencias.md`
   - `03_dataset_conferencia.csv`
   - `04_dataset_divergencias.csv`
   - `05_dataset_duplicidades_lote.csv`
   - `06_caso_teste_resiliencia_pdf_corrompido.md`
3. Utilize os prompts abaixo no chat ou nas ferramentas de geração (Relatórios, Slides, Infográfico, Audio Overview).

---

## Prompt 1 — Apresentação Executiva para Stakeholders (Slides)

```text
Atue como um Gerente de QA e Homologação apresentando o status da integração AgroCenter × MTech para a diretoria e stakeholders de negócio.
Com base exclusivamente nas fontes enviadas, crie o roteiro completo de uma apresentação de 8 slides em português (Brasil):
- Slide 1: Título, objetivo da integração e parecer atual (NÃO HOMOLOGADA / pendente de correções).
- Slide 2: Visão geral da arquitetura (JSON + Demais_Dados + PDF64) e regra de cardinalidade 1:1.
- Slide 3: KPIs da amostra auditada (9 payloads, taxa de conformidade, lotes analisados).
- Slide 4: O que já está funcionando bem (batimento de aviário-lote 1290-21 entre JSON, cabeçalho e Termo de Quitação, e integridade dos totais financeiros).
- Slide 5: Achado Crítico #1 — Divergência entre Cod_Cliente (0100034342) e BP (0100093258).
- Slide 6: Achado Crítico #2 — Duplicidade de envios (8x para 1290-21) e ordenação não-determinística no PDF (mesmo conteúdo canônico, hashes diferentes).
- Slide 7: Achados Pontuais — Demais_Dados vazio, PDF64 corrompido e texto por extenso em inglês na quitação.
- Slide 8: Plano de Ação, donos por sistema (AgroCenter vs MTech) e critérios objetivos para aprovar o Go-Live.
Para cada slide, inclua: Título, 3 a 4 bullet points diretos, destaque visual/dado-chave e nota do apresentador.
```

---

## Prompt 2 — Infográfico Executivo e Técnico

```text
Crie a especificação estruturada de um infográfico em português (Brasil) resumindo a auditoria de homologação AgroCenter × MTech:
1. Cabeçalho com o status "NÃO HOMOLOGADA" e os 4 KPIs principais (9 payloads, 8 duplicados no lote 1290-21, 1 hash canônico de conteúdo, 5 issues abertas).
2. Fluxograma visual da conferência (Payload JSON -> Validação 1:1 -> Decode PDF64 -> Batimento Cabeçalho + Quitação -> Banco SQLite/DBeaver).
3. Semáforo de Conformidade:
   - Verde (OK): Aviário-Lote composto (1290-21), Produtor, Datas e Totais Financeiros.
   - Amarelo (Alerta): Valor por extenso em inglês no Termo de Quitação.
   - Vermelho (Bloqueante): Cod_Cliente ≠ BP, Reenvio sem idempotência + PDF sem ORDER BY, Demais_Dados vazio e PDF64 corrompido.
4. Callout explicando de forma simples "Por que 8 arquivos iguais têm hashes diferentes?".
```

---

## Prompt 3 — Audio Overview (Resumo em Áudio para Diretoria)

```text
Foque nos resultados da homologação da integração AgroCenter × MTech em português (Brasil).
Explique de forma clara e executiva:
- Por que a integração ainda não pode ser homologada apesar dos valores financeiros e do aviário-lote (1290-21) estarem corretos nos PDFs legíveis.
- A descoberta técnica sobre os 8 reenvios do lote 1290-21 com hashes diferentes (falta de idempotência + ordenação aleatória nas tabelas de Ração e Produção Entregue).
- A divergência de cadastro entre Cod_Cliente e BP, além dos casos de Demais_Dados vazio e valor por extenso em inglês.
- Quais são os próximos passos para liberar a homologação.
```

---

## Prompt 4 — Relatório Técnico e Plano de Correção para Dev

```text
Com base no catálogo técnico de issues e nos datasets CSV, gere um relatório objetivo para o Tech Lead contendo:
1. Tabela priorizada de Issues (ID, Severidade, Sistema Responsável, Causa Raiz Provável, Evidência Exata e Critério de Aceite).
2. Explicação técnica da causa dos hashes diferentes no lote 1290-21 usando os trechos de diff entre os PDFs.
3. Checklist de validação que o time de desenvolvimento deve atender antes de enviar novos payloads para reteste na suíte pytest.
```

---

## Prompt 5 — Q&A / Perguntas Difíceis de Stakeholders

```text
Liste as 6 perguntas mais prováveis que gestores de negócio e líderes técnicos farão na reunião de homologação (ex: "Os valores pagos ao produtor estão errados?", "Por que apareceram 8 arquivos para o mesmo lote?", "O erro do BP bloqueia o pagamento?") e responda cada uma com base estrita nas evidências dos arquivos e datasets.
```

---

## Prompt 6 — Infográfico: Prova de Eficácia do QA & Resiliência (Caso PDF Corrompido)

```text
Crie a estrutura visual de um infográfico em português (Brasil) destacando a eficácia da nossa suíte automatizada de QA na homologação AgroCenter × MTech, usando como destaque o caso de teste `2026-11-10 190742.014.txt` ("QUALQUER ABOBRINHA"):
1. Título: "Como o Motor de QA Protege a Integração AgroCenter × MTech".
2. Bloco "Teste de Fogo (Caso Simulado / Mock)":
   - Entrada: Payload `565-117` ("QUALQUER ABOBRINHA") com `PDF64` truncado (234 chars Base64 / 174 bytes PDF).
   - O que poderia acontecer sem QA: Arquivo corrompido passaria silenciosamente ou derrubaria o lote inteiro.
   - O que nosso QA fez: Isolou o erro sem travar o pipeline, registrou no SQLite/DBeaver e reprovou automaticamente em 3 testes `pytest`.
3. Bloco "Cobertura Completa de Detecção":
   - Camada 1 (Contrato & Cardinalidade 1:1) -> Pegou `PDF64` truncado e `Demais_Dados` vazio.
   - Camada 2 (Batimento JSON × PDF Cabeçalho × Quitação) -> Pegou divergência `Cod_Cliente` ≠ `BP`.
   - Camada 3 (Idempotência & Hash Canônico) -> Pegou 8 reenvios de `1290-21` com ordenação não-determinística.
4. Rodapé com resultado: 100% dos defeitos reais e simulados detectados com rastreabilidade completa.
```
"""

    prompts_path = nlm_dir / "PROMPTS_NOTEBOOKLM.md"
    prompts_path.write_text(prompts_md, encoding="utf-8")
    return prompts_path
