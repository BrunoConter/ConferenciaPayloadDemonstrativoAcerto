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
    dups_lotes = (
        int(((df_dup["qtd_irns_distintos"] > 1) | (df_dup["qtd_hashes_pdf_binario_distintos"] > 1)).sum())
        if not df_dup.empty
        else 0
    )
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
        f"- **Lotes com Inconsistência de IRN ou Hash PDF64:** {dups_lotes}",
        f"- **Total de Issues Mapeadas para Desenvolvimento:** {len(issues)}",
        "",
        "## 3. Principais Achados da Auditoria (Dinâmico)",
        "",
        *(
            ["- Nenhuma falha ou alerta identificado na amostra atual."]
            if not issues
            else [
                f"- **{it['ID']} ({it['Severidade']} | {it['Status']}):** {it['Descricao']} *(Afetados: {it['Qtd_Afetados']})*"
                for it in issues
            ]
        ),
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
2. Faça upload dos 7 arquivos da pasta `reports/notebooklm/sources/`:
   - `01_dossie_executivo_homologacao.md`
   - `02_catalogo_tecnico_issues_e_evidencias.md`
   - `03_dataset_conferencia.csv`
   - `04_dataset_divergencias.csv`
   - `05_dataset_duplicidades_lote.csv`
   - `06_caso_teste_resiliencia_pdf_corrompido.md`
   - `07_log_execucoes_interface_e_recepcao_13_11.md`
3. Utilize os prompts abaixo no chat ou nas ferramentas de geração (Relatórios, Slides, Infográfico, Audio Overview).

---

## Prompt 1 — Apresentação Executiva para Stakeholders (Slides)

```text
Atue como um Gerente de QA e Homologação apresentando o status da integração AgroCenter × MTech para a diretoria e stakeholders de negócio.
Com base exclusivamente nas fontes enviadas, crie o roteiro completo de uma apresentação de 8 slides em português (Brasil):
- Slide 1: Título, objetivo da integração e parecer atual (NÃO HOMOLOGADA / pendente de correções).
- Slide 2: Visão geral da arquitetura (JSON + Demais_Dados + PDF64) e regra de cardinalidade 1:1.
- Slide 3: KPIs da amostra auditada (47 payloads, 40 lotes únicos, 63,8% de conformidade geral, 17 payloads reprovados) e cobertura das execuções de 13/11 (40/40 lotes recebidos na interface manual vs. Status 200 sem entrega na interface automatizada das 16:18).
- Slide 4: O que já está funcionando bem (batimento dos 40 aviários-lote entre JSON, cabeçalho e Termo de Quitação, e integridade dos totais financeiros).
- Slide 5: Achado Crítico #1 — Divergência entre Cod_Cliente e BP (7 pares distintos em 17 ocorrências: Proprietário do Aviário no PDF vs. Responsável pela Granja no JSON).
- Slide 6: Achado Crítico #2 — Duplicidade de envios (8x para 1290-21 com 1 IRN e 1 hash canônico, mas 8 hashes binários de PDF distintos).
- Slide 7: Achados Pontuais e Infraestrutura — Data em formato americano (MM/DD/YYYY), valor por extenso em inglês na quitação e execução automatizada das 16:18 com Status 200 não recebida no endpoint.
- Slide 8: Plano de Ação, donos por sistema (AgroCenter vs MTech) e critérios objetivos para aprovar o Go-Live.
Para cada slide, inclua: Título, 3 a 4 bullet points diretos, destaque visual/dado-chave e nota do apresentador.
```

---

## Prompt 2 — Infográfico Executivo e Técnico

```text
Crie a especificação estruturada de um infográfico em português (Brasil) resumindo a auditoria de homologação AgroCenter × MTech:
1. Cabeçalho com o status "NÃO HOMOLOGADA" e os 4 KPIs principais (47 payloads / 40 lotes únicos, 63,8% conformidade, 17 reprovados por divergência de BP, 4 issues mapeadas).
2. Fluxograma visual da conferência (Interface MTech -> Endpoint AgroCenter data/raw/ -> Validação 1:1 -> Decode PDF64 -> Batimento Cabeçalho + Quitação -> Banco SQLite/DBeaver).
3. Semáforo de Conformidade:
   - Verde (OK): 40/40 lotes compostos recebidos em 13/11, Produtor e Totais Financeiros consistentes.
   - Amarelo (Alerta): Data em formato americano (MM/DD/YYYY) e valor por extenso em inglês no Termo de Quitação.
   - Vermelho (Bloqueante): Cod_Cliente ≠ BP (7 pares / 17 ocorrências), 8 PDFs não-determinísticos para o lote 1290-21 e execução automatizada das 16:18 com Status 200 não recebida no endpoint.
4. Callout explicando de forma simples "Por que 8 arquivos do lote 1290-21 têm hashes binários diferentes mesmo com o mesmo conteúdo?".
```

---

## Prompt 3 — Audio Overview (Resumo em Áudio para Diretoria)

```text
Foque nos resultados da homologação da integração AgroCenter × MTech em português (Brasil).
Explique de forma clara e executiva:
- Por que a integração ainda não pode ser homologada apesar dos 40 lotes testados em 13/11 terem sido recebidos com valores financeiros e aviário-lote corretos.
- A descoberta técnica sobre a divergência de cadastro entre Cod_Cliente (Responsável pela Granja) e BP (Proprietário do Aviário) em 7 pares distintos (17 ocorrências).
- Os 8 reenvios do lote 1290-21 com hashes binários diferentes (PDF não-determinístico com mesmo conteúdo canônico).
- O alerta de infraestrutura da execução automatizada das 16:18 (Status 200 sem entrega no endpoint) e os próximos passos para liberar a homologação.
```

---

## Prompt 4 — Relatório Técnico e Plano de Correção para Dev

```text
Com base no catálogo técnico de issues, nos datasets CSV e no log de execuções de 13/11, gere um relatório objetivo para o Tech Lead contendo:
1. Tabela priorizada de Issues (ID, Severidade, Sistema Responsável, Causa Raiz Provável, Evidência Exata e Critério de Aceite).
2. Explicação técnica da causa dos hashes diferentes no lote 1290-21 e da diferença entre Proprietário do Aviário e Responsável pela Granja nos 7 pares de BP.
3. Investigação recomendada para a interface automatizada `Export BRIM Demons Resultado Frango Res V3` (Status 200 às 16:18 sem recepção no endpoint).
4. Checklist de validação que o time de desenvolvimento deve atender antes de enviar novos payloads para reteste na suíte pytest.
```

---

## Prompt 5 — Q&A / Perguntas Difíceis de Stakeholders

```text
Liste as 6 perguntas mais prováveis que gestores de negócio e líderes técnicos farão na reunião de homologação (ex: "Os valores pagos ao produtor estão errados?", "Todos os 40 lotes de 13/11 chegaram?", "O erro de BP entre Proprietário e Responsável bloqueia o pagamento?", "Por que a execução automatizada das 16:18 deu Status 200 mas não chegou?") e responda cada uma com base estrita nas evidências dos arquivos e datasets.
```

---

## Prompt 6 — Infográfico: Prova de Eficácia do QA & Resiliência (Caso PDF Corrompido)

```text
Crie a estrutura visual de um infográfico em português (Brasil) destacando a eficácia da nossa suíte automatizada de QA na homologação AgroCenter × MTech, usando como destaque o caso de teste simulado `2026-11-10 190742.014.txt` ("QUALQUER ABOBRINHA") e o lote de 40 payloads de 13/11:
1. Título: "Como o Motor de QA Protege a Integração AgroCenter × MTech".
2. Bloco "Teste de Fogo (Caso Simulado / Mock)":
   - Entrada: Payload `565-117` ("QUALQUER ABOBRINHA") com `PDF64` truncado (234 chars Base64 / 174 bytes PDF).
   - O que poderia acontecer sem QA: Arquivo corrompido passaria silenciosamente ou derrubaria o lote inteiro.
   - O que nosso QA fez: Isolou o erro sem travar o pipeline, registrou no SQLite/DBeaver e reprovou automaticamente na suíte `pytest`.
3. Bloco "Cobertura Completa de Detecção":
   - Camada 1 (Contrato & Cardinalidade 1:1) -> Detecta `PDF64` truncado e `Demais_Dados` vazio.
   - Camada 2 (Batimento JSON × PDF Cabeçalho × Quitação × `ref_aviario_bp`) -> Detectou os 7 pares de divergência `Cod_Cliente` ≠ `BP`.
   - Camada 3 (Idempotência & Hash Canônico) -> Detectou 8 reenvios de `1290-21` com PDF não-determinístico.
4. Rodapé com resultado: 40/40 lotes de 13/11 reconciliados e 100% dos defeitos detectados com rastreabilidade completa.
```
"""

    prompts_path = nlm_dir / "PROMPTS_NOTEBOOKLM.md"
    prompts_path.write_text(prompts_md, encoding="utf-8")
    return prompts_path
