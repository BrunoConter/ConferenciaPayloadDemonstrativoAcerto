from __future__ import annotations

from pathlib import Path

import pytest

from conferencia_acertos.cli import discover_payload_files
from conferencia_acertos.parser import EXPECTED_SCHEMA, DemaisDadosModel, ParsedPayload, parse_payload_file
from conferencia_acertos.pdf_extractor import PdfExtractedData, compute_canonical_text_hash, extract_pdf_data
from conferencia_acertos.validator import validate_payload


DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def _load_all_cases() -> list[tuple[str, ParsedPayload]]:
    files = discover_payload_files([DATA_RAW_DIR])
    cases: list[tuple[str, ParsedPayload]] = []
    for f in files:
        for item in parse_payload_file(f):
            cases.append((item.arquivo_origem, item))
    return cases


PAYLOAD_CASES = _load_all_cases()


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_contrato_json_e_schema(name: str, payload: ParsedPayload) -> None:
    assert payload.json_valido, f"[{name}] JSON inválido: {payload.json_erro}"
    assert payload.schema_versao == EXPECTED_SCHEMA, (
        f"[{name}] Schema inesperado: {payload.schema_versao!r} != {EXPECTED_SCHEMA!r}"
    )


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_cardinalidade_um_para_um(name: str, payload: ParsedPayload) -> None:
    assert payload.qtd_itens_data == 1, (
        f"[{name}] Esperado exatamente 1 item em Data (1:1), encontrado {payload.qtd_itens_data}"
    )
    assert payload.pdf_base64_valido, f"[{name}] PDF64 ausente ou inválido: {payload.pdf_base64_erro}"


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_demais_dados_valido(name: str, payload: ParsedPayload) -> None:
    assert payload.demais_dados_valido, f"[{name}] Falha em Demais_Dados: {payload.demais_dados_erro}"


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_pdf64_integro_e_legivel(name: str, payload: ParsedPayload) -> None:
    assert payload.pdf_base64_valido, f"[{name}] PDF64 inválido: {payload.pdf_base64_erro}"
    pdf_data = extract_pdf_data(payload.pdf_bytes)
    assert pdf_data.pdf_valido, f"[{name}] PDF corrompido ou ilegível: {pdf_data.pdf_erro}"
    assert pdf_data.pdf_paginas >= 1, f"[{name}] PDF sem páginas"


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_batimento_agrocenter_vs_mtech(name: str, payload: ParsedPayload) -> None:
    pdf_data = extract_pdf_data(payload.pdf_bytes)
    if not payload.pdf_base64_valido or not pdf_data.pdf_valido:
        pytest.fail(
            f"[{name}] Impossível realizar batimento: PDF inválido ({pdf_data.pdf_erro or payload.pdf_base64_erro})"
        )

    if not payload.demais_dados_valido:
        pytest.fail(f"[{name}] Impossível realizar batimento completo: {payload.demais_dados_erro}")

    results = validate_payload(payload, pdf_data)
    falhas = [r for r in results if r.status == "FALHA"]
    assert not falhas, f"[{name}] Discrepâncias encontradas: " + "; ".join(
        f"{r.regra}: JSON={r.valor_json!r} vs PDF={r.valor_pdf!r} ({r.detalhe})" for r in falhas
    )


def _build_synthetic_valid_pair() -> tuple[ParsedPayload, PdfExtractedData]:
    payload = ParsedPayload(
        arquivo_origem="sintetico.txt",
        caminho_origem=Path("sintetico.txt"),
        sha256_arquivo="0" * 64,
        json_valido=True,
        json_erro=None,
        schema_versao=EXPECTED_SCHEMA,
        qtd_itens_data=1,
        item_indice=1,
        cod_cliente="0100093258",
        demais_dados_valido=True,
        demais_dados_erro=None,
        demais_dados=DemaisDadosModel(
            Cod_Empresa=1001,
            Lote="21",
            DataEmissao="2026-07-27T00:00:00",
            Aviario="REINALDO JOSE ARAGAO CORREIA",
            Numero_Extrato="1290-21",
            BrimGrowSettlementsIRN="d7949dbf-cc18-4f24-a5ac-2f9fb820df12",
        ),
        raw_demais_dados="{}",
        extrato_aviario="1290",
        extrato_lote="21",
        pdf_bytes=b"%PDF-1.4",
        pdf_base64_valido=True,
        pdf_base64_erro=None,
    )
    pdf_data = PdfExtractedData(
        pdf_valido=True,
        pdf_erro=None,
        pdf_paginas=3,
        texto_completo="ok",
        produtor="REINALDO JOSE ARAGAO CORREIA",
        bp="0100093258",
        bps_encontrados=["0100093258", "0100093258"],
        data_pdf="07/27/2026",
        aviario_codigo="1290",
        lote_pdf="21",
        numero_extrato_pdf="1290-21",
        aviario_lote_composto_pdf="1290-21",
        quitacao_aviario="1290",
        quitacao_lote="21",
        tem_valor_extenso_en=False,
    )
    return payload, pdf_data


def test_motor_validacao_cenario_conforme() -> None:
    """Garante que o motor aprova quando JSON e PDF estão 100% alinhados."""
    payload, pdf_data = _build_synthetic_valid_pair()
    results = validate_payload(payload, pdf_data)
    assert all(r.status == "OK" for r in results), results


def test_motor_reprova_quebra_cardinalidade_1_para_1() -> None:
    """Garante que o motor detecta quando um payload traz mais de 1 item em Data."""
    payload, pdf_data = _build_synthetic_valid_pair()
    payload.qtd_itens_data = 2
    results = validate_payload(payload, pdf_data)
    card = next(r for r in results if r.regra == "CARDINALIDADE_1_PARA_1")
    assert card.status == "FALHA"


def test_hash_canonico_detecta_reordenacao() -> None:
    """Garante que linhas reordenadas na tabela do PDF produzem o mesmo hash canônico."""
    t1 = "TOTAL 30,304\n260720001 4,320\n260720005 3,780"
    t2 = "TOTAL 30,304\n260720005 3,780\n260720001 4,320"
    assert compute_canonical_text_hash(t1) == compute_canonical_text_hash(t2)


def test_unicidade_por_aviario_lote() -> None:
    """Detecta reenvios duplicados para o mesmo aviário-lote com hashes distintos."""
    grupos: dict[str, list[tuple[str, str, str | None]]] = {}
    for name, payload in PAYLOAD_CASES:
        pdf_data = extract_pdf_data(payload.pdf_bytes)
        chave = (
            payload.demais_dados.Numero_Extrato
            if payload.demais_dados
            else pdf_data.aviario_lote_composto_pdf or name
        )
        grupos.setdefault(chave, []).append(
            (name, payload.sha256_arquivo[:12], pdf_data.pdf_texto_canonico_sha256)
        )

    duplicados = {k: v for k, v in grupos.items() if len(v) > 1}
    assert not duplicados, "Duplicidades detectadas por aviário-lote: " + "; ".join(
        f"{k}: {len(v)} payloads (hashes_arquivo={len({x[1] for x in v})}, "
        f"hashes_conteudo_canonico={len({x[2] for x in v})})"
        for k, v in duplicados.items()
    )
