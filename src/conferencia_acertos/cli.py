from __future__ import annotations

import argparse
from pathlib import Path

from conferencia_acertos.database import init_db, upsert_record
from conferencia_acertos.exporter import (
    export_payload_bundle,
    export_tabular,
    generate_duplicity_diff_report,
    generate_executive_report,
    generate_html_dashboard,
    generate_issues_package,
)
from conferencia_acertos.parser import parse_payload_file
from conferencia_acertos.pdf_extractor import extract_pdf_data
from conferencia_acertos.validator import validate_payload


def discover_payload_files(input_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in input_dirs:
        if not directory.exists():
            continue
        for ext in ("*.txt", "*.json"):
            files.extend(directory.glob(ext))
    return sorted(set(files))


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
    # Remove PDFs soltos legados na raiz de data/pdf/ (agora organizados em subpastas)
    for legacy_pdf in pdf_dir.glob("*.pdf"):
        legacy_pdf.unlink()

    conn = init_db(db_path)

    total_items = 0
    try:
        for file_path in files:
            parsed_items = parse_payload_file(file_path)
            for item in parsed_items:
                total_items += 1
                pdf_data = extract_pdf_data(item.pdf_bytes)
                validations = validate_payload(item, pdf_data)

                safe_stem = (
                    item.arquivo_origem.replace(" ", "_")
                    .replace(".txt", "")
                    .replace(".json", "")
                    .replace("[", "_")
                    .replace("]", "")
                )
                bundle_dir = pdf_dir / safe_stem
                pdf_saved_path = export_payload_bundle(
                    bundle_dir=bundle_dir,
                    safe_stem=safe_stem,
                    payload=item,
                    pdf_data=pdf_data,
                    validations=validations,
                )

                upsert_record(conn, item, pdf_data, validations, pdf_saved_path)

                falhas = sum(1 for v in validations if v.status == "FALHA")
                alertas = sum(1 for v in validations if v.status == "ALERTA")
                print(
                    f"[{item.arquivo_origem}] itens_data={item.qtd_itens_data} "
                    f"falhas={falhas} alertas={alertas} -> {bundle_dir}"
                )

        csv_conf, csv_div, xlsx = export_tabular(conn, exports_dir)
        rep = generate_executive_report(conn, report_path)
        rep_html = generate_html_dashboard(conn, report_path.with_suffix(".html"))
        issues_csv, issues_md = generate_issues_package(conn, report_path.parent)
        diff_md = generate_duplicity_diff_report(conn, report_path.parent / "diff_duplicidades.md")
        print(f"\nProcessados {total_items} registro(s) de {len(files)} arquivo(s).")
        print(f"SQLite: {db_path}")
        print(f"Exports: {csv_conf}, {csv_div}, {xlsx}")
        print(f"Relatórios: {rep}, {rep_html}, {issues_csv}, {issues_md}, {diff_md}")
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

    args = parser.parse_args()
    if args.command == "run":
        run_pipeline(
            input_dirs=args.input,
            db_path=args.db,
            pdf_dir=args.pdf_dir,
            exports_dir=args.exports_dir,
            report_path=args.report,
        )


if __name__ == "__main__":
    main()
