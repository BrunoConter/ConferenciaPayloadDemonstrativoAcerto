from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


EXPECTED_SCHEMA = "br.com.cvale.sap.extratoaves.v1"


class DemaisDadosModel(BaseModel):
    Cod_Empresa: int
    Lote: str
    DataEmissao: str
    Aviario: str
    Numero_Extrato: str
    BrimGrowSettlementsIRN: str


@dataclass
class ParsedPayload:
    arquivo_origem: str
    caminho_origem: Path
    sha256_arquivo: str
    json_valido: bool
    json_erro: str | None
    schema_versao: str | None
    qtd_itens_data: int
    item_indice: int
    cod_cliente: str | None
    demais_dados_valido: bool
    demais_dados_erro: str | None
    demais_dados: DemaisDadosModel | None
    raw_demais_dados: str
    extrato_aviario: str | None
    extrato_lote: str | None
    pdf_bytes: bytes | None
    pdf_base64_valido: bool
    pdf_base64_erro: str | None
    pdf64_len: int = 0


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _split_numero_extrato(numero_extrato: str | None) -> tuple[str | None, str | None]:
    if not numero_extrato:
        return None, None
    m = re.match(r"^\s*(\d+)\s*-\s*(\S+)\s*$", numero_extrato)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def _parse_demais_dados(raw_value: Any) -> tuple[bool, str | None, DemaisDadosModel | None, str]:
    if raw_value is None:
        return False, "Campo Demais_Dados ausente (None)", None, ""

    if isinstance(raw_value, dict):
        raw_str = json.dumps(raw_value, ensure_ascii=False)
        obj = raw_value
    elif isinstance(raw_value, str):
        raw_str = raw_value
        if not raw_str.strip():
            return False, "Campo Demais_Dados vazio ('')", None, raw_str
        try:
            obj = json.loads(raw_str)
        except json.JSONDecodeError as exc:
            return False, f"JSON inválido em Demais_Dados: {exc}", None, raw_str
    else:
        return False, f"Tipo inesperado em Demais_Dados: {type(raw_value).__name__}", None, str(raw_value)

    try:
        model = DemaisDadosModel.model_validate(obj)
        return True, None, model, raw_str
    except ValidationError as exc:
        return False, f"Contrato Demais_Dados inválido: {exc}", None, raw_str


def _decode_pdf64(pdf64: Any) -> tuple[bool, str | None, bytes | None, int]:
    if not pdf64 or not isinstance(pdf64, str) or not pdf64.strip():
        return False, "Campo PDF64 ausente ou vazio", None, 0
    pdf64_len = len(pdf64)
    try:
        raw_bytes = base64.b64decode(pdf64, validate=True)
    except Exception as exc:
        return False, f"Erro ao decodificar Base64 de PDF64: {exc}", None, pdf64_len

    if not raw_bytes.startswith(b"%PDF"):
        return False, "Conteúdo decodificado de PDF64 não inicia com assinatura %PDF", raw_bytes, pdf64_len

    return True, None, raw_bytes, pdf64_len


def parse_payload_file(path: Path) -> list[ParsedPayload]:
    """Lê um arquivo de payload JSON e retorna uma lista de ParsedPayload (1 por item em Data)."""
    sha256 = _compute_sha256(path)
    try:
        content = path.read_text(encoding="utf-8")
        envelope = json.loads(content)
    except Exception as exc:
        return [
            ParsedPayload(
                arquivo_origem=path.name,
                caminho_origem=path,
                sha256_arquivo=sha256,
                json_valido=False,
                json_erro=f"Falha ao ler JSON raiz: {exc}",
                schema_versao=None,
                qtd_itens_data=0,
                item_indice=0,
                cod_cliente=None,
                demais_dados_valido=False,
                demais_dados_erro="JSON raiz inválido",
                demais_dados=None,
                raw_demais_dados="",
                extrato_aviario=None,
                extrato_lote=None,
                pdf_bytes=None,
                pdf_base64_valido=False,
                pdf_base64_erro="JSON raiz inválido",
            )
        ]

    if not isinstance(envelope, dict):
        return [
            ParsedPayload(
                arquivo_origem=path.name,
                caminho_origem=path,
                sha256_arquivo=sha256,
                json_valido=False,
                json_erro="JSON raiz não é um objeto dict",
                schema_versao=None,
                qtd_itens_data=0,
                item_indice=0,
                cod_cliente=None,
                demais_dados_valido=False,
                demais_dados_erro="JSON raiz inválido",
                demais_dados=None,
                raw_demais_dados="",
                extrato_aviario=None,
                extrato_lote=None,
                pdf_bytes=None,
                pdf_base64_valido=False,
                pdf_base64_erro="JSON raiz inválido",
            )
        ]

    schema_versao = envelope.get("Schema")
    data_list = envelope.get("Data")
    if not isinstance(data_list, list) or not data_list:
        return [
            ParsedPayload(
                arquivo_origem=path.name,
                caminho_origem=path,
                sha256_arquivo=sha256,
                json_valido=False,
                json_erro="Campo 'Data' ausente, não é lista ou está vazio",
                schema_versao=schema_versao,
                qtd_itens_data=0 if not isinstance(data_list, list) else len(data_list),
                item_indice=0,
                cod_cliente=None,
                demais_dados_valido=False,
                demais_dados_erro="Campo 'Data' vazio",
                demais_dados=None,
                raw_demais_dados="",
                extrato_aviario=None,
                extrato_lote=None,
                pdf_bytes=None,
                pdf_base64_valido=False,
                pdf_base64_erro="Campo 'Data' vazio",
            )
        ]

    qtd_itens = len(data_list)
    results: list[ParsedPayload] = []
    for idx, item in enumerate(data_list):
        nome_registro = path.name if qtd_itens == 1 else f"{path.name}[{idx}]"
        if not isinstance(item, dict):
            results.append(
                ParsedPayload(
                    arquivo_origem=nome_registro,
                    caminho_origem=path,
                    sha256_arquivo=sha256,
                    json_valido=False,
                    json_erro=f"Item Data[{idx}] não é um objeto",
                    schema_versao=schema_versao,
                    qtd_itens_data=qtd_itens,
                    item_indice=idx + 1,
                    cod_cliente=None,
                    demais_dados_valido=False,
                    demais_dados_erro="Item inválido",
                    demais_dados=None,
                    raw_demais_dados="",
                    extrato_aviario=None,
                    extrato_lote=None,
                    pdf_bytes=None,
                    pdf_base64_valido=False,
                    pdf_base64_erro="Item inválido",
                )
            )
            continue

        cod_cliente = item.get("Cod_Cliente")
        dd_ok, dd_err, dd_model, raw_dd = _parse_demais_dados(item.get("Demais_Dados"))
        ext_av, ext_lote = _split_numero_extrato(dd_model.Numero_Extrato if dd_model else None)
        pdf_ok, pdf_err, pdf_bytes, pdf64_len = _decode_pdf64(item.get("PDF64"))

        results.append(
            ParsedPayload(
                arquivo_origem=nome_registro,
                caminho_origem=path,
                sha256_arquivo=sha256,
                json_valido=True,
                json_erro=None,
                schema_versao=schema_versao,
                qtd_itens_data=qtd_itens,
                item_indice=idx + 1,
                cod_cliente=str(cod_cliente).strip() if cod_cliente is not None else None,
                demais_dados_valido=dd_ok,
                demais_dados_erro=dd_err,
                demais_dados=dd_model,
                raw_demais_dados=raw_dd,
                extrato_aviario=ext_av,
                extrato_lote=ext_lote,
                pdf_bytes=pdf_bytes,
                pdf_base64_valido=pdf_ok,
                pdf_base64_erro=pdf_err,
                pdf64_len=pdf64_len,
            )
        )

    return results
