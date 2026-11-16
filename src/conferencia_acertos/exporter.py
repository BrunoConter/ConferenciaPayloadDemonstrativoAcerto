from __future__ import annotations

import difflib
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pdfplumber

from conferencia_acertos.parser import ParsedPayload
from conferencia_acertos.pdf_extractor import PdfExtractedData
from conferencia_acertos.validator import ValidationResult


def _fmt(val: object, default: str = "-") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val):
        return default
    s = str(val).strip()
    return s if s else default


def resolve_lote_key(payload: ParsedPayload, pdf_data: PdfExtractedData) -> str:
    """Resolve a chave de pasta agnóstica ao arquivo de origem: <aviario-lote> ou fallback."""
    raw_key = None
    if payload.demais_dados and payload.demais_dados.Numero_Extrato:
        raw_key = payload.demais_dados.Numero_Extrato.strip()
    elif pdf_data.aviario_lote_composto_pdf:
        raw_key = pdf_data.aviario_lote_composto_pdf.strip()
    elif payload.extrato_aviario and payload.extrato_lote:
        raw_key = f"{payload.extrato_aviario}-{payload.extrato_lote}"
    else:
        raw_key = f"sem_lote_{payload.sha256_arquivo[:8]}"

    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", raw_key).strip("_")
    return sanitized or f"sem_lote_{payload.sha256_arquivo[:8]}"


def export_payload_bundle(
    bundle_dir: Path,
    lote_key: str,
    payload: ParsedPayload,
    pdf_data: PdfExtractedData,
    validations: list[ValidationResult],
) -> Path | None:
    """Cria/atualiza por adição a subpasta data/pdf/<aviario-lote>/ com PDF(s), payload.json e relatorio_acuracia.md."""
    bundle_dir.mkdir(parents=True, exist_ok=True)

    pdf_saved_path: Path | None = None
    if payload.pdf_bytes and payload.pdf_base64_valido and pdf_data.pdf_valido:
        pdf_hash8 = (pdf_data.pdf_bytes_sha256 or payload.sha256_arquivo)[:8]
        pdf_saved_path = bundle_dir / f"{lote_key}_{pdf_hash8}.pdf"
        if not pdf_saved_path.exists():
            pdf_saved_path.write_bytes(payload.pdf_bytes)

    ocorrencia_obj = {
        "arquivo_origem": payload.arquivo_origem,
        "arquivo_pai": payload.caminho_origem.name,
        "sha256_arquivo": payload.sha256_arquivo,
        "schema_versao": payload.schema_versao,
        "cardinalidade": {
            "qtd_itens_data": payload.qtd_itens_data,
            "item_indice": payload.item_indice,
            "esperado_1_para_1_por_item": payload.qtd_itens_data >= 1 and pdf_saved_path is not None,
        },
        "Cod_Cliente": payload.cod_cliente,
        "Demais_Dados_valido": payload.demais_dados_valido,
        "Demais_Dados": payload.demais_dados.model_dump() if payload.demais_dados else payload.raw_demais_dados,
        "Aviario_Lote_decomposto": {
            "aviario": payload.extrato_aviario,
            "lote": payload.extrato_lote,
        },
        "PDF64_resumo": {
            "base64_chars": payload.pdf64_len,
            "base64_valido": payload.pdf_base64_valido,
            "pdf_valido": pdf_data.pdf_valido,
            "pdf_paginas": pdf_data.pdf_paginas,
            "pdf_bytes": len(payload.pdf_bytes) if payload.pdf_bytes else 0,
            "pdf_bytes_sha256": pdf_data.pdf_bytes_sha256,
            "pdf_texto_sha256": pdf_data.pdf_texto_sha256,
            "pdf_texto_canonico_sha256": pdf_data.pdf_texto_canonico_sha256,
            "arquivo_pdf": pdf_saved_path.name if pdf_saved_path else None,
            "erro": payload.pdf_base64_erro or pdf_data.pdf_erro,
        },
    }

    payload_json_path = bundle_dir / "payload.json"
    ocorrencias: list[dict[str, object]] = []
    if payload_json_path.exists():
        try:
            existing = json.loads(payload_json_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("ocorrencias"), list):
                ocorrencias = [
                    o for o in existing["ocorrencias"]
                    if isinstance(o, dict) and o.get("arquivo_origem") != payload.arquivo_origem
                ]
        except Exception:
            ocorrencias = []
    ocorrencias.append(ocorrencia_obj)

    payload_json_path.write_text(
        json.dumps(
            {
                "aviario_lote": lote_key,
                "qtd_ocorrencias": len(ocorrencias),
                "ocorrencias": ocorrencias,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    total_regras = len(validations)
    ok_count = sum(1 for v in validations if v.status == "OK")
    falha_count = sum(1 for v in validations if v.status == "FALHA")
    alerta_count = sum(1 for v in validations if v.status == "ALERTA")
    acuracia_pct = (ok_count / total_regras * 100.0) if total_regras else 0.0

    aviario_lote_cab = (
        f"{pdf_data.aviario_codigo}-{pdf_data.lote_pdf}"
        if pdf_data.aviario_codigo and pdf_data.lote_pdf
        else "-"
    )
    aviario_lote_quit = (
        f"{pdf_data.quitacao_aviario}-{pdf_data.quitacao_lote}"
        if pdf_data.quitacao_aviario and pdf_data.quitacao_lote
        else "-"
    )

    section_lines = [
        f"## Ocorrência #{len(ocorrencias)} — `{payload.arquivo_origem}`",
        "",
        f"- **Acurácia (Regras OK / Total):** **{acuracia_pct:.1f}%** ({ok_count}/{total_regras})",
        f"- **Falhas Bloqueantes:** {falha_count} | **Alertas:** {alerta_count}",
        f"- **Cardinalidade (`Data` ↔ PDF):** item {payload.item_indice}/{payload.qtd_itens_data} | PDF válido: {'Sim' if pdf_saved_path else 'Não'}",
        f"- **PDF Gerado:** `{pdf_saved_path.name if pdf_saved_path else 'Não gerado (PDF inválido/corrompido)'}`",
        f"- **SHA-256 PDF:** `{pdf_data.pdf_bytes_sha256 or '-'}`",
        "",
        "### Comparativo Chave (Payload JSON × Binário PDF)",
        "",
        "| Campo | Payload JSON | PDF (Cabeçalho) | PDF (Quitação) |",
        "| :--- | :--- | :--- | :--- |",
        f"| **BP / Cod_Cliente** | `{payload.cod_cliente or '-'}` | `{pdf_data.bp or '-'}` | `{', '.join(pdf_data.bps_encontrados) if pdf_data.bps_encontrados else '-'}` |",
        f"| **Aviário-Lote Composto** | `{payload.demais_dados.Numero_Extrato if payload.demais_dados else '-'}` | `{aviario_lote_cab}` | `{aviario_lote_quit}` |",
        f"| **Produtor / Aviário** | `{payload.demais_dados.Aviario if payload.demais_dados else '-'}` | `{pdf_data.produtor or '-'}` | `{pdf_data.produtor or '-'}` |",
        f"| **Data Emissão** | `{payload.demais_dados.DataEmissao if payload.demais_dados else '-'}` | `{pdf_data.data_pdf or '-'}` | `-` |",
        "",
        "### Detalhamento das Regras Conferidas",
        "",
        "| Regra | Status | Severidade | Valor JSON | Valor PDF | Detalhe |",
        "| :--- | :---: | :---: | :--- | :--- | :--- |",
    ]
    for v in validations:
        section_lines.append(
            f"| `{v.regra}` | **{v.status}** | {v.severidade} | `{v.valor_json or '-'}` | `{v.valor_pdf or '-'}` | {v.detalhe} |"
        )
    section_lines.append("")

    rel_path = bundle_dir / "relatorio_acuracia.md"
    if len(ocorrencias) == 1 or not rel_path.exists():
        header = [
            f"# Relatório de Acurácia — Lote `{lote_key}`",
            "",
        ]
        rel_path.write_text("\n".join(header + section_lines), encoding="utf-8")
    else:
        existing_md = rel_path.read_text(encoding="utf-8").rstrip()
        rel_path.write_text(
            existing_md + "\n\n---\n\n" + "\n".join(section_lines),
            encoding="utf-8",
        )

    return pdf_saved_path


def export_tabular(conn: sqlite3.Connection, exports_dir: Path) -> tuple[Path, Path, Path]:
    """Exporta as views do SQLite para CSV e XLSX."""
    exports_dir.mkdir(parents=True, exist_ok=True)

    df_conf = pd.read_sql_query("SELECT * FROM vw_conferencia_completa ORDER BY arquivo_origem", conn)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    csv_conf_path = exports_dir / "conferencia_acertos.csv"
    csv_div_path = exports_dir / "divergencias_acertos.csv"
    csv_dup_path = exports_dir / "duplicidades_lote.csv"
    xlsx_path = exports_dir / "conferencia_acertos.xlsx"

    df_conf.to_csv(csv_conf_path, index=False, encoding="utf-8-sig")
    df_div.to_csv(csv_div_path, index=False, encoding="utf-8-sig")
    df_dup.to_csv(csv_dup_path, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_conf.to_excel(writer, sheet_name="Conferencia", index=False)
        df_div.to_excel(writer, sheet_name="Divergencias", index=False)
        df_dup.to_excel(writer, sheet_name="Duplicidades_Lote", index=False)

    return csv_conf_path, csv_div_path, xlsx_path


def generate_executive_report(conn: sqlite3.Connection, report_path: Path) -> Path:
    """Gera o relatório executivo de homologação e lista de issues para dev."""
    report_path.parent.mkdir(parents=True, exist_ok=True)

    df_conf = pd.read_sql_query("SELECT * FROM vw_conferencia_completa ORDER BY arquivo_origem", conn)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    total = len(df_conf)
    aprovados = int((df_conf["status_homologacao"] == "APROVADO").sum()) if total else 0
    com_alerta = int((df_conf["status_homologacao"] == "APROVADO_COM_ALERTA").sum()) if total else 0
    reprovados = int((df_conf["status_homologacao"] == "REPROVADO").sum()) if total else 0
    taxa_aprovacao = ((aprovados + com_alerta) / total * 100.0) if total else 0.0

    parecer = (
        "HOMOLOGADA"
        if total > 0 and reprovados == 0
        else "NÃO HOMOLOGADA (PENDENTE DE CORREÇÕES)"
    )
    now_str = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S")

    lines: list[str] = [
        "# Relatório Executivo de Homologação — Integração AgroCenter × MTech",
        "",
        f"**Gerado em:** {now_str}  ",
        f"**Parecer Geral:** **{parecer}**",
        "",
        "---",
        "",
        "## 1. Sumário Executivo",
        "",
        "| Indicador | Valor |",
        "| :--- | ---: |",
        f"| Total de Payloads Analisados | {total} |",
        f"| Aprovados (Sem Ressalvas) | {aprovados} |",
        f"| Aprovados com Alerta | {com_alerta} |",
        f"| Reprovados (Com Falhas Bloqueantes) | {reprovados} |",
        f"| Taxa de Conformidade (Sem Falhas) | {taxa_aprovacao:.1f}% |",
        "",
        "---",
        "",
        "## 2. Matriz de Conferência por Payload",
        "",
        "| Arquivo | `Data` (1:1) | `Cod_Cliente` (JSON) | `BP` (PDF) | `Aviário-Lote` (JSON) | `Aviário-Lote` (PDF Cab. / Quit.) | `Demais_Dados` | PDF Íntegro | Falhas | Alertas | Status |",
        "| :--- | :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for _, row in df_conf.iterrows():
        dd_ok = "OK" if row["demais_dados_valido"] == 1 else "FALHA"
        pdf_ok = "OK" if row["pdf_valido"] == 1 else "FALHA"
        qtd_data = int(row["qtd_itens_data"]) if not pd.isna(row["qtd_itens_data"]) else 0
        item_idx = int(row["item_indice"]) if not pd.isna(row["item_indice"]) else 1
        pdf_flag = "1" if row["pdf_valido"] == 1 else "0"
        card_str = f"1:{pdf_flag}" if qtd_data == 1 else f"1:{pdf_flag} ({item_idx}/{qtd_data})"
        av_lote_cab = (
            f"{_fmt(row['pdf_aviario_codigo'])}-{_fmt(row['pdf_lote'])}"
            if _fmt(row["pdf_aviario_codigo"]) != "-"
            else "-"
        )
        av_lote_quit = (
            f"{_fmt(row['pdf_quitacao_aviario'])}-{_fmt(row['pdf_quitacao_lote'])}"
            if _fmt(row["pdf_quitacao_aviario"]) != "-"
            else "-"
        )
        lines.append(
            f"| `{row['arquivo_origem']}` | {card_str} | `{_fmt(row['json_cod_cliente'])}` | "
            f"`{_fmt(row['pdf_bp'])}` | `{_fmt(row['json_numero_extrato'])}` | "
            f"`{av_lote_cab}` / `{av_lote_quit}` | {dd_ok} | {pdf_ok} | "
            f"{int(row['qtd_falhas'])} | {int(row['qtd_alertas'])} | **{row['status_homologacao']}** |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Análise de Duplicidades por Aviário-Lote (Idempotência e Hashes)",
        "",
        "| Aviário-Lote | Qtd Payloads | IRNs Distintos | Hashes Arquivo | Hashes PDF Binário | Hashes Conteúdo Canônico | Diagnóstico |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for _, drow in df_dup.iterrows():
        lines.append(
            f"| `{drow['aviario_lote']}` | {int(drow['qtd_payloads'])} | "
            f"{int(drow['qtd_irns_distintos'])} | "
            f"{int(drow['qtd_hashes_arquivo_distintos'])} | "
            f"{int(drow['qtd_hashes_pdf_binario_distintos'])} | "
            f"{int(drow['qtd_hashes_conteudo_canonico_distintos'])} | "
            f"**{drow['diagnostico_duplicidade']}** |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 4. Issues Identificadas para a Equipe de Desenvolvimento",
        "",
    ])

    dups_only = _filter_inconsistent_resends(df_dup)
    issue_num = 1
    if not dups_only.empty:
        for _, drow in dups_only.iterrows():
            lines.extend([
                f"### Issue #{issue_num} — `INCONSISTENCIA_IRN_OU_PDF64` (FALHA | Severidade: ALTA)",
                "",
                (
                    f"- **Descrição:** O aviário-lote `{drow['aviario_lote']}` recebeu **{int(drow['qtd_payloads'])}** "
                    f"envio(s) com divergência de IRN ou hash binário do PDF Base64 "
                    f"(IRNs distintos: {int(drow['qtd_irns_distintos'])}, hashes de arquivo: {int(drow['qtd_hashes_arquivo_distintos'])}, "
                    f"hashes binários de PDF Base64: {int(drow['qtd_hashes_pdf_binario_distintos'])}, "
                    f"hashes de conteúdo canônico: {int(drow['qtd_hashes_conteudo_canonico_distintos'])}). "
                    f"Diagnóstico: `{drow['diagnostico_duplicidade']}` — reenvios do mesmo lote são aceitos, mas "
                    f"exigem o mesmo IRN e o mesmo hash binário SHA-256 do PDF Base64."
                ),
                f"- **Payloads Afetados ({int(drow['qtd_payloads'])}):** {drow['arquivos']}",
                "",
            ])
            issue_num += 1

    if df_div.empty and dups_only.empty:
        lines.append("Nenhuma divergência ou alerta identificado nos payloads analisados.")
    elif not df_div.empty:
        for item in _build_issues_rows(df_div, pd.DataFrame(), split_by_pair=False):
            lines.extend([
                f"### Issue #{issue_num} — {item['Titulo']} ({item['Status']} | Severidade: {item['Severidade']})",
                "",
                f"- **Descrição:** {item['Descricao']}",
                f"- **Evidência JSON:** `{item['Evidencia_JSON']}`",
                f"- **Evidência PDF:** `{item['Evidencia_PDF']}`",
                f"- **Lotes Afetados:** {item['Lotes_Afetados']}",
                f"- **Payloads Afetados ({item['Qtd_Afetados']}):** {item['Payloads_Afetados']}",
                "",
            ])
            issue_num += 1

    _append_bp_diag_section(lines, conn, heading_level="###")

    lines.extend([
        "---",
        "",
        "## 5. Artefatos de Apoio",
        "",
        "- **Base SQLite (DBeaver):** `db/acertos.db` (views `vw_conferencia_completa`, `vw_divergencias` e `vw_duplicidades_lote`)",
        "- **Dossiês por Payload:** `data/pdf/<payload>/` (`<payload>.pdf`, `payload.json` e `relatorio_acuracia.md`)",
        "- **Planilha Consolidada:** `data/exports/conferencia_acertos.xlsx`",
        "- **CSVs:** `data/exports/conferencia_acertos.csv`, `data/exports/divergencias_acertos.csv` e `data/exports/duplicidades_lote.csv`",
        "",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _filter_inconsistent_resends(df_dup: pd.DataFrame) -> pd.DataFrame:
    """Filtra apenas lotes com IRN distinto (>1) ou hash binário de PDF64 distinto (>1)."""
    if df_dup.empty:
        return pd.DataFrame()
    if "qtd_irns_distintos" in df_dup.columns and "qtd_hashes_pdf_binario_distintos" in df_dup.columns:
        mask = (df_dup["qtd_irns_distintos"] > 1) | (df_dup["qtd_hashes_pdf_binario_distintos"] > 1)
        return df_dup[mask]
    if "possui_inconsistencia_irn_ou_pdf" in df_dup.columns:
        return df_dup[df_dup["possui_inconsistencia_irn_ou_pdf"] == 1]
    return pd.DataFrame()


def _build_issues_rows(
    df_div: pd.DataFrame,
    df_dup: pd.DataFrame,
    *,
    split_by_pair: bool = False,
) -> list[dict[str, object]]:
    """Consolida divergências e inconsistências de IRN/PDF64 em registros estruturados para Jira/Azure DevOps."""
    rows: list[dict[str, object]] = []
    idx = 1

    sistema_map = {
        "BATIMENTO_COD_CLIENTE_BP": "AgroCenter / MTech (LGPD — Mapeamento BP vs Cod_Cliente)",
        "DEMAIS_DADOS_INTEGRIDADE": "MTech -> AgroCenter (Serialização Demais_Dados)",
        "PDF_INTEGRIDADE": "MTech (Geração/Codificação PDF64)",
        "PDF_VALOR_EXTENSO_IDIOMA": "MTech (Template PDF)",
        "PDF_SEXAGEM_IDIOMA": "MTech (Template PDF — Localização PT-BR)",
        "PDF_DATA_FORMATO_EUA": "MTech (Template PDF — Localização PT-BR)",
        "PDF_CONSISTENCIA_ZOOTECNICA": "MTech (Cálculo Zootécnico PDF)",
        "PDF_CONSISTENCIA_FINANCEIRA": "MTech (Cálculo Financeiro PDF)",
    }

    dups_only = _filter_inconsistent_resends(df_dup)
    for _, drow in dups_only.iterrows():
        rows.append({
            "ID": f"ISSUE-{idx:02d}",
            "Titulo": f"[Integração] Inconsistência entre envios do lote ({drow['aviario_lote']}): IRN ou hash binário PDF64 divergente",
            "Severidade": "ALTA",
            "Sistema_Responsavel": "MTech / AgroCenter (Consistência IRN + Determinismo PDF64)",
            "Status": "FALHA",
            "Descricao": (
                f"O aviário-lote {drow['aviario_lote']} recebeu {int(drow['qtd_payloads'])} envio(s) com "
                f"{int(drow['qtd_irns_distintos'])} IRN(s) distintos e "
                f"{int(drow['qtd_hashes_pdf_binario_distintos'])} hashes binários de PDF Base64 distintos "
                f"({int(drow['qtd_hashes_conteudo_canonico_distintos'])} hash(es) de conteúdo canônico). "
                f"Diagnóstico: {drow['diagnostico_duplicidade']}. Reenvios são aceitos quando mantêm o mesmo IRN e o mesmo SHA-256 binário do PDF64."
            ),
            "Criterio_Aceite": (
                "Em qualquer reenvio de um mesmo aviário-lote, manter exatamente o mesmo IRN e o mesmo hash SHA-256 "
                "binário do PDF Base64 (geração determinística)."
            ),
            "Evidencia_JSON": f"qtd_payloads={int(drow['qtd_payloads'])}, hashes_arquivo={int(drow['qtd_hashes_arquivo_distintos'])}",
            "Evidencia_PDF": f"hashes_binario={int(drow['qtd_hashes_pdf_binario_distintos'])}, hash_canonico={int(drow['qtd_hashes_conteudo_canonico_distintos'])}",
            "Lotes_Afetados": str(drow["aviario_lote"]),
            "Qtd_Afetados": int(drow["qtd_payloads"]),
            "Payloads_Afetados": drow["arquivos"],
        })
        idx += 1

    if not df_div.empty:
        df_work = df_div.copy()
        if "aviario_lote" not in df_work.columns:
            df_work["aviario_lote"] = df_work["arquivo_origem"]
        # Quando split_by_pair=True (ex.: CLI --group-by par), separa cada par distinto em BATIMENTO_*
        df_work["_group_json"] = df_work.apply(
            lambda r: _fmt(r["valor_json"]) if (split_by_pair and str(r["regra"]).startswith("BATIMENTO_")) else "*",
            axis=1,
        )
        df_work["_group_pdf"] = df_work.apply(
            lambda r: _fmt(r["valor_pdf"]) if (split_by_pair and str(r["regra"]).startswith("BATIMENTO_")) else "*",
            axis=1,
        )
        grouped = df_work.groupby(["regra", "status", "severidade", "_group_json", "_group_pdf"], sort=False)
        for (regra, status, severidade, _, _), grp in grouped:
            exemplo = grp.iloc[0]
            lotes_unicos = sorted({str(x) for x in grp["aviario_lote"].tolist() if pd.notna(x)})
            pares_unicos = sorted(
                {(_fmt(r["valor_json"]), _fmt(r["valor_pdf"])) for _, r in grp.iterrows()}
            )
            if not split_by_pair and str(regra) == "BATIMENTO_COD_CLIENTE_BP" and len(pares_unicos) > 1:
                pares_str = "; ".join(f"{vj} -> {vp}" for vj, vp in pares_unicos)
                titulo = (
                    f"[{regra}] Risco LGPD / Desalinhamento Cadastral: Divergência Cod_Cliente (JSON) x BP (PDF) "
                    f"({len(pares_unicos)} pares em {len(grp)} ocorrências)"
                )
                descricao = (
                    f"Consolidado de {len(pares_unicos)} pares distintos em {len(grp)} ocorrência(s): {pares_str}. "
                    "Uma granja possui aviários com um Proprietário (BP) e um Responsável pela granja (também integrado, com BP). "
                    "O PDF está puxando o BP do proprietário do aviário, enquanto o JSON (Cod_Cliente) está puxando o BP do "
                    "responsável pela granja (além de possível redundância de cadastro no MTech). A coluna usada no JSON deve ser a mesma do PDF."
                )
                criterio = (
                    "Alinhar a origem de Cod_Cliente (JSON) e BP (PDF) no MTech para utilizarem exatamente a mesma "
                    "coluna/papel (Responsável da granja ou Proprietário do aviário) e garantir BATIMENTO_COD_CLIENTE_BP = OK em 100% dos payloads válidos."
                )
                evid_json = ", ".join(sorted({vj for vj, _ in pares_unicos}))
                evid_pdf = ", ".join(sorted({vp for _, vp in pares_unicos}))
            else:
                titulo = f"[{regra}] {exemplo['detalhe'][:80]}"
                descricao = exemplo["detalhe"]
                criterio = f"Regra {regra} deve retornar OK em 100% dos payloads válidos."
                evid_json = _fmt(exemplo["valor_json"])
                evid_pdf = _fmt(exemplo["valor_pdf"])

            rows.append({
                "ID": f"ISSUE-{idx:02d}",
                "Titulo": titulo,
                "Severidade": severidade,
                "Sistema_Responsavel": sistema_map.get(regra, "AgroCenter / MTech"),
                "Status": status,
                "Descricao": descricao,
                "Criterio_Aceite": criterio,
                "Evidencia_JSON": evid_json,
                "Evidencia_PDF": evid_pdf,
                "Lotes_Afetados": ", ".join(lotes_unicos),
                "Qtd_Afetados": len(grp),
                "Payloads_Afetados": ", ".join(grp["arquivo_origem"].tolist()),
            })
            idx += 1

    return rows


def query_issues(
    conn: sqlite3.Connection,
    *,
    regra: str | None = None,
    status: str | None = None,
    severidade: str | None = None,
    lote: str | None = None,
    arquivo: str | None = None,
    group_by: str = "par",
) -> list[dict[str, object]]:
    """Consulta e agrupa issues dinamicamente a partir do SQLite com filtros opcionais."""
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    if not df_div.empty:
        if regra:
            df_div = df_div[df_div["regra"].str.contains(regra, case=False, na=False)]
        if status:
            df_div = df_div[df_div["status"].str.upper() == status.upper()]
        if severidade:
            df_div = df_div[df_div["severidade"].str.upper() == severidade.upper()]
        if lote:
            df_div = df_div[df_div["aviario_lote"].astype(str).str.contains(lote, case=False, na=False)]
        if arquivo:
            mask = (
                df_div["arquivo_origem"].astype(str).str.contains(arquivo, case=False, na=False)
                | df_div["arquivo_pai"].astype(str).str.contains(arquivo, case=False, na=False)
            )
            df_div = df_div[mask]

    if not df_dup.empty:
        if lote:
            df_dup = df_dup[df_dup["aviario_lote"].astype(str).str.contains(lote, case=False, na=False)]
        if arquivo:
            df_dup = df_dup[df_dup["arquivos"].astype(str).str.contains(arquivo, case=False, na=False)]
        if status and status.upper() != "FALHA":
            df_dup = df_dup.iloc[0:0]
        if severidade and severidade.upper() != "ALTA":
            df_dup = df_dup.iloc[0:0]
        if regra and not any(k in regra.upper() for k in ("DUPLIC", "INCONSIST", "IRN", "PDF")):
            df_dup = df_dup.iloc[0:0]

    if group_by == "nenhum":
        items: list[dict[str, object]] = []
        for _, r in df_div.iterrows():
            items.append({
                "Regra": r["regra"],
                "Status": r["status"],
                "Severidade": r["severidade"],
                "Aviario_Lote": r["aviario_lote"],
                "Arquivo": r["arquivo_origem"],
                "Valor_JSON": _fmt(r["valor_json"]),
                "Valor_PDF": _fmt(r["valor_pdf"]),
                "Detalhe": r["detalhe"],
            })
        return items

    if group_by == "lote":
        items = []
        if not df_div.empty:
            for lote_k, grp in df_div.groupby("aviario_lote", sort=True):
                regras = sorted({str(x) for x in grp["regra"].tolist()})
                items.append({
                    "Aviario_Lote": lote_k,
                    "Qtd_Ocorrencias": len(grp),
                    "Regras": ", ".join(regras),
                    "Severidade_Max": "ALTA" if "ALTA" in grp["severidade"].values else ("MEDIA" if "MEDIA" in grp["severidade"].values else "BAIXA"),
                    "Payloads": ", ".join(sorted({str(x) for x in grp["arquivo_origem"].tolist()})),
                })
        return items

    if group_by == "regra":
        df_tmp = df_div.copy()
        if not df_tmp.empty:
            df_tmp["regra_orig"] = df_tmp["regra"]
            grouped = df_tmp.groupby(["regra", "status", "severidade"], sort=False)
            items = []
            for (r_name, st, sev), grp in grouped:
                lotes = sorted({str(x) for x in grp["aviario_lote"].tolist()})
                items.append({
                    "Regra": r_name,
                    "Status": st,
                    "Severidade": sev,
                    "Qtd_Afetados": len(grp),
                    "Lotes_Afetados": ", ".join(lotes),
                })
            return items
        return []

    return _build_issues_rows(df_div, df_dup, split_by_pair=(group_by == "par"))


def generate_issues_package(conn: sqlite3.Connection, reports_dir: Path) -> tuple[Path, Path]:
    """Gera pacote de issues prontas para Jira/Azure DevOps (.csv e .md)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    issues = _build_issues_rows(df_div, df_dup, split_by_pair=False)
    df_issues = pd.DataFrame(issues)

    csv_path = reports_dir / "issues_dev.csv"
    md_path = reports_dir / "issues_dev.md"

    df_issues.to_csv(csv_path, index=False, encoding="utf-8-sig")

    md_lines = [
        "# Pacote de Issues para Desenvolvimento — Homologação AgroCenter × MTech",
        "",
        f"Total de issues abertas: **{len(issues)}**",
        "",
    ]
    for item in issues:
        md_lines.extend([
            f"## {item['ID']} — {item['Titulo']}",
            "",
            f"- **Severidade:** {item['Severidade']} | **Status:** {item['Status']}",
            f"- **Sistema Responsável:** {item['Sistema_Responsavel']}",
            f"- **Descrição:** {item['Descricao']}",
            f"- **Critério de Aceite:** {item['Criterio_Aceite']}",
            f"- **Evidência JSON:** `{item['Evidencia_JSON']}`",
            f"- **Evidência PDF:** `{item['Evidencia_PDF']}`",
            f"- **Lotes Afetados:** {item.get('Lotes_Afetados', '-')}",
            f"- **Payloads Afetados ({item['Qtd_Afetados']}):** {item['Payloads_Afetados']}",
            "",
        ])

    _append_bp_diag_section(md_lines, conn, heading_level="##")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return csv_path, md_path


def _append_bp_diag_section(
    lines: list[str],
    conn: sqlite3.Connection,
    *,
    heading_level: str = "##",
) -> None:
    """Anexa a tabela de diagnóstico cadastral Cod_Cliente (JSON) x BP (PDF) com consideração de domínio."""
    try:
        df_bp_diag = pd.read_sql_query("SELECT * FROM vw_diagnostico_cod_cliente_bp", conn)
    except Exception:
        df_bp_diag = pd.DataFrame()
    if df_bp_diag.empty:
        return

    lines.extend([
        f"{heading_level} Diagnóstico Cadastral: `Cod_Cliente` (JSON) × `BP` (PDF)",
        "",
        "Detalhamento dos pares divergentes cruzados com a base oficial de referência (`data/cod_bp/cod_BP_integracao.md` / `ref_aviario_bp`) para investigar redundância de cadastro no MTech ou desalinhamento entre a coluna do JSON e a coluna do PDF:",
        "",
        "> **Regra de Negócio (Granja × Aviário):** Uma granja possui aviários; cada aviário tem um **Proprietário** (`cod_BP_Proprietario`) e a granja tem um **Responsável** (`cod_BP_Responsavel`, também integrado). A coluna/papel utilizada no JSON (`Cod_Cliente`) deve ser exatamente a mesma do PDF (`BP`). No cruzamento com `cod_BP_integracao.md`, observou-se que o **JSON (`Cod_Cliente`)** está usando `cod_BP_Proprietario`, enquanto o **PDF (`BP`)** puxa `cod_BP_Responsavel` (ou diverge até da tabela de referência).",
        "",
        "| Aviário | Produtor (PDF) | Matrícula | Cod_Cliente (JSON) | BP (PDF) | Ref. Proprietário | Ref. Responsável | Classificação | Qtd | Lotes Afetados |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ])
    for _, brow in df_bp_diag.iterrows():
        ref_prop = f"{_fmt(brow.get('nome_proprietario_ref'))} (`{_fmt(brow.get('bp_proprietario_ref'))}`)"
        ref_resp = f"{_fmt(brow.get('nome_responsavel_ref'))} (`{_fmt(brow.get('bp_responsavel_ref'))}`)"
        lines.append(
            f"| `{_fmt(brow.get('aviario'))}` | {_fmt(brow.get('produtor_pdf'))} | {_fmt(brow.get('matricula_pdf'))} | "
            f"`{_fmt(brow.get('cod_cliente_json'))}` | `{_fmt(brow.get('bp_pdf'))}` | "
            f"{ref_prop} | {ref_resp} | `{_fmt(brow.get('classificacao_causa'))}` | "
            f"{int(brow.get('qtd_ocorrencias', 0))} | {_fmt(brow.get('lotes_afetados'))} |"
        )
    lines.append("")


def generate_duplicity_diff_report(conn: sqlite3.Connection, report_path: Path) -> Path:
    """Gera relatório com diff de texto entre os 2 primeiros PDFs de lotes com IRN ou PDF64 divergente."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    df_dup_all = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)
    df_dup = _filter_inconsistent_resends(df_dup_all)

    lines = [
        "# Relatório de Diff — Inconsistência de IRN ou Hash Binário PDF64 por Aviário-Lote",
        "",
        "Este artefato evidencia diferenças entre envios do mesmo lote quando há IRN distinto ou hash binário de PDF Base64 distinto.",
        "",
    ]

    if df_dup.empty:
        lines.append("Nenhuma inconsistência de IRN ou hash binário PDF64 encontrada entre envios.")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    df_paths = pd.read_sql_query(
        "SELECT arquivo_origem, pdf_caminho, sha256_arquivo, pdf_bytes_sha256, pdf_texto_canonico_sha256 "
        "FROM payloads WHERE pdf_valido = 1 ORDER BY arquivo_origem",
        conn,
    )

    for _, drow in df_dup.iterrows():
        arquivos = [a.strip() for a in str(drow["arquivos"]).split(",")]
        sub = df_paths[df_paths["arquivo_origem"].isin(arquivos)]
        lines.extend([
            f"## Lote `{drow['aviario_lote']}` ({int(drow['qtd_payloads'])} payloads)",
            "",
            f"- **Diagnóstico:** `{drow['diagnostico_duplicidade']}`",
        ])
        if len(sub) >= 2:
            r1, r2 = sub.iloc[0], sub.iloc[1]
            with pdfplumber.open(r1["pdf_caminho"]) as p1:
                t1 = [ln for pg in p1.pages for ln in (pg.extract_text(layout=True) or "").splitlines()]
            with pdfplumber.open(r2["pdf_caminho"]) as p2:
                t2 = [ln for pg in p2.pages for ln in (pg.extract_text(layout=True) or "").splitlines()]
            diff_lines = list(
                difflib.unified_diff(
                    t1,
                    t2,
                    fromfile=r1["arquivo_origem"],
                    tofile=r2["arquivo_origem"],
                    lineterm="",
                    n=1,
                )
            )
            lines.extend([
                f"- **Comparação:** `{r1['arquivo_origem']}` vs `{r2['arquivo_origem']}`",
                "",
                "```diff",
                *(diff_lines if diff_lines else ["(Sem diferenças textuais)"]),
                "```",
                "",
            ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def generate_html_dashboard(conn: sqlite3.Connection, html_path: Path) -> Path:
    """Gera dashboard HTML autocontido (offline) para apresentação aos stakeholders."""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    df_conf = pd.read_sql_query("SELECT * FROM vw_conferencia_completa ORDER BY arquivo_origem", conn)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    total = len(df_conf)
    aprovados = int((df_conf["status_homologacao"] == "APROVADO").sum()) if total else 0
    aprovados_alerta = int((df_conf["status_homologacao"] == "APROVADO_COM_ALERTA").sum()) if total else 0
    reprovados = int((df_conf["status_homologacao"] == "REPROVADO").sum()) if total else 0
    taxa = ((aprovados + aprovados_alerta) / total * 100.0) if total else 0.0
    dups_count = len(_filter_inconsistent_resends(df_dup))
    parecer = "HOMOLOGADA" if total > 0 and reprovados == 0 else "NÃO HOMOLOGADA"
    parecer_cls = "ok" if parecer == "HOMOLOGADA" else "fail"
    now_str = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S")

    issues = _build_issues_rows(df_div, df_dup)

    conf_rows_html = []
    for _, r in df_conf.iterrows():
        st = str(r["status_homologacao"])
        st_cls = "fail" if st == "REPROVADO" else ("warn" if "ALERTA" in st else "ok")
        qtd_d = int(r["qtd_itens_data"]) if not pd.isna(r["qtd_itens_data"]) else 0
        idx_d = int(r["item_indice"]) if not pd.isna(r["item_indice"]) else 1
        pdf_f = "1" if r["pdf_valido"] == 1 else "0"
        card = f"1:{pdf_f}" if qtd_d == 1 else f"1:{pdf_f} ({idx_d}/{qtd_d})"
        av_cab = f"{_fmt(r['pdf_aviario_codigo'])}-{_fmt(r['pdf_lote'])}" if _fmt(r["pdf_aviario_codigo"]) != "-" else "-"
        av_quit = f"{_fmt(r['pdf_quitacao_aviario'])}-{_fmt(r['pdf_quitacao_lote'])}" if _fmt(r["pdf_quitacao_aviario"]) != "-" else "-"
        conf_rows_html.append(
            f"<tr data-status='{html.escape(st)}'>"
            f"<td><code>{html.escape(str(r['arquivo_origem']))}</code></td>"
            f"<td>{card}</td>"
            f"<td><code>{html.escape(_fmt(r['json_cod_cliente']))}</code></td>"
            f"<td><code>{html.escape(_fmt(r['pdf_bp']))}</code></td>"
            f"<td><code>{html.escape(_fmt(r['json_numero_extrato']))}</code></td>"
            f"<td><code>{html.escape(av_cab)}</code> / <code>{html.escape(av_quit)}</code></td>"
            f"<td>{int(r['qtd_falhas'])}</td>"
            f"<td>{int(r['qtd_alertas'])}</td>"
            f"<td><span class='badge {st_cls}'>{html.escape(st)}</span></td>"
            f"</tr>"
        )

    dup_rows_html = []
    for _, d in df_dup.iterrows():
        diag = str(d["diagnostico_duplicidade"])
        d_cls = "ok" if diag in {"UNICO", "REENVIO_CONSISTENTE"} else "fail"
        dup_rows_html.append(
            f"<tr>"
            f"<td><code>{html.escape(str(d['aviario_lote']))}</code></td>"
            f"<td>{int(d['qtd_payloads'])}</td>"
            f"<td>{int(d['qtd_hashes_arquivo_distintos'])}</td>"
            f"<td>{int(d['qtd_hashes_pdf_binario_distintos'])}</td>"
            f"<td>{int(d['qtd_hashes_conteudo_canonico_distintos'])}</td>"
            f"<td><span class='badge {d_cls}'>{html.escape(diag)}</span></td>"
            f"</tr>"
        )

    issues_cards_html = []
    for it in issues:
        sev = str(it["Severidade"])
        s_cls = "fail" if sev == "ALTA" else ("warn" if sev == "MEDIA" else "info")
        copy_txt = html.escape(
            f"{it['ID']} - {it['Titulo']}\nSeveridade: {sev}\nSistema: {it['Sistema_Responsavel']}\n"
            f"Descrição: {it['Descricao']}\nCritério de Aceite: {it['Criterio_Aceite']}\n"
            f"Evidência JSON: {it['Evidencia_JSON']}\nEvidência PDF: {it['Evidencia_PDF']}\n"
            f"Payloads: {it['Payloads_Afetados']}"
        )
        issues_cards_html.append(
            f"<div class='issue-card'>"
            f"<div class='issue-head'><strong>{html.escape(str(it['ID']))} — {html.escape(str(it['Titulo']))}</strong>"
            f"<span class='badge {s_cls}'>{html.escape(sev)}</span></div>"
            f"<p><b>Sistema:</b> {html.escape(str(it['Sistema_Responsavel']))}</p>"
            f"<p>{html.escape(str(it['Descricao']))}</p>"
            f"<p class='meta'><b>JSON:</b> <code>{html.escape(str(it['Evidencia_JSON']))}</code> | "
            f"<b>PDF:</b> <code>{html.escape(str(it['Evidencia_PDF']))}</code></p>"
            f"<p class='meta'><b>Afetados ({it['Qtd_Afetados']}):</b> {html.escape(str(it['Payloads_Afetados']))}</p>"
            f"<button class='copy-btn' onclick=\"copyIssue(this)\" data-text=\"{copy_txt}\">Copiar Issue</button>"
            f"</div>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Homologação AgroCenter × MTech</title>
<style>
  :root {{ --bg:#f8fafc; --card:#ffffff; --text:#0f172a; --muted:#475569; --border:#e2e8f0;
           --ok:#16a34a; --ok-bg:#dcfce7; --fail:#dc2626; --fail-bg:#fee2e2;
           --warn:#d97706; --warn-bg:#fef3c7; --info:#2563eb; --info-bg:#dbeafe; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  header {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:24px; }}
  h1 {{ margin:0; font-size:1.5rem; }}
  .subtitle {{ color:var(--muted); font-size:0.9rem; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:16px; margin-bottom:24px; }}
  .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; }}
  .kpi .label {{ color:var(--muted); font-size:0.8rem; text-transform:uppercase; }}
  .kpi .val {{ font-size:1.6rem; font-weight:700; margin-top:4px; }}
  .section {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:20px; margin-bottom:24px; }}
  h2 {{ margin-top:0; font-size:1.15rem; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.88rem; }}
  th, td {{ padding:10px 8px; border-bottom:1px solid var(--border); text-align:left; }}
  th {{ color:var(--muted); font-weight:600; }}
  .badge {{ padding:3px 8px; border-radius:999px; font-size:0.75rem; font-weight:700; display:inline-block; }}
  .ok {{ background:var(--ok-bg); color:var(--ok); }}
  .fail {{ background:var(--fail-bg); color:var(--fail); }}
  .warn {{ background:var(--warn-bg); color:var(--warn); }}
  .info {{ background:var(--info-bg); color:var(--info); }}
  .filters {{ display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }}
  .filters button, .copy-btn {{ border:1px solid var(--border); background:#fff; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.82rem; }}
  .filters button.active {{ background:#0f172a; color:#fff; border-color:#0f172a; }}
  .issue-card {{ border:1px solid var(--border); border-radius:8px; padding:14px; margin-bottom:12px; }}
  .issue-head {{ display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px; }}
  .meta {{ color:var(--muted); font-size:0.83rem; }}
  code {{ background:#f1f5f9; padding:2px 5px; border-radius:4px; font-size:0.82rem; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>Relatório Executivo de Homologação — AgroCenter × MTech</h1>
      <div class="subtitle">Gerado em {now_str}</div>
    </div>
    <span class="badge {parecer_cls}" style="font-size:0.95rem;padding:8px 14px;">{parecer}</span>
  </header>

  <div class="kpis">
    <div class="kpi"><div class="label">Payloads Analisados</div><div class="val">{total}</div></div>
    <div class="kpi"><div class="label">Aprovados</div><div class="val">{aprovados}</div></div>
    <div class="kpi"><div class="label">Reprovados</div><div class="val">{reprovados}</div></div>
    <div class="kpi"><div class="label">Conformidade</div><div class="val">{taxa:.1f}%</div></div>
    <div class="kpi"><div class="label">Lotes com Duplicidade</div><div class="val">{dups_count}</div></div>
  </div>

  <div class="section">
    <h2>Matriz de Conferência por Payload</h2>
    <div class="filters">
      <button class="active" onclick="filterRows('ALL', this)">Todos ({total})</button>
      <button onclick="filterRows('REPROVADO', this)">Reprovados ({reprovados})</button>
      <button onclick="filterRows('APROVADO_COM_ALERTA', this)">Com Alerta ({aprovados_alerta})</button>
      <button onclick="filterRows('APROVADO', this)">Aprovados ({aprovados})</button>
    </div>
    <table>
      <thead>
        <tr><th>Arquivo</th><th>1:1</th><th>Cod_Cliente (JSON)</th><th>BP (PDF)</th><th>Aviário-Lote (JSON)</th><th>PDF Cab. / Quit.</th><th>Falhas</th><th>Alertas</th><th>Status</th></tr>
      </thead>
      <tbody id="conf-body">
        {"".join(conf_rows_html)}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Duplicidades por Aviário-Lote (Idempotência e Hashes)</h2>
    <table>
      <thead>
        <tr><th>Aviário-Lote</th><th>Payloads</th><th>Hashes Arquivo</th><th>Hashes PDF Binário</th><th>Hashes Conteúdo Canônico</th><th>Diagnóstico</th></tr>
      </thead>
      <tbody>
        {"".join(dup_rows_html)}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Issues para Equipe de Desenvolvimento ({len(issues)})</h2>
    {"".join(issues_cards_html)}
  </div>
</div>
<script>
function filterRows(status, btn) {{
  document.querySelectorAll('.filters button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#conf-body tr').forEach(tr => {{
    tr.style.display = (status === 'ALL' || tr.dataset.status === status) ? '' : 'none';
  }});
}}
function copyIssue(btn) {{
  navigator.clipboard.writeText(btn.dataset.text);
  const orig = btn.textContent;
  btn.textContent = 'Copiado!';
  setTimeout(() => btn.textContent = orig, 1500);
}}
</script>
</body>
</html>"""

    html_path.write_text(doc, encoding="utf-8")
    return html_path
