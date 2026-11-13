from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from conferencia_acertos.database import init_db, upsert_record, upsert_ref_aviario_bp
from conferencia_acertos.reference_bp import export_cod_bp_csv, parse_cod_bp_markdown
from conferencia_acertos.exporter import (
    export_payload_bundle,
    export_tabular,
    generate_duplicity_diff_report,
    generate_executive_report,
    generate_html_dashboard,
    generate_issues_package,
    query_issues,
    resolve_lote_key,
)
from conferencia_acertos.notebooklm_exporter import generate_notebooklm_bundle
from conferencia_acertos.parser import parse_payload_file
from conferencia_acertos.pdf_extractor import extract_pdf_data
from conferencia_acertos.validator import validate_payload


def discover_payload_files(input_dirs: list[Path]) -> list[tuple[Path, Path]]:
    """Retorna pares (arquivo, diretorio_raiz) buscando recursivamente por .txt/.json."""
    files: dict[Path, Path] = {}
    for directory in input_dirs:
        if not directory.exists():
            continue
        resolved_root = directory.resolve()
        for ext in ("*.txt", "*.json"):
            for path in directory.rglob(ext):
                if path.is_file():
                    files[path.resolve()] = resolved_root
    return sorted(((p, root) for p, root in files.items()), key=lambda item: item[0])


def run_pipeline(
    input_dirs: list[Path],
    db_path: Path,
    pdf_dir: Path,
    exports_dir: Path,
    report_path: Path,
) -> None:
    files = discover_payload_files(input_dirs)
    if not files:
        print("Nenhum arquivo de payload (.txt/.json) encontrado.")
        return

    pdf_dir.mkdir(parents=True, exist_ok=True)
    # Remove PDFs soltos legados na raiz de data/pdf/ e reseta artefatos aditivos para reconstrução limpa
    for legacy_pdf in pdf_dir.glob("*.pdf"):
        legacy_pdf.unlink()
    for existing_dir in pdf_dir.iterdir():
        if existing_dir.is_dir():
            for artifact in ("payload.json", "relatorio_acuracia.md"):
                art_path = existing_dir / artifact
                if art_path.exists():
                    art_path.unlink()

    conn = init_db(db_path)

    ref_md = Path("data/cod_bp/cod_BP_integracao.md")
    if ref_md.exists():
        ref_records = parse_cod_bp_markdown(ref_md)
        if ref_records:
            upsert_ref_aviario_bp(conn, ref_records)
            export_cod_bp_csv(ref_records, Path("data/cod_bp/cod_BP_integracao.csv"))

    total_items = 0
    processed_names: set[str] = set()
    processed_lote_dirs: set[str] = set()
    try:
        for file_path, root_dir in files:
            try:
                parsed_items = parse_payload_file(file_path, root_dir=root_dir)
                file_falhas = 0
                file_alertas = 0
                for item in parsed_items:
                    total_items += 1
                    processed_names.add(item.arquivo_origem)
                    pdf_data = extract_pdf_data(item.pdf_bytes)
                    validations = validate_payload(item, pdf_data)

                    lote_key = resolve_lote_key(item, pdf_data)
                    processed_lote_dirs.add(lote_key)
                    bundle_dir = pdf_dir / lote_key
                    pdf_saved_path = export_payload_bundle(
                        bundle_dir=bundle_dir,
                        lote_key=lote_key,
                        payload=item,
                        pdf_data=pdf_data,
                        validations=validations,
                    )

                    upsert_record(conn, item, pdf_data, validations, pdf_saved_path)

                    falhas = sum(1 for v in validations if v.status == "FALHA")
                    alertas = sum(1 for v in validations if v.status == "ALERTA")
                    file_falhas += falhas
                    file_alertas += alertas
                    if item.qtd_itens_data == 1:
                        print(
                            f"[{item.arquivo_origem}] itens_data=1 "
                            f"falhas={falhas} alertas={alertas} -> {bundle_dir}"
                        )
                if len(parsed_items) > 1:
                    rel_file = file_path.relative_to(root_dir).as_posix() if file_path.parent != root_dir else file_path.name
                    print(
                        f"[{rel_file}] lote={len(parsed_items)} itens "
                        f"falhas_totais={file_falhas} alertas_totais={file_alertas} -> {pdf_dir}/<aviario-lote>/"
                    )
            except Exception as exc:
                rel_name = file_path.relative_to(root_dir).as_posix() if file_path.parent != root_dir else file_path.name
                processed_names.add(rel_name)
                print(f"[ERRO] Falha inesperada ao processar {file_path}: {exc}")

        # Remove do banco e de data/pdf/ registros/pastas que não existem mais em data/raw/
        if processed_names:
            placeholders = ",".join("?" for _ in processed_names)
            conn.execute(
                f"DELETE FROM payloads WHERE arquivo_origem NOT IN ({placeholders})",
                tuple(sorted(processed_names)),
            )
            conn.commit()
        for existing_dir in pdf_dir.iterdir():
            if existing_dir.is_dir() and existing_dir.name not in processed_lote_dirs:
                shutil.rmtree(existing_dir)

        csv_conf, csv_div, xlsx = export_tabular(conn, exports_dir)
        rep = generate_executive_report(conn, report_path)
        rep_html = generate_html_dashboard(conn, report_path.with_suffix(".html"))
        issues_csv, issues_md = generate_issues_package(conn, report_path.parent)
        diff_md = generate_duplicity_diff_report(conn, report_path.parent / "diff_duplicidades.md")
        nlm_prompts = generate_notebooklm_bundle(conn, report_path.parent / "notebooklm")
        print(f"\nProcessados {total_items} registro(s) de {len(files)} arquivo(s).")
        print(f"SQLite: {db_path}")
        print(f"Exports: {csv_conf}, {csv_div}, {xlsx}")
        print(f"Relatórios: {rep}, {rep_html}, {issues_csv}, {issues_md}, {diff_md}")
        print(f"NotebookLM: {nlm_prompts} (+ sources/)")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI de conferência AgroCenter x MTech")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="Processa payloads, popula SQLite, gera exports e relatório")
    run_cmd.add_argument("--input", nargs="+", type=Path, default=[Path("data/raw")])
    run_cmd.add_argument("--db", type=Path, default=Path("db/acertos.db"))
    run_cmd.add_argument("--pdf-dir", type=Path, default=Path("data/pdf"))
    run_cmd.add_argument("--exports-dir", type=Path, default=Path("data/exports"))
    run_cmd.add_argument("--report", type=Path, default=Path("reports/relatorio_homologacao.md"))

    issues_cmd = sub.add_parser("issues", help="Consulta e agrupa issues dinamicamente no SQLite")
    issues_cmd.add_argument("--db", type=Path, default=Path("db/acertos.db"))
    issues_cmd.add_argument("--regra", type=str, default=None)
    issues_cmd.add_argument("--status", type=str, default=None)
    issues_cmd.add_argument("--severidade", type=str, default=None)
    issues_cmd.add_argument("--lote", type=str, default=None)
    issues_cmd.add_argument("--arquivo", type=str, default=None)
    issues_cmd.add_argument(
        "--group-by",
        choices=["par", "lote", "regra", "nenhum"],
        default="par",
    )
    issues_cmd.add_argument(
        "--format",
        choices=["table", "json", "md"],
        default="table",
    )

    args = parser.parse_args()
    if args.command == "run":
        run_pipeline(
            input_dirs=args.input,
            db_path=args.db,
            pdf_dir=args.pdf_dir,
            exports_dir=args.exports_dir,
            report_path=args.report,
        )
    elif args.command == "issues":
        conn = init_db(args.db)
        try:
            rows = query_issues(
                conn,
                regra=args.regra,
                status=args.status,
                severidade=args.severidade,
                lote=args.lote,
                arquivo=args.arquivo,
                group_by=args.group_by,
            )
        finally:
            conn.close()

        if args.format == "json":
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif args.format == "md":
            if not rows:
                print("Nenhuma issue encontrada.")
            else:
                cols = list(rows[0].keys())
                print("| " + " | ".join(cols) + " |")
                print("| " + " | ".join("---" for _ in cols) + " |")
                for row in rows:
                    print("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        else:
            if not rows:
                print("Nenhuma issue encontrada.")
            else:
                for row in rows:
                    if args.group_by == "par":
                        print(
                            f"[{row.get('ID', '-')}] ({row.get('Severidade', '-')}/{row.get('Status', '-')}) "
                            f"{row.get('Titulo', '-')} | JSON={row.get('Evidencia_JSON', '-')} x "
                            f"PDF={row.get('Evidencia_PDF', '-')} | Qtd={row.get('Qtd_Afetados', 0)} | "
                            f"Lotes={row.get('Lotes_Afetados', '-')}"
                        )
                    elif args.group_by == "lote":
                        print(
                            f"[{row.get('Aviario_Lote', '-')}] ({row.get('Severidade_Max', '-')}) "
                            f"Qtd={row.get('Qtd_Ocorrencias', 0)} | Regras={row.get('Regras', '-')}"
                        )
                    elif args.group_by == "regra":
                        print(
                            f"[{row.get('Regra', '-')}] ({row.get('Severidade', '-')}/{row.get('Status', '-')}) "
                            f"Qtd={row.get('Qtd_Afetados', 0)} | Lotes={row.get('Lotes_Afetados', '-')}"
                        )
                    else:
                        print(
                            f"[{row.get('Regra', '-')}] ({row.get('Severidade', '-')}/{row.get('Status', '-')}) "
                            f"Lote={row.get('Aviario_Lote', '-')} | JSON={row.get('Valor_JSON', '-')} x "
                            f"PDF={row.get('Valor_PDF', '-')} | Arquivo={row.get('Arquivo', '-')}"
                        )


if __name__ == "__main__":
    main()
