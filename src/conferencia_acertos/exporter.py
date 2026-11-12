from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from conferencia_acertos.parser import ParsedPayload
from conferencia_acertos.pdf_extractor import PdfExtractedData
from conferencia_acertos.validator import ValidationResult


def _fmt(val: object, default: str = "-") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val):
        return default
    s = str(val).strip()
    return s if s else default


def export_payload_bundle(
    bundle_dir: Path,
    safe_stem: str,
    payload: ParsedPayload,
    pdf_data: PdfExtractedData,
    validations: list[ValidationResult],
) -> Path | None:
    """Cria a subpasta data/pdf/<payload>/ com o PDF, payload.json e relatorio_acuracia.md."""
    bundle_dir.mkdir(parents=True, exist_ok=True)

    pdf_saved_path: Path | None = None
    if payload.pdf_bytes and payload.pdf_base64_valido and pdf_data.pdf_valido:
        pdf_saved_path = bundle_dir / f"{safe_stem}.pdf"
        pdf_saved_path.write_bytes(payload.pdf_bytes)

    payload_json_obj = {
        "arquivo_origem": payload.arquivo_origem,
        "sha256_arquivo": payload.sha256_arquivo,
        "schema_versao": payload.schema_versao,
        "cardinalidade": {
            "qtd_itens_data": payload.qtd_itens_data,
            "item_indice": payload.item_indice,
            "esperado_1_para_1": payload.qtd_itens_data == 1 and pdf_saved_path is not None,
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
            "arquivo_pdf": pdf_saved_path.name if pdf_saved_path else None,
            "erro": payload.pdf_base64_erro or pdf_data.pdf_erro,
        },
    }
    (bundle_dir / "payload.json").write_text(
        json.dumps(payload_json_obj, indent=2, ensure_ascii=False),
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

    lines = [
        f"# Relatório de Acurácia — `{payload.arquivo_origem}`",
        "",
        f"- **Acurácia (Regras OK / Total):** **{acuracia_pct:.1f}%** ({ok_count}/{total_regras})",
        f"- **Falhas Bloqueantes:** {falha_count} | **Alertas:** {alerta_count}",
        f"- **Cardinalidade (`Data` ↔ PDF):** {payload.qtd_itens_data} item(ns) em `Data` | PDF válido: {'Sim' if pdf_saved_path else 'Não'}",
        f"- **PDF Gerado:** `{pdf_saved_path.name if pdf_saved_path else 'Não gerado (PDF inválido/corrompido)'}`",
        "",
        "## Comparativo Chave (Payload JSON × Binário PDF)",
        "",
        "| Campo | Payload JSON | PDF (Cabeçalho) | PDF (Quitação) |",
        "| :--- | :--- | :--- | :--- |",
        f"| **BP / Cod_Cliente** | `{payload.cod_cliente or '-'}` | `{pdf_data.bp or '-'}` | `{', '.join(pdf_data.bps_encontrados) if pdf_data.bps_encontrados else '-'}` |",
        f"| **Aviário-Lote Composto** | `{payload.demais_dados.Numero_Extrato if payload.demais_dados else '-'}` | `{aviario_lote_cab}` | `{aviario_lote_quit}` |",
        f"| **Produtor / Aviário** | `{payload.demais_dados.Aviario if payload.demais_dados else '-'}` | `{pdf_data.produtor or '-'}` | `{pdf_data.produtor or '-'}` |",
        f"| **Data Emissão** | `{payload.demais_dados.DataEmissao if payload.demais_dados else '-'}` | `{pdf_data.data_pdf or '-'}` | `-` |",
        "",
        "## Detalhamento das Regras Conferidas",
        "",
        "| Regra | Status | Severidade | Valor JSON | Valor PDF | Detalhe |",
        "| :--- | :---: | :---: | :--- | :--- | :--- |",
    ]
    for v in validations:
        lines.append(
            f"| `{v.regra}` | **{v.status}** | {v.severidade} | `{v.valor_json or '-'}` | `{v.valor_pdf or '-'}` | {v.detalhe} |"
        )

    (bundle_dir / "relatorio_acuracia.md").write_text("\n".join(lines), encoding="utf-8")
    return pdf_saved_path


def export_tabular(conn: sqlite3.Connection, exports_dir: Path) -> tuple[Path, Path, Path]:
    """Exporta as views do SQLite para CSV e XLSX."""
    exports_dir.mkdir(parents=True, exist_ok=True)

    df_conf = pd.read_sql_query("SELECT * FROM vw_conferencia_completa ORDER BY arquivo_origem", conn)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)
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
        card_str = f"{qtd_data}:{'1' if row['pdf_valido'] == 1 else '0'}"
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
        "| Aviário-Lote | Qtd Payloads | Hashes Arquivo | Hashes PDF Binário | Hashes Conteúdo Canônico | Diagnóstico |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |",
    ])

    for _, drow in df_dup.iterrows():
        lines.append(
            f"| `{drow['aviario_lote']}` | {int(drow['qtd_payloads'])} | "
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

    dups_only = df_dup[df_dup["qtd_payloads"] > 1]
    issue_num = 1
    if not dups_only.empty:
        for _, drow in dups_only.iterrows():
            lines.extend([
                f"### Issue #{issue_num} — `DUPLICIDADE_E_ORDENACAO_NAO_DETERMINISTICA` (FALHA | Severidade: ALTA)",
                "",
                (
                    f"- **Descrição:** O aviário-lote `{drow['aviario_lote']}` recebeu **{int(drow['qtd_payloads'])}** "
                    f"payloads distintos (hashes de arquivo: {int(drow['qtd_hashes_arquivo_distintos'])}, "
                    f"hashes binários de PDF: {int(drow['qtd_hashes_pdf_binario_distintos'])}, "
                    f"hashes de conteúdo canônico: {int(drow['qtd_hashes_conteudo_canonico_distintos'])}). "
                    f"Diagnóstico: `{drow['diagnostico_duplicidade']}` — reenvio sem idempotência e/ou tabelas do PDF "
                    f"(Movimentação de Ração / Produção Entregue) sem `ORDER BY` determinístico."
                ),
                f"- **Payloads Afetados ({int(drow['qtd_payloads'])}):** {drow['arquivos']}",
                "",
            ])
            issue_num += 1

    if df_div.empty and dups_only.empty:
        lines.append("Nenhuma divergência ou alerta identificado nos payloads analisados.")
    elif not df_div.empty:
        grouped = df_div.groupby(["regra", "status", "severidade"], sort=False)
        for (regra, status, severidade), grp in grouped:
            arquivos = ", ".join(f"`{a}`" for a in grp["arquivo_origem"].tolist())
            exemplo = grp.iloc[0]
            lines.extend([
                f"### Issue #{issue_num} — `{regra}` ({status} | Severidade: {severidade})",
                "",
                f"- **Descrição:** {exemplo['detalhe']}",
                f"- **Evidência JSON:** `{_fmt(exemplo['valor_json'])}`",
                f"- **Evidência PDF:** `{_fmt(exemplo['valor_pdf'])}`",
                f"- **Payloads Afetados ({len(grp)}):** {arquivos}",
                "",
            ])
            issue_num += 1

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
