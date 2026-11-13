from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from conferencia_acertos.parser import ParsedPayload
from conferencia_acertos.pdf_extractor import PdfExtractedData
from conferencia_acertos.validator import ValidationResult


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_origem TEXT NOT NULL UNIQUE,
    arquivo_pai TEXT,
    sha256_arquivo TEXT NOT NULL,
    schema_versao TEXT,
    qtd_itens_data INTEGER NOT NULL DEFAULT 1,
    item_indice INTEGER NOT NULL DEFAULT 1,
    cod_cliente TEXT,
    pdf_valido INTEGER NOT NULL,
    pdf_tamanho_bytes INTEGER NOT NULL,
    pdf_paginas INTEGER NOT NULL,
    pdf_bytes_sha256 TEXT,
    pdf_texto_canonico_sha256 TEXT,
    pdf_caminho TEXT,
    processado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acertos_json (
    payload_id INTEGER PRIMARY KEY,
    demais_dados_valido INTEGER NOT NULL,
    cod_empresa INTEGER,
    lote TEXT,
    data_emissao TEXT,
    aviario TEXT,
    numero_extrato TEXT,
    extrato_aviario TEXT,
    extrato_lote TEXT,
    brim_grow_settlements_irn TEXT,
    raw_demais_dados TEXT,
    FOREIGN KEY (payload_id) REFERENCES payloads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS acertos_pdf (
    payload_id INTEGER PRIMARY KEY,
    produtor TEXT,
    matricula TEXT,
    bp TEXT,
    bps_encontrados TEXT,
    municipio TEXT,
    uf TEXT,
    data_pdf TEXT,
    tecnico TEXT,
    aviario_codigo TEXT,
    lote_pdf TEXT,
    numero_extrato_pdf TEXT,
    quitacao_aviario TEXT,
    quitacao_lote TEXT,
    aves_alojadas INTEGER,
    aves_abatidas INTEGER,
    mortalidade_pct REAL,
    viabilidade_pct REAL,
    conversao_alimentar REAL,
    peso_lote REAL,
    peso_medio REAL,
    iep REAL,
    valor_base REAL,
    valor_lote REAL,
    valor_liquido REAL,
    valor_por_m2 REAL,
    FOREIGN KEY (payload_id) REFERENCES payloads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS validacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_id INTEGER NOT NULL,
    regra TEXT NOT NULL,
    status TEXT NOT NULL,
    severidade TEXT NOT NULL,
    valor_json TEXT,
    valor_pdf TEXT,
    detalhe TEXT NOT NULL,
    FOREIGN KEY (payload_id) REFERENCES payloads(id) ON DELETE CASCADE
);

DROP VIEW IF EXISTS vw_conferencia_completa;
CREATE VIEW vw_conferencia_completa AS
SELECT
    p.id AS payload_id,
    p.arquivo_origem,
    p.arquivo_pai,
    p.schema_versao,
    p.qtd_itens_data,
    p.item_indice,
    p.cod_cliente AS json_cod_cliente,
    j.demais_dados_valido,
    j.cod_empresa AS json_cod_empresa,
    j.lote AS json_lote,
    j.data_emissao AS json_data_emissao,
    j.aviario AS json_aviario,
    j.numero_extrato AS json_numero_extrato,
    j.extrato_aviario AS json_extrato_aviario,
    j.extrato_lote AS json_extrato_lote,
    j.brim_grow_settlements_irn AS json_irn,
    p.pdf_valido,
    p.pdf_paginas,
    p.pdf_tamanho_bytes,
    p.sha256_arquivo,
    p.pdf_bytes_sha256,
    p.pdf_texto_canonico_sha256,
    d.produtor AS pdf_produtor,
    d.bp AS pdf_bp,
    d.bps_encontrados AS pdf_bps_encontrados,
    d.matricula AS pdf_matricula,
    d.municipio AS pdf_municipio,
    d.uf AS pdf_uf,
    d.data_pdf AS pdf_data,
    d.aviario_codigo AS pdf_aviario_codigo,
    d.lote_pdf AS pdf_lote,
    d.numero_extrato_pdf AS pdf_numero_extrato,
    d.quitacao_aviario AS pdf_quitacao_aviario,
    d.quitacao_lote AS pdf_quitacao_lote,
    d.aves_alojadas,
    d.aves_abatidas,
    d.mortalidade_pct,
    d.viabilidade_pct,
    d.conversao_alimentar,
    d.peso_lote,
    d.peso_medio,
    d.iep,
    d.valor_base,
    d.valor_lote,
    d.valor_liquido,
    d.valor_por_m2,
    (SELECT COUNT(*) FROM validacoes v WHERE v.payload_id = p.id AND v.status = 'FALHA') AS qtd_falhas,
    (SELECT COUNT(*) FROM validacoes v WHERE v.payload_id = p.id AND v.status = 'ALERTA') AS qtd_alertas,
    CASE
        WHEN EXISTS (SELECT 1 FROM validacoes v WHERE v.payload_id = p.id AND v.status = 'FALHA') THEN 'REPROVADO'
        WHEN EXISTS (SELECT 1 FROM validacoes v WHERE v.payload_id = p.id AND v.status = 'ALERTA') THEN 'APROVADO_COM_ALERTA'
        ELSE 'APROVADO'
    END AS status_homologacao,
    p.pdf_caminho,
    p.processado_em
FROM payloads p
LEFT JOIN acertos_json j ON j.payload_id = p.id
LEFT JOIN acertos_pdf d ON d.payload_id = p.id;

DROP VIEW IF EXISTS vw_divergencias;
CREATE VIEW vw_divergencias AS
SELECT
    p.arquivo_origem,
    p.arquivo_pai,
    COALESCE(
        NULLIF(j.numero_extrato, ''),
        CASE
            WHEN d.aviario_codigo IS NOT NULL AND d.lote_pdf IS NOT NULL
            THEN d.aviario_codigo || '-' || d.lote_pdf
            ELSE p.arquivo_origem
        END
    ) AS aviario_lote,
    j.brim_grow_settlements_irn AS irn,
    v.regra,
    v.status,
    v.severidade,
    v.valor_json,
    v.valor_pdf,
    v.detalhe
FROM validacoes v
JOIN payloads p ON p.id = v.payload_id
LEFT JOIN acertos_json j ON j.payload_id = p.id
LEFT JOIN acertos_pdf d ON d.payload_id = p.id
WHERE v.status != 'OK'
ORDER BY
    CASE v.status WHEN 'FALHA' THEN 1 WHEN 'ALERTA' THEN 2 ELSE 3 END,
    CASE v.severidade WHEN 'ALTA' THEN 1 WHEN 'MEDIA' THEN 2 WHEN 'BAIXA' THEN 3 ELSE 4 END,
    aviario_lote,
    p.arquivo_origem;

DROP VIEW IF EXISTS vw_duplicidades_lote;
CREATE VIEW vw_duplicidades_lote AS
WITH base AS (
    SELECT
        COALESCE(
            NULLIF(j.numero_extrato, ''),
            CASE
                WHEN d.aviario_codigo IS NOT NULL AND d.lote_pdf IS NOT NULL
                THEN d.aviario_codigo || '-' || d.lote_pdf
                ELSE p.arquivo_origem
            END
        ) AS aviario_lote,
        p.arquivo_origem,
        p.sha256_arquivo,
        p.pdf_bytes_sha256,
        p.pdf_texto_canonico_sha256,
        j.brim_grow_settlements_irn
    FROM payloads p
    LEFT JOIN acertos_json j ON j.payload_id = p.id
    LEFT JOIN acertos_pdf d ON d.payload_id = p.id
)
SELECT
    aviario_lote,
    COUNT(*) AS qtd_payloads,
    COUNT(DISTINCT sha256_arquivo) AS qtd_hashes_arquivo_distintos,
    COUNT(DISTINCT pdf_bytes_sha256) AS qtd_hashes_pdf_binario_distintos,
    COUNT(DISTINCT pdf_texto_canonico_sha256) AS qtd_hashes_conteudo_canonico_distintos,
    COUNT(DISTINCT brim_grow_settlements_irn) AS qtd_irns_distintos,
    CASE
        WHEN COUNT(DISTINCT brim_grow_settlements_irn) > 1 OR COUNT(DISTINCT pdf_bytes_sha256) > 1 THEN 1
        ELSE 0
    END AS possui_inconsistencia_irn_ou_pdf,
    CASE
        WHEN COUNT(*) = 1 THEN 'UNICO'
        WHEN COUNT(DISTINCT brim_grow_settlements_irn) <= 1 AND COUNT(DISTINCT pdf_bytes_sha256) <= 1
            THEN 'REENVIO_CONSISTENTE'
        WHEN COUNT(DISTINCT brim_grow_settlements_irn) > 1 AND COUNT(DISTINCT pdf_bytes_sha256) <= 1
            THEN 'INCONSISTENCIA_IRN_DIVERGENTE'
        WHEN COUNT(DISTINCT brim_grow_settlements_irn) > 1 AND COUNT(DISTINCT pdf_bytes_sha256) > 1
            THEN 'INCONSISTENCIA_IRN_E_PDF_DIVERGENTE'
        WHEN COUNT(DISTINCT pdf_texto_canonico_sha256) <= 1 AND COUNT(DISTINCT pdf_bytes_sha256) > 1
            THEN 'INCONSISTENCIA_PDF_NAO_DETERMINISTICO'
        ELSE 'INCONSISTENCIA_CONTEUDO_DIVERGENTE'
    END AS diagnostico_duplicidade,
    GROUP_CONCAT(arquivo_origem, ', ') AS arquivos
FROM base
GROUP BY aviario_lote
ORDER BY qtd_payloads DESC, aviario_lote;

DROP VIEW IF EXISTS vw_diagnostico_cod_cliente_bp;
CREATE TABLE IF NOT EXISTS ref_aviario_bp (
    aviario TEXT PRIMARY KEY,
    nome_proprietario_aviario TEXT,
    cod_bp_proprietario TEXT,
    nome_responsavel_granja TEXT,
    cod_bp_responsavel TEXT
);

CREATE VIEW vw_diagnostico_cod_cliente_bp AS
SELECT
    COALESCE(NULLIF(j.extrato_aviario, ''), d.aviario_codigo) AS aviario,
    p.cod_cliente AS cod_cliente_json,
    d.bp AS bp_pdf,
    d.matricula AS matricula_pdf,
    MAX(d.produtor) AS produtor_pdf,
    MAX(j.aviario) AS aviario_json,
    MAX(r.nome_proprietario_aviario) AS nome_proprietario_ref,
    MAX(r.cod_bp_proprietario) AS bp_proprietario_ref,
    MAX(r.nome_responsavel_granja) AS nome_responsavel_ref,
    MAX(r.cod_bp_responsavel) AS bp_responsavel_ref,
    COUNT(*) AS qtd_ocorrencias,
    GROUP_CONCAT(DISTINCT COALESCE(NULLIF(j.numero_extrato, ''), d.aviario_codigo || '-' || d.lote_pdf)) AS lotes_afetados,
    (
        SELECT GROUP_CONCAT(DISTINCT d2.produtor)
        FROM payloads p2
        JOIN acertos_pdf d2 ON d2.payload_id = p2.id
        WHERE p2.cod_cliente = d.bp AND COALESCE(d2.produtor, '') != COALESCE(d.produtor, '')
    ) AS titular_bp_na_base,
    CASE
        WHEN MAX(r.aviario) IS NOT NULL
             AND p.cod_cliente = MAX(r.cod_bp_proprietario)
             AND d.bp = MAX(r.cod_bp_responsavel)
            THEN 'JSON=PROPRIETARIO | PDF=RESPONSAVEL'
        WHEN MAX(r.aviario) IS NOT NULL
             AND p.cod_cliente = MAX(r.cod_bp_proprietario)
             AND d.bp != MAX(r.cod_bp_responsavel)
            THEN 'JSON=PROPRIETARIO | PDF=DIVERGENTE_REF'
        WHEN MAX(r.aviario) IS NOT NULL
             AND p.cod_cliente = MAX(r.cod_bp_responsavel)
             AND d.bp = MAX(r.cod_bp_proprietario)
            THEN 'JSON=RESPONSAVEL | PDF=PROPRIETARIO'
        WHEN EXISTS (
            SELECT 1 FROM payloads p2
            WHERE p2.cod_cliente = d.bp AND COALESCE(p2.cod_cliente, '') != COALESCE(p.cod_cliente, '')
        ) THEN 'BP_COMPARTILHADO_OUTRO_PRODUTOR'
        ELSE 'DIVERGENCIA_CADASTRAL_ISOLADA'
    END AS classificacao_causa
FROM payloads p
JOIN acertos_json j ON j.payload_id = p.id
JOIN acertos_pdf d ON d.payload_id = p.id
LEFT JOIN ref_aviario_bp r ON r.aviario = COALESCE(NULLIF(j.extrato_aviario, ''), d.aviario_codigo)
WHERE COALESCE(p.cod_cliente, '') != COALESCE(d.bp, '')
GROUP BY COALESCE(NULLIF(j.extrato_aviario, ''), d.aviario_codigo), p.cod_cliente, d.bp, d.matricula
ORDER BY qtd_ocorrencias DESC, produtor_pdf;
"""


def upsert_ref_aviario_bp(conn: sqlite3.Connection, records: list[object]) -> int:
    """Sincroniza a tabela de referência ref_aviario_bp com os registros extraídos."""
    cur = conn.cursor()
    cur.execute("DELETE FROM ref_aviario_bp")
    cur.executemany(
        """
        INSERT INTO ref_aviario_bp (
            aviario, nome_proprietario_aviario, cod_bp_proprietario,
            nome_responsavel_granja, cod_bp_responsavel
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                r.aviario,
                r.nome_proprietario_aviario,
                r.cod_bp_proprietario,
                r.nome_responsavel_granja,
                r.cod_bp_responsavel,
            )
            for r in records
        ],
    )
    conn.commit()
    return len(records)


def _ensure_current_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(payloads)").fetchall()}
    if cols and (
        "qtd_itens_data" not in cols
        or "pdf_texto_canonico_sha256" not in cols
        or "arquivo_pai" not in cols
    ):
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            DROP VIEW IF EXISTS vw_conferencia_completa;
            DROP VIEW IF EXISTS vw_divergencias;
            DROP VIEW IF EXISTS vw_duplicidades_lote;
            DROP TABLE IF EXISTS validacoes;
            DROP TABLE IF EXISTS acertos_pdf;
            DROP TABLE IF EXISTS acertos_json;
            DROP TABLE IF EXISTS payloads;
            PRAGMA foreign_keys = ON;
            """
        )


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _ensure_current_schema(conn)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def upsert_record(
    conn: sqlite3.Connection,
    payload: ParsedPayload,
    pdf_data: PdfExtractedData,
    validations: list[ValidationResult],
    pdf_saved_path: Path | None,
) -> int:
    now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    pdf_size = len(payload.pdf_bytes) if payload.pdf_bytes else 0
    pdf_valid_int = 1 if (payload.pdf_base64_valido and pdf_data.pdf_valido) else 0

    cur = conn.cursor()
    cur.execute("DELETE FROM payloads WHERE arquivo_origem = ?", (payload.arquivo_origem,))

    cur.execute(
        """
        INSERT INTO payloads (
            arquivo_origem, arquivo_pai, sha256_arquivo, schema_versao, qtd_itens_data, item_indice,
            cod_cliente, pdf_valido, pdf_tamanho_bytes, pdf_paginas,
            pdf_bytes_sha256, pdf_texto_canonico_sha256, pdf_caminho, processado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.arquivo_origem,
            payload.caminho_origem.name,
            payload.sha256_arquivo,
            payload.schema_versao,
            payload.qtd_itens_data,
            payload.item_indice,
            payload.cod_cliente,
            pdf_valid_int,
            pdf_size,
            pdf_data.pdf_paginas,
            pdf_data.pdf_bytes_sha256,
            pdf_data.pdf_texto_canonico_sha256,
            str(pdf_saved_path) if pdf_saved_path else None,
            now_iso,
        ),
    )
    payload_id = cur.lastrowid

    dd = payload.demais_dados
    cur.execute(
        """
        INSERT INTO acertos_json (
            payload_id, demais_dados_valido, cod_empresa, lote, data_emissao,
            aviario, numero_extrato, extrato_aviario, extrato_lote,
            brim_grow_settlements_irn, raw_demais_dados
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload_id,
            1 if payload.demais_dados_valido else 0,
            dd.Cod_Empresa if dd else None,
            dd.Lote if dd else None,
            dd.DataEmissao if dd else None,
            dd.Aviario if dd else None,
            dd.Numero_Extrato if dd else None,
            payload.extrato_aviario,
            payload.extrato_lote,
            dd.BrimGrowSettlementsIRN if dd else None,
            payload.raw_demais_dados,
        ),
    )

    cur.execute(
        """
        INSERT INTO acertos_pdf (
            payload_id, produtor, matricula, bp, bps_encontrados, municipio, uf, data_pdf,
            tecnico, aviario_codigo, lote_pdf, numero_extrato_pdf,
            quitacao_aviario, quitacao_lote,
            aves_alojadas, aves_abatidas, mortalidade_pct, viabilidade_pct,
            conversao_alimentar, peso_lote, peso_medio, iep,
            valor_base, valor_lote, valor_liquido, valor_por_m2
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload_id,
            pdf_data.produtor,
            pdf_data.matricula,
            pdf_data.bp,
            ", ".join(pdf_data.bps_encontrados) if pdf_data.bps_encontrados else None,
            pdf_data.municipio,
            pdf_data.uf,
            pdf_data.data_pdf,
            pdf_data.tecnico,
            pdf_data.aviario_codigo,
            pdf_data.lote_pdf,
            pdf_data.numero_extrato_pdf,
            pdf_data.quitacao_aviario,
            pdf_data.quitacao_lote,
            pdf_data.aves_alojadas,
            pdf_data.aves_abatidas,
            pdf_data.mortalidade_pct,
            pdf_data.viabilidade_pct,
            pdf_data.conversao_alimentar,
            pdf_data.peso_lote,
            pdf_data.peso_medio,
            pdf_data.iep,
            pdf_data.valor_base,
            pdf_data.valor_lote,
            pdf_data.valor_liquido,
            pdf_data.valor_por_m2,
        ),
    )

    cur.executemany(
        """
        INSERT INTO validacoes (
            payload_id, regra, status, severidade, valor_json, valor_pdf, detalhe
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (payload_id, v.regra, v.status, v.severidade, v.valor_json, v.valor_pdf, v.detalhe)
            for v in validations
        ],
    )

    conn.commit()
    return payload_id
