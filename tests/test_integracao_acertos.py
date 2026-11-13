from __future__ import annotations

from pathlib import Path

import pytest

from conferencia_acertos.cli import discover_payload_files
from conferencia_acertos.parser import (
    EXPECTED_SCHEMA,
    DemaisDadosModel,
    ParsedPayload,
    _split_numero_extrato,
    parse_payload_file,
)
from conferencia_acertos.pdf_extractor import (
    PdfExtractedData,
    _parse_float,
    compute_canonical_text_hash,
    extract_pdf_data,
)
from conferencia_acertos.validator import validate_payload


DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def _load_all_cases() -> list[tuple[str, ParsedPayload]]:
    files = discover_payload_files([DATA_RAW_DIR])
    cases: list[tuple[str, ParsedPayload]] = []
    for f, root_dir in files:
        for item in parse_payload_file(f, root_dir=root_dir):
            cases.append((item.arquivo_origem, item))
    return cases


PAYLOAD_CASES = _load_all_cases()
_PDF_CACHE: dict[str, PdfExtractedData] = {}


def _get_pdf_data(name: str, payload: ParsedPayload) -> PdfExtractedData:
    if name not in _PDF_CACHE:
        _PDF_CACHE[name] = extract_pdf_data(payload.pdf_bytes)
    return _PDF_CACHE[name]


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_contrato_json_e_schema(name: str, payload: ParsedPayload) -> None:
    assert payload.json_valido, f"[{name}] JSON inválido: {payload.json_erro}"
    assert payload.schema_versao == EXPECTED_SCHEMA, (
        f"[{name}] Schema inesperado: {payload.schema_versao!r} != {EXPECTED_SCHEMA!r}"
    )


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_cardinalidade_um_para_um(name: str, payload: ParsedPayload) -> None:
    assert payload.qtd_itens_data >= 1, (
        f"[{name}] Esperado ao menos 1 item em Data (1:1 por item), encontrado {payload.qtd_itens_data}"
    )
    assert payload.pdf_base64_valido, f"[{name}] PDF64 ausente ou inválido: {payload.pdf_base64_erro}"


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_demais_dados_valido(name: str, payload: ParsedPayload) -> None:
    assert payload.demais_dados_valido, f"[{name}] Falha em Demais_Dados: {payload.demais_dados_erro}"


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_pdf64_integro_e_legivel(name: str, payload: ParsedPayload) -> None:
    assert payload.pdf_base64_valido, f"[{name}] PDF64 inválido: {payload.pdf_base64_erro}"
    pdf_data = _get_pdf_data(name, payload)
    assert pdf_data.pdf_valido, f"[{name}] PDF corrompido ou ilegível: {pdf_data.pdf_erro}"
    assert pdf_data.pdf_paginas >= 1, f"[{name}] PDF sem páginas"


@pytest.mark.parametrize("name,payload", PAYLOAD_CASES, ids=[c[0] for c in PAYLOAD_CASES])
def test_batimento_agrocenter_vs_mtech(name: str, payload: ParsedPayload) -> None:
    pdf_data = _get_pdf_data(name, payload)
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
        data_pdf="27/07/2026",
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
    """Garante que o motor detecta quando um item não possui PDF válido ou Data está vazia."""
    payload, pdf_data = _build_synthetic_valid_pair()
    payload.qtd_itens_data = 0
    results = validate_payload(payload, pdf_data)
    card = next(r for r in results if r.regra == "CARDINALIDADE_1_PARA_1")
    assert card.status == "FALHA"


def test_hash_canonico_detecta_reordenacao() -> None:
    """Garante que linhas reordenadas na tabela do PDF produzem o mesmo hash canônico."""
    t1 = "TOTAL 30,304\n260720001 4,320\n260720005 3,780"
    t2 = "TOTAL 30,304\n260720005 3,780\n260720001 4,320"
    assert compute_canonical_text_hash(t1) == compute_canonical_text_hash(t2)


def test_lgpd_cod_cliente_ou_bp_ausente_reprova() -> None:
    """Garante que Cod_Cliente ou BP ausente/divergente reprova por risco LGPD."""
    payload, pdf_data = _build_synthetic_valid_pair()
    payload.cod_cliente = None
    results = validate_payload(payload, pdf_data)
    regra = next(r for r in results if r.regra == "BATIMENTO_COD_CLIENTE_BP")
    assert regra.status == "FALHA"
    assert regra.severidade == "ALTA"


def test_data_pdf_formato_eua_gera_alerta() -> None:
    """Garante que DATA do PDF em MM/DD/YYYY bate com JSON mas gera ALERTA de localização."""
    payload, pdf_data = _build_synthetic_valid_pair()
    pdf_data.data_pdf = "07/27/2026"
    results = validate_payload(payload, pdf_data)
    bat = next(r for r in results if r.regra == "BATIMENTO_DATA_EMISSAO")
    alerta = next(r for r in results if r.regra == "PDF_DATA_FORMATO_EUA")
    assert bat.status == "OK"
    assert alerta.status == "ALERTA"


def test_consistencia_zootecnica_e_financeira() -> None:
    """Garante detecção de inconsistências zootécnicas e financeiras no PDF."""
    payload, pdf_data = _build_synthetic_valid_pair()
    pdf_data.aves_alojadas = 10000
    pdf_data.aves_abatidas = 10500
    pdf_data.mortalidade_pct = 5.0
    pdf_data.viabilidade_pct = 90.0
    pdf_data.valor_lote = 50000.0
    pdf_data.valor_liquido = 55000.0
    results = validate_payload(payload, pdf_data)
    zoo = next(r for r in results if r.regra == "PDF_CONSISTENCIA_ZOOTECNICA")
    fin = next(r for r in results if r.regra == "PDF_CONSISTENCIA_FINANCEIRA")
    assert zoo.status == "FALHA"
    assert fin.status == "FALHA"


def test_parse_float_ptbr_e_enus() -> None:
    """Garante suporte dinâmico a valores numéricos em PT-BR e EN-US."""
    assert _parse_float("73.500,00") == pytest.approx(73500.0)
    assert _parse_float("73,500.00") == pytest.approx(73500.0)
    assert _parse_float("123,45") == pytest.approx(123.45)
    assert _parse_float("3.765") == pytest.approx(3.765)


def test_demais_dados_aceita_campos_extras_e_aviario_alfanumerico() -> None:
    """Garante flexibilidade de schema para novos payloads com campos adicionais."""
    model = DemaisDadosModel.model_validate({
        "Cod_Empresa": 1001,
        "Lote": "21",
        "DataEmissao": "2026-07-27T00:00:00",
        "Aviario": "1290",
        "Numero_Extrato": "A12-21",
        "BrimGrowSettlementsIRN": "uuid-1",
        "CampoNovo": "valor-extra",
    })
    assert model.model_extra == {"CampoNovo": "valor-extra"}
    assert _split_numero_extrato("A12-21") == ("A12", "21")


def test_batimento_aviario_por_codigo() -> None:
    """Aceita batimento quando JSON envia o código numérico do aviário."""
    payload, pdf_data = _build_synthetic_valid_pair()
    assert payload.demais_dados is not None
    payload.demais_dados.Aviario = "1290"
    results = validate_payload(payload, pdf_data)
    regra = next(r for r in results if r.regra == "BATIMENTO_AVIARIO_PRODUTOR")
    assert regra.status == "OK"


def test_parse_payload_encoding_bom_e_latin1(tmp_path: Path) -> None:
    """Garante leitura de payloads em UTF-8 com BOM e Latin-1."""
    raw = '{"Schema": "br.com.cvale.sap.extratoaves.v1", "Data": []}'
    p_bom = tmp_path / "bom.json"
    p_bom.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
    res_bom = parse_payload_file(p_bom, root_dir=tmp_path)
    assert res_bom[0].schema_versao == EXPECTED_SCHEMA

    raw_latin = '{"Schema": "br.com.cvale.sap.extratoaves.v1", "Data": [{"Aviario": "JOÃO"}]}'
    p_lat = tmp_path / "lat.json"
    p_lat.write_bytes(raw_latin.encode("latin-1"))
    res_lat = parse_payload_file(p_lat, root_dir=tmp_path)
    assert res_lat[0].json_valido is True


def test_bp_divergente_entre_paginas_e_irn_vazio() -> None:
    """Garante reprovação quando BP diverge entre páginas do PDF ou IRN é vazio."""
    payload, pdf_data = _build_synthetic_valid_pair()
    pdf_data.bps_encontrados = ["0100093258", "0100099999"]
    results = validate_payload(payload, pdf_data)
    bp_int = next(r for r in results if r.regra == "BP_CONSISTENCIA_INTERNA_PDF")
    assert bp_int.status == "FALHA"

    with pytest.raises(Exception):
        DemaisDadosModel.model_validate({
            "Cod_Empresa": 1001,
            "Lote": "21",
            "DataEmissao": "2026-07-27T00:00:00",
            "Aviario": "PRODUTOR",
            "Numero_Extrato": "1290-21",
            "BrimGrowSettlementsIRN": "   ",
        })


def test_database_exporter_e_notebooklm_e2e(tmp_path: Path) -> None:
    """Valida persistência SQLite, views e geração de exports/relatórios sem erros."""
    from conferencia_acertos.database import init_db, upsert_record
    from conferencia_acertos.exporter import (
        export_tabular,
        generate_executive_report,
        generate_html_dashboard,
        generate_issues_package,
    )
    from conferencia_acertos.notebooklm_exporter import generate_notebooklm_bundle

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    try:
        payload, pdf_data = _build_synthetic_valid_pair()
        validations = validate_payload(payload, pdf_data)
        upsert_record(conn, payload, pdf_data, validations, tmp_path / "fake.pdf")

        row = conn.execute("SELECT status_homologacao FROM vw_conferencia_completa").fetchone()
        assert row is not None and row[0] == "APROVADO"

        csv_conf, csv_div, xlsx = export_tabular(conn, tmp_path / "exports")
        assert csv_conf.exists() and csv_div.exists() and xlsx.exists()

        rep_md = generate_executive_report(conn, tmp_path / "reports" / "rel.md")
        rep_html = generate_html_dashboard(conn, tmp_path / "reports" / "rel.html")
        issues_csv, issues_md = generate_issues_package(conn, tmp_path / "reports")
        nlm = generate_notebooklm_bundle(conn, tmp_path / "reports" / "notebooklm")

        assert rep_md.exists() and "HOMOLOGADA" in rep_md.read_text(encoding="utf-8")
        assert rep_html.exists() and "APROVADO_COM_ALERTA" in rep_html.read_text(encoding="utf-8")
        assert issues_csv.exists() and issues_md.exists()
        assert nlm.exists()
    finally:
        conn.close()


def test_resolve_lote_key_e_export_aditivo_opcao_a(tmp_path: Path) -> None:
    """Garante pasta agnóstica por <aviario-lote> e consolidação por adição para duplicatas."""
    from conferencia_acertos.exporter import export_payload_bundle, resolve_lote_key

    p1, d1 = _build_synthetic_valid_pair()
    p1.arquivo_origem = "envio_1.txt"
    d1.pdf_bytes_sha256 = "aaaa1111" * 8
    lote_key = resolve_lote_key(p1, d1)
    assert lote_key == "1290-21"

    bundle_dir = tmp_path / lote_key
    export_payload_bundle(bundle_dir, lote_key, p1, d1, validate_payload(p1, d1))

    p2, d2 = _build_synthetic_valid_pair()
    p2.arquivo_origem = "envio_2.txt"
    p2.pdf_bytes = b"%PDF-1.4-v2"
    d2.pdf_bytes_sha256 = "bbbb2222" * 8
    export_payload_bundle(bundle_dir, lote_key, p2, d2, validate_payload(p2, d2))

    assert (bundle_dir / "1290-21_aaaa1111.pdf").exists()
    assert (bundle_dir / "1290-21_bbbb2222.pdf").exists()
    payload_json = (bundle_dir / "payload.json").read_text(encoding="utf-8")
    assert '"qtd_ocorrencias": 2' in payload_json
    rel_md = (bundle_dir / "relatorio_acuracia.md").read_text(encoding="utf-8")
    assert "Ocorrência #1" in rel_md and "Ocorrência #2" in rel_md


def test_unicidade_por_aviario_lote() -> None:
    """Detecta múltiplos IRNs ou hashes binários divergentes de PDF64 por aviário-lote (reenvio idêntico é aceito)."""
    grupos: dict[str, list[tuple[str, str, str | None, str | None, str | None]]] = {}
    for name, payload in PAYLOAD_CASES:
        pdf_data = _get_pdf_data(name, payload)
        chave = (
            payload.demais_dados.Numero_Extrato
            if payload.demais_dados
            else pdf_data.aviario_lote_composto_pdf or name
        )
        irn = payload.demais_dados.BrimGrowSettlementsIRN if payload.demais_dados else None
        grupos.setdefault(chave, []).append(
            (
                name,
                payload.sha256_arquivo[:12],
                pdf_data.pdf_bytes_sha256,
                pdf_data.pdf_texto_canonico_sha256,
                irn,
            )
        )

    inconsistentes = {
        k: v
        for k, v in grupos.items()
        if len({x[2] for x in v if x[2]}) > 1 or len({x[4] for x in v if x[4]}) > 1
    }
    assert not inconsistentes, "Inconsistências de IRN ou hash binário PDF64 detectadas por aviário-lote: " + "; ".join(
        f"{k}: {len(v)} payloads (hashes_arquivo={len({x[1] for x in v})}, "
        f"hashes_pdf_binario={len({x[2] for x in v if x[2]})}, "
        f"hashes_conteudo_canonico={len({x[3] for x in v if x[3]})}, "
        f"irns_distintos={len({x[4] for x in v if x[4]})})"
        for k, v in inconsistentes.items()
    )


def test_build_issues_rows_separa_pares_distintos() -> None:
    """Garante que pares distintos (Cod_Cliente, BP) na mesma regra gerem issues separadas."""
    import pandas as pd

    from conferencia_acertos.exporter import _build_issues_rows

    df_div = pd.DataFrame(
        [
            {
                "regra": "BATIMENTO_COD_CLIENTE_BP",
                "status": "FALHA",
                "severidade": "ALTA",
                "valor_json": "0010537517",
                "valor_pdf": "0001000419",
                "arquivo_origem": "arq1.json",
                "aviario_lote": "1290-21",
                "detalhe": "Divergência Cod_Cliente x BP",
            },
            {
                "regra": "BATIMENTO_COD_CLIENTE_BP",
                "status": "FALHA",
                "severidade": "ALTA",
                "valor_json": "0010537517",
                "valor_pdf": "0001000419",
                "arquivo_origem": "arq2.json",
                "aviario_lote": "1290-21",
                "detalhe": "Divergência Cod_Cliente x BP",
            },
            {
                "regra": "BATIMENTO_COD_CLIENTE_BP",
                "status": "FALHA",
                "severidade": "ALTA",
                "valor_json": "0010536025",
                "valor_pdf": "0001000083",
                "arquivo_origem": "arq3.json",
                "aviario_lote": "4112-40",
                "detalhe": "Divergência Cod_Cliente x BP",
            },
        ]
    )

    issues_consolidadas = _build_issues_rows(df_div, pd.DataFrame())
    assert len(issues_consolidadas) == 1
    assert issues_consolidadas[0]["Qtd_Afetados"] == 3
    assert "0010537517 -> 0001000419" in str(issues_consolidadas[0]["Descricao"])
    assert "0010536025 -> 0001000083" in str(issues_consolidadas[0]["Descricao"])
    assert issues_consolidadas[0]["Lotes_Afetados"] == "1290-21, 4112-40"

    issues = _build_issues_rows(df_div, pd.DataFrame(), split_by_pair=True)
    assert len(issues) == 2
    pares = {(item["Evidencia_JSON"], item["Evidencia_PDF"]): item for item in issues}
    assert ("0010537517", "0001000419") in pares
    assert ("0010536025", "0001000083") in pares
    assert pares[("0010537517", "0001000419")]["Qtd_Afetados"] == 2
    assert pares[("0010537517", "0001000419")]["Lotes_Afetados"] == "1290-21"
    assert pares[("0010536025", "0001000083")]["Lotes_Afetados"] == "4112-40"


def test_query_issues_filtros_e_agrupamentos(tmp_path: Path) -> None:
    """Valida filtros e modos de agrupamento (par, lote, regra, nenhum) em query_issues."""
    from conferencia_acertos.database import init_db, upsert_record
    from conferencia_acertos.exporter import query_issues

    conn = init_db(tmp_path / "test_issues.db")
    try:
        p1, d1 = _build_synthetic_valid_pair()
        p1.arquivo_origem = "p1.json"
        p1.sha256_arquivo = "1111" * 16
        p1.cod_cliente = "0010537517"
        assert p1.demais_dados is not None
        p1.demais_dados.Numero_Extrato = "1290-21"
        d1.bp = "0001000419"
        d1.bps_encontrados = ["0001000419"]

        p2, d2 = _build_synthetic_valid_pair()
        p2.arquivo_origem = "p2.json"
        p2.sha256_arquivo = "2222" * 16
        p2.cod_cliente = "0010536025"
        assert p2.demais_dados is not None
        p2.demais_dados.Numero_Extrato = "4112-40"
        d2.aviario_codigo = "4112"
        d2.lote_pdf = "40"
        d2.aviario_lote_composto_pdf = "4112-40"
        d2.bp = "0001000083"
        d2.bps_encontrados = ["0001000083"]

        upsert_record(conn, p1, d1, validate_payload(p1, d1), tmp_path / "p1.pdf")
        upsert_record(conn, p2, d2, validate_payload(p2, d2), tmp_path / "p2.pdf")

        por_par = query_issues(conn, regra="BATIMENTO_COD_CLIENTE_BP", status="FALHA", group_by="par")
        assert len(por_par) == 2
        assert {r["Lotes_Afetados"] for r in por_par} == {"1290-21", "4112-40"}

        filtrado_lote = query_issues(conn, regra="BATIMENTO_COD_CLIENTE_BP", lote="4112-40", group_by="lote")
        assert len(filtrado_lote) == 1
        assert filtrado_lote[0]["Aviario_Lote"] == "4112-40"

        por_regra = query_issues(conn, regra="BATIMENTO_COD_CLIENTE_BP", group_by="regra")
        assert len(por_regra) == 1
        assert por_regra[0]["Qtd_Afetados"] == 2
        assert "1290-21" in str(por_regra[0]["Lotes_Afetados"])
        assert "4112-40" in str(por_regra[0]["Lotes_Afetados"])

        sem_agrupamento = query_issues(conn, regra="BATIMENTO_COD_CLIENTE_BP", group_by="nenhum")
        assert len(sem_agrupamento) == 2
    finally:
        conn.close()


def test_vw_diagnostico_cod_cliente_bp(tmp_path: Path) -> None:
    """Valida classificação de BP compartilhado vs divergência cadastral isolada na view SQLite."""
    from conferencia_acertos.database import init_db, upsert_record

    conn = init_db(tmp_path / "diag.db")
    try:
        # Produtor A válido (Cod_Cliente == BP == 0100139505)
        p_ok, d_ok = _build_synthetic_valid_pair()
        p_ok.arquivo_origem = "ok.json"
        p_ok.sha256_arquivo = "aaaa" * 16
        p_ok.cod_cliente = "0100139505"
        d_ok.bp = "0100139505"
        d_ok.bps_encontrados = ["0100139505"]
        d_ok.produtor = "PRODUTOR TITULAR"
        upsert_record(conn, p_ok, d_ok, validate_payload(p_ok, d_ok), tmp_path / "ok.pdf")

        # Produtor B com BP compartilhado do Produtor A
        p_comp, d_comp = _build_synthetic_valid_pair()
        p_comp.arquivo_origem = "comp.json"
        p_comp.sha256_arquivo = "bbbb" * 16
        p_comp.cod_cliente = "0100116602"
        assert p_comp.demais_dados is not None
        p_comp.demais_dados.Numero_Extrato = "1036-53"
        d_comp.bp = "0100139505"
        d_comp.bps_encontrados = ["0100139505"]
        d_comp.produtor = "PRODUTOR PARCEIRO"
        upsert_record(conn, p_comp, d_comp, validate_payload(p_comp, d_comp), tmp_path / "comp.pdf")

        # Produtor C com divergência isolada
        p_iso, d_iso = _build_synthetic_valid_pair()
        p_iso.arquivo_origem = "iso.json"
        p_iso.sha256_arquivo = "cccc" * 16
        p_iso.cod_cliente = "0100034342"
        assert p_iso.demais_dados is not None
        p_iso.demais_dados.Numero_Extrato = "1290-21"
        d_iso.bp = "0100093258"
        d_iso.bps_encontrados = ["0100093258"]
        d_iso.produtor = "PRODUTOR ISOLADO"
        upsert_record(conn, p_iso, d_iso, validate_payload(p_iso, d_iso), tmp_path / "iso.pdf")

        rows = conn.execute(
            "SELECT cod_cliente_json, bp_pdf, classificacao_causa, titular_bp_na_base "
            "FROM vw_diagnostico_cod_cliente_bp"
        ).fetchall()
        by_cli = {r[0]: r for r in rows}
        assert by_cli["0100116602"][2] == "BP_COMPARTILHADO_OUTRO_PRODUTOR"
        assert by_cli["0100116602"][3] == "PRODUTOR TITULAR"
        assert by_cli["0100034342"][2] == "DIVERGENCIA_CADASTRAL_ISOLADA"
        assert by_cli["0100034342"][3] is None

        from conferencia_acertos.exporter import generate_issues_package

        _, md_path = generate_issues_package(conn, tmp_path / "reports")
        md_text = md_path.read_text(encoding="utf-8")
        assert "cod_BP_Proprietario" in md_text
        assert "cod_BP_Responsavel" in md_text
    finally:
        conn.close()


def test_parse_cod_bp_markdown_e_cruzamento_ref() -> None:
    """Valida extração da base oficial data/cod_bp/cod_BP_integracao.md."""
    from conferencia_acertos.reference_bp import parse_cod_bp_markdown

    md_path = Path("data/cod_bp/cod_BP_integracao.md")
    if not md_path.exists():
        pytest.skip("Base data/cod_bp/cod_BP_integracao.md ausente")
    records = parse_cod_bp_markdown(md_path)
    assert len(records) == 1161
    by_av = {r.aviario: r for r in records}
    assert by_av["1036"].cod_bp_proprietario == "0100116602"
    assert by_av["1290"].cod_bp_proprietario == "0100034342"
    assert by_av["1290"].cod_bp_responsavel == "0100093258"


def test_reenvio_consistente_nao_gera_issue_e_inconsistente_gera(tmp_path: Path) -> None:
    """Reenvio com mesmo IRN e mesmo SHA-256 de PDF64 não gera issue; IRN ou PDF64 distinto gera."""
    from conferencia_acertos.database import init_db, upsert_record
    from conferencia_acertos.exporter import query_issues

    conn = init_db(tmp_path / "reenvio.db")
    try:
        # 1. Reenvio consistente (mesmo IRN e mesmo pdf_bytes_sha256)
        p1, d1 = _build_synthetic_valid_pair()
        p1.arquivo_origem = "r1.json"
        p1.sha256_arquivo = "1111" * 16
        d1.pdf_bytes_sha256 = "aaaa" * 16
        p2, d2 = _build_synthetic_valid_pair()
        p2.arquivo_origem = "r2.json"
        p2.sha256_arquivo = "2222" * 16
        d2.pdf_bytes_sha256 = "aaaa" * 16
        upsert_record(conn, p1, d1, validate_payload(p1, d1), tmp_path / "r1.pdf")
        upsert_record(conn, p2, d2, validate_payload(p2, d2), tmp_path / "r2.pdf")

        assert query_issues(conn, status="FALHA", group_by="par") == []

        # 2. Novo lote com IRN distinto
        p3, d3 = _build_synthetic_valid_pair()
        p3.arquivo_origem = "i1.json"
        p3.sha256_arquivo = "3333" * 16
        assert p3.demais_dados is not None
        p3.demais_dados.Numero_Extrato = "9999-10"
        p3.demais_dados.BrimGrowSettlementsIRN = "irn-1"
        d3.aviario_codigo = "9999"
        d3.lote_pdf = "10"
        d3.aviario_lote_composto_pdf = "9999-10"
        d3.pdf_bytes_sha256 = "bbbb" * 16

        p4, d4 = _build_synthetic_valid_pair()
        p4.arquivo_origem = "i2.json"
        p4.sha256_arquivo = "4444" * 16
        assert p4.demais_dados is not None
        p4.demais_dados.Numero_Extrato = "9999-10"
        p4.demais_dados.BrimGrowSettlementsIRN = "irn-2"
        d4.aviario_codigo = "9999"
        d4.lote_pdf = "10"
        d4.aviario_lote_composto_pdf = "9999-10"
        d4.pdf_bytes_sha256 = "bbbb" * 16

        upsert_record(conn, p3, d3, validate_payload(p3, d3), tmp_path / "i1.pdf")
        upsert_record(conn, p4, d4, validate_payload(p4, d4), tmp_path / "i2.pdf")

        issues_falha = query_issues(conn, regra="IRN", status="FALHA", group_by="par")
        assert len(issues_falha) == 1
        assert issues_falha[0]["Lotes_Afetados"] == "9999-10"
    finally:
        conn.close()
