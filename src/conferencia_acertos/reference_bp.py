from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AviarioBpRef:
    aviario: str
    nome_proprietario_aviario: str
    cod_bp_proprietario: str
    nome_responsavel_granja: str
    cod_bp_responsavel: str


def parse_cod_bp_markdown(md_path: Path) -> list[AviarioBpRef]:
    """Extrai tabela Markdown Aviário × Proprietário × Responsável para registros estruturados."""
    if not md_path.exists():
        return []

    records: list[AviarioBpRef] = []
    for raw_line in md_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) != 5:
            continue
        aviario, prop_nome, prop_bp, resp_nome, resp_bp = parts
        if aviario.lower() == "aviario" or set(aviario) <= {"-", " "}:
            continue
        records.append(
            AviarioBpRef(
                aviario=aviario,
                nome_proprietario_aviario=prop_nome,
                cod_bp_proprietario=prop_bp,
                nome_responsavel_granja=resp_nome,
                cod_bp_responsavel=resp_bp,
            )
        )
    return records


def export_cod_bp_csv(records: list[AviarioBpRef], csv_path: Path) -> Path:
    """Exporta os registros de referência Aviário × BP para CSV UTF-8."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "aviario",
            "nome_proprietario_aviario",
            "cod_bp_proprietario",
            "nome_responsavel_granja",
            "cod_bp_responsavel",
        ])
        for rec in records:
            writer.writerow([
                rec.aviario,
                rec.nome_proprietario_aviario,
                rec.cod_bp_proprietario,
                rec.nome_responsavel_granja,
                rec.cod_bp_responsavel,
            ])
    return csv_path
