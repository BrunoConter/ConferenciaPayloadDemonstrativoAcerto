from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from conferencia_acertos.parser import EXPECTED_SCHEMA, ParsedPayload
from conferencia_acertos.pdf_extractor import PdfExtractedData


@dataclass
class ValidationResult:
    regra: str
    status: str  # "OK" | "FALHA" | "ALERTA"
    severidade: str  # "ALTA" | "MEDIA" | "BAIXA" | "INFO"
    valor_json: str | None
    valor_pdf: str | None
    detalhe: str


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_str).strip().upper()


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _parse_pdf_date(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def validate_payload(payload: ParsedPayload, pdf_data: PdfExtractedData) -> list[ValidationResult]:
    """Executa todas as regras de conferência AgroCenter (JSON) x MTech (PDF)."""
    results: list[ValidationResult] = []

    # 1. JSON Raiz e Schema
    if not payload.json_valido:
        results.append(
            ValidationResult(
                regra="JSON_RAIZ",
                status="FALHA",
                severidade="ALTA",
                valor_json=None,
                valor_pdf=None,
                detalhe=payload.json_erro or "JSON raiz inválido",
            )
        )
        return results

    schema_ok = payload.schema_versao == EXPECTED_SCHEMA
    results.append(
        ValidationResult(
            regra="SCHEMA_VERSAO",
            status="OK" if schema_ok else "FALHA",
            severidade="INFO" if schema_ok else "ALTA",
            valor_json=payload.schema_versao,
            valor_pdf=EXPECTED_SCHEMA,
            detalhe="Schema compatível" if schema_ok else f"Schema inesperado: esperado {EXPECTED_SCHEMA}",
        )
    )

    # 2. Cardinalidade 1:1 (1 payload -> 1 item em Data -> 1 binário PDF válido)
    pdf_ok = payload.pdf_base64_valido and pdf_data.pdf_valido
    card_ok = payload.qtd_itens_data == 1 and pdf_ok
    results.append(
        ValidationResult(
            regra="CARDINALIDADE_1_PARA_1",
            status="OK" if card_ok else "FALHA",
            severidade="INFO" if card_ok else "ALTA",
            valor_json=f"{payload.qtd_itens_data} item(ns) em Data",
            valor_pdf="1 PDF válido" if pdf_ok else "0 PDF válido",
            detalhe=(
                "Cardinalidade 1:1 confirmada (1 item em Data e 1 PDF íntegro)"
                if card_ok
                else (
                    f"Esperado 1:1 (1 item em Data e 1 PDF válido), obtido Data={payload.qtd_itens_data} "
                    f"e PDF={'válido' if pdf_ok else 'inválido'}"
                )
            ),
        )
    )

    # 3. Demais_Dados e formato composto aviario-lote
    results.append(
        ValidationResult(
            regra="DEMAIS_DADOS_INTEGRIDADE",
            status="OK" if payload.demais_dados_valido else "FALHA",
            severidade="INFO" if payload.demais_dados_valido else "ALTA",
            valor_json=payload.raw_demais_dados[:80] if payload.raw_demais_dados else "''",
            valor_pdf=None,
            detalhe=(
                "Demais_Dados preenchido e válido"
                if payload.demais_dados_valido
                else (payload.demais_dados_erro or "Demais_Dados inválido")
            ),
        )
    )

    dd = payload.demais_dados
    if dd is not None:
        comp_ok = bool(
            payload.extrato_aviario
            and payload.extrato_lote
            and payload.extrato_lote.strip() == dd.Lote.strip()
        )
        results.append(
            ValidationResult(
                regra="DEMAIS_DADOS_AVIARIO_LOTE_FORMATO",
                status="OK" if comp_ok else "FALHA",
                severidade="INFO" if comp_ok else "ALTA",
                valor_json=f"Numero_Extrato={dd.Numero_Extrato} | Lote={dd.Lote}",
                valor_pdf=None,
                detalhe=(
                    f"Lote composto válido: aviário={payload.extrato_aviario}, lote={payload.extrato_lote}"
                    if comp_ok
                    else f"Numero_Extrato ({dd.Numero_Extrato}) inconsistente com Lote ({dd.Lote})"
                ),
            )
        )

    # 4. PDF64 e Integridade do PDF
    pdf_err = payload.pdf_base64_erro or pdf_data.pdf_erro
    results.append(
        ValidationResult(
            regra="PDF_INTEGRIDADE",
            status="OK" if pdf_ok else "FALHA",
            severidade="INFO" if pdf_ok else "ALTA",
            valor_json=f"{len(payload.pdf_bytes or b'')} bytes" if payload.pdf_bytes else "0 bytes",
            valor_pdf=f"{pdf_data.pdf_paginas} pág(s)" if pdf_data.pdf_valido else "Corrompido",
            detalhe="PDF Base64 íntegro e legível" if pdf_ok else (pdf_err or "Falha no PDF"),
        )
    )

    if not pdf_ok:
        return results

    # 5. Consistência interna de BP entre páginas do PDF e batimento Cod_Cliente x BP
    unique_bps = sorted(set(pdf_data.bps_encontrados))
    bp_consistente = len(unique_bps) == 1
    results.append(
        ValidationResult(
            regra="BP_CONSISTENCIA_INTERNA_PDF",
            status="OK" if bp_consistente else "FALHA",
            severidade="INFO" if bp_consistente else "ALTA",
            valor_json=None,
            valor_pdf=", ".join(pdf_data.bps_encontrados) if pdf_data.bps_encontrados else "Ausente",
            detalhe=(
                f"BP consistente em {len(pdf_data.bps_encontrados)} ocorrência(s) no PDF ({unique_bps[0]})"
                if bp_consistente
                else f"BP ausente ou divergente entre páginas do PDF: {pdf_data.bps_encontrados}"
            ),
        )
    )

    cod_cli = (payload.cod_cliente or "").strip()
    bp_pdf = (pdf_data.bp or "").strip()
    if cod_cli and bp_pdf:
        match_bp = cod_cli == bp_pdf
        results.append(
            ValidationResult(
                regra="BATIMENTO_COD_CLIENTE_BP",
                status="OK" if match_bp else "FALHA",
                severidade="INFO" if match_bp else "ALTA",
                valor_json=cod_cli,
                valor_pdf=bp_pdf,
                detalhe=(
                    "Cod_Cliente igual ao BP do PDF"
                    if match_bp
                    else f"Divergência entre Cod_Cliente ({cod_cli}) no JSON e BP ({bp_pdf}) no PDF"
                ),
            )
        )

    # 6. Batimentos com Demais_Dados (quando presente)
    if dd is not None:
        # Aviario (JSON) x Produtor (PDF)
        aviario_norm = _normalize_text(dd.Aviario)
        produtor_norm = _normalize_text(pdf_data.produtor)
        match_prod = bool(aviario_norm and produtor_norm and aviario_norm == produtor_norm)
        results.append(
            ValidationResult(
                regra="BATIMENTO_AVIARIO_PRODUTOR",
                status="OK" if match_prod else "FALHA",
                severidade="INFO" if match_prod else "ALTA",
                valor_json=dd.Aviario,
                valor_pdf=pdf_data.produtor,
                detalhe=(
                    "Aviario (JSON) confere com PRODUTOR (PDF)"
                    if match_prod
                    else "Divergência entre Aviario (JSON) e PRODUTOR (PDF)"
                ),
            )
        )

        # Lote
        match_lote = dd.Lote.strip() == (pdf_data.lote_pdf or "").strip()
        results.append(
            ValidationResult(
                regra="BATIMENTO_LOTE",
                status="OK" if match_lote else "FALHA",
                severidade="INFO" if match_lote else "ALTA",
                valor_json=dd.Lote,
                valor_pdf=pdf_data.lote_pdf,
                detalhe="Lote confere" if match_lote else "Divergência no número do Lote",
            )
        )

        # Numero_Extrato (JSON) x Subtítulo Extrato (PDF)
        match_extrato = dd.Numero_Extrato.strip() == (pdf_data.numero_extrato_pdf or "").strip()
        results.append(
            ValidationResult(
                regra="BATIMENTO_NUMERO_EXTRATO",
                status="OK" if match_extrato else "FALHA",
                severidade="INFO" if match_extrato else "ALTA",
                valor_json=dd.Numero_Extrato,
                valor_pdf=pdf_data.numero_extrato_pdf,
                detalhe=(
                    "Numero_Extrato confere"
                    if match_extrato
                    else "Divergência no Numero_Extrato (JSON vs PDF)"
                ),
            )
        )

        # Lote Composto (aviario-lote) JSON x Cabeçalho PDF (AVIÁRIO - X / LOTE - Y)
        match_cab = (
            dd.Numero_Extrato.strip() == (pdf_data.aviario_lote_composto_pdf or "").strip()
        )
        results.append(
            ValidationResult(
                regra="BATIMENTO_AVIARIO_LOTE_CABECALHO",
                status="OK" if match_cab else "FALHA",
                severidade="INFO" if match_cab else "ALTA",
                valor_json=dd.Numero_Extrato,
                valor_pdf=pdf_data.aviario_lote_composto_pdf,
                detalhe=(
                    "Lote composto (aviario-lote) confere com cabeçalho AVIÁRIO/LOTE do PDF"
                    if match_cab
                    else "Divergência entre aviario-lote do JSON e cabeçalho AVIÁRIO/LOTE do PDF"
                ),
            )
        )

        # Lote Composto (aviario-lote) JSON x Termo de Quitação (última página do PDF)
        quitacao_comp = (
            f"{pdf_data.quitacao_aviario}-{pdf_data.quitacao_lote}"
            if pdf_data.quitacao_aviario and pdf_data.quitacao_lote
            else None
        )
        match_quit = bool(quitacao_comp and dd.Numero_Extrato.strip() == quitacao_comp)
        results.append(
            ValidationResult(
                regra="BATIMENTO_AVIARIO_LOTE_QUITACAO",
                status="OK" if match_quit else "FALHA",
                severidade="INFO" if match_quit else "ALTA",
                valor_json=dd.Numero_Extrato,
                valor_pdf=quitacao_comp,
                detalhe=(
                    "Lote composto (aviario-lote) confere com o Termo de Quitação (última página do PDF)"
                    if match_quit
                    else "Divergência ou ausência de aviario-lote no Termo de Quitação do PDF"
                ),
            )
        )

        # DataEmissao
        iso_json = _parse_iso_date(dd.DataEmissao)
        iso_pdf = _parse_pdf_date(pdf_data.data_pdf)
        match_data = bool(iso_json and iso_pdf and iso_json == iso_pdf)
        results.append(
            ValidationResult(
                regra="BATIMENTO_DATA_EMISSAO",
                status="OK" if match_data else "FALHA",
                severidade="INFO" if match_data else "MEDIA",
                valor_json=dd.DataEmissao,
                valor_pdf=pdf_data.data_pdf,
                detalhe=(
                    f"Data confere ({iso_json}; PDF em formato MM/DD/YYYY)"
                    if match_data
                    else f"Divergência de data: JSON={iso_json} vs PDF={iso_pdf} ({pdf_data.data_pdf})"
                ),
            )
        )

    # 7. Qualidade do template PDF (valor por extenso em inglês na declaração)
    if pdf_data.tem_valor_extenso_en:
        results.append(
            ValidationResult(
                regra="PDF_VALOR_EXTENSO_IDIOMA",
                status="ALERTA",
                severidade="BAIXA",
                valor_json=None,
                valor_pdf="Texto por extenso em inglês na declaração",
                detalhe="Declaração de recebimento do PDF exibe valor por extenso em inglês (ex: 'Seventy-Three Thousand...')",
            )
        )

    return results
