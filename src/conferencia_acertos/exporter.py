from __future__ import annotations

import difflib
import html
import json
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
            "pdf_bytes_sha256": pdf_data.pdf_bytes_sha256,
            "pdf_texto_sha256": pdf_data.pdf_texto_sha256,
            "pdf_texto_canonico_sha256": pdf_data.pdf_texto_canonico_sha256,
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


def _build_issues_rows(df_div: pd.DataFrame, df_dup: pd.DataFrame) -> list[dict[str, object]]:
    """Consolida divergências e duplicidades em registros estruturados para Jira/Azure DevOps."""
    rows: list[dict[str, object]] = []
    idx = 1

    sistema_map = {
        "BATIMENTO_COD_CLIENTE_BP": "AgroCenter / MTech (Mapeamento BP vs Cod_Cliente)",
        "DEMAIS_DADOS_INTEGRIDADE": "AgroCenter (Serialização Demais_Dados)",
        "PDF_INTEGRIDADE": "MTech / Origem PDF64",
        "PDF_VALOR_EXTENSO_IDIOMA": "MTech (Template PDF)",
    }

    dups_only = df_dup[df_dup["qtd_payloads"] > 1]
    for _, drow in dups_only.iterrows():
        rows.append({
            "ID": f"ISSUE-{idx:02d}",
            "Titulo": f"[Integração] Reenvio duplicado e ordenação não-determinística no PDF ({drow['aviario_lote']})",
            "Severidade": "ALTA",
            "Sistema_Responsavel": "AgroCenter / MTech (Idempotência + Query PDF)",
            "Status": "FALHA",
            "Descricao": (
                f"O aviário-lote {drow['aviario_lote']} recebeu {int(drow['qtd_payloads'])} payloads com "
                f"{int(drow['qtd_hashes_pdf_binario_distintos'])} hashes binários de PDF distintos, mas "
                f"{int(drow['qtd_hashes_conteudo_canonico_distintos'])} hash(es) de conteúdo canônico. "
                f"Diagnóstico: {drow['diagnostico_duplicidade']}."
            ),
            "Criterio_Aceite": "Garantir idempotência por IRN/aviário-lote e adicionar ORDER BY determinístico nas queries de Ração e Produção Entregue do PDF.",
            "Evidencia_JSON": f"qtd_payloads={int(drow['qtd_payloads'])}, hashes_arquivo={int(drow['qtd_hashes_arquivo_distintos'])}",
            "Evidencia_PDF": f"hashes_binario={int(drow['qtd_hashes_pdf_binario_distintos'])}, hash_canonico={int(drow['qtd_hashes_conteudo_canonico_distintos'])}",
            "Qtd_Afetados": int(drow["qtd_payloads"]),
            "Payloads_Afetados": drow["arquivos"],
        })
        idx += 1

    if not df_div.empty:
        grouped = df_div.groupby(["regra", "status", "severidade"], sort=False)
        for (regra, status, severidade), grp in grouped:
            exemplo = grp.iloc[0]
            rows.append({
                "ID": f"ISSUE-{idx:02d}",
                "Titulo": f"[{regra}] {exemplo['detalhe'][:80]}",
                "Severidade": severidade,
                "Sistema_Responsavel": sistema_map.get(regra, "AgroCenter / MTech"),
                "Status": status,
                "Descricao": exemplo["detalhe"],
                "Criterio_Aceite": f"Regra {regra} deve retornar OK em 100% dos payloads válidos.",
                "Evidencia_JSON": _fmt(exemplo["valor_json"]),
                "Evidencia_PDF": _fmt(exemplo["valor_pdf"]),
                "Qtd_Afetados": len(grp),
                "Payloads_Afetados": ", ".join(grp["arquivo_origem"].tolist()),
            })
            idx += 1

    return rows


def generate_issues_package(conn: sqlite3.Connection, reports_dir: Path) -> tuple[Path, Path]:
    """Gera pacote de issues prontas para Jira/Azure DevOps (.csv e .md)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    df_div = pd.read_sql_query("SELECT * FROM vw_divergencias", conn)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote", conn)

    issues = _build_issues_rows(df_div, df_dup)
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
            f"- **Payloads Afetados ({item['Qtd_Afetados']}):** {item['Payloads_Afetados']}",
            "",
        ])

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return csv_path, md_path


def generate_duplicity_diff_report(conn: sqlite3.Connection, report_path: Path) -> Path:
    """Gera relatório com diff de texto entre os 2 primeiros PDFs de lotes duplicados."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    df_dup = pd.read_sql_query("SELECT * FROM vw_duplicidades_lote WHERE qtd_payloads > 1", conn)

    lines = [
        "# Relatório de Diff — PDFs Duplicados por Aviário-Lote",
        "",
        "Este artefato evidencia as diferenças exatas de ordenação/conteúdo entre PDFs reenviados para o mesmo lote.",
        "",
    ]

    if df_dup.empty:
        lines.append("Nenhuma duplicidade por aviário-lote encontrada.")
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
                t1 = [ln for pg in p1.pages for ln in (pg.extract_text() or "").splitlines()]
            with pdfplumber.open(r2["pdf_caminho"]) as p2:
                t2 = [ln for pg in p2.pages for ln in (pg.extract_text() or "").splitlines()]
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
    reprovados = int((df_conf["status_homologacao"] == "REPROVADO").sum()) if total else 0
    taxa = ((total - reprovados) / total * 100.0) if total else 0.0
    dups_count = int((df_dup["qtd_payloads"] > 1).sum())
    parecer = "HOMOLOGADA" if total > 0 and reprovados == 0 else "NÃO HOMOLOGADA"
    parecer_cls = "ok" if parecer == "HOMOLOGADA" else "fail"
    now_str = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S")

    issues = _build_issues_rows(df_div, df_dup)

    conf_rows_html = []
    for _, r in df_conf.iterrows():
        st = str(r["status_homologacao"])
        st_cls = "fail" if st == "REPROVADO" else ("warn" if "ALERTA" in st else "ok")
        qtd_d = int(r["qtd_itens_data"]) if not pd.isna(r["qtd_itens_data"]) else 0
        card = f"{qtd_d}:{'1' if r['pdf_valido'] == 1 else '0'}"
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
        d_cls = "ok" if diag == "UNICO" else "fail"
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
