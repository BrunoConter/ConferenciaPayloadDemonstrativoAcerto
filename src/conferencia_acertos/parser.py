from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


EXPECTED_SCHEMA = "br.com.cvale.sap.extratoaves.v1"
SUPPORTED_SCHEMAS = {EXPECTED_SCHEMA}


class DemaisDadosModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    Cod_Empresa: int
    Lote: str
    DataEmissao: str
    Aviario: str
    Numero_Extrato: str
    BrimGrowSettlementsIRN: str

    @field_validator("BrimGrowSettlementsIRN")
    @classmethod
    def _irn_nao_vazio(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("BrimGrowSettlementsIRN não pode ser vazio")
        return cleaned


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
    m = re.match(r"^\s*([A-Za-z0-9]+)\s*-\s*(\S+)\s*$", numero_extrato)
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


def _error_payload(
    *,
    arquivo_origem: str,
    caminho_origem: Path,
    sha256: str,
    json_erro: str,
    schema_versao: str | None = None,
    qtd_itens_data: int = 0,
    item_indice: int = 0,
    detail_erro: str = "JSON raiz inválido",
) -> ParsedPayload:
    return ParsedPayload(
        arquivo_origem=arquivo_origem,
        caminho_origem=caminho_origem,
        sha256_arquivo=sha256,
        json_valido=False,
        json_erro=json_erro,
        schema_versao=schema_versao,
        qtd_itens_data=qtd_itens_data,
        item_indice=item_indice,
        cod_cliente=None,
        demais_dados_valido=False,
        demais_dados_erro=detail_erro,
        demais_dados=None,
        raw_demais_dados="",
        extrato_aviario=None,
        extrato_lote=None,
        pdf_bytes=None,
        pdf_base64_valido=False,
        pdf_base64_erro=detail_erro,
    )


def _read_text_with_fallback(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def parse_payload_file(path: Path, root_dir: Path | None = None) -> list[ParsedPayload]:
    """Lê um arquivo de payload JSON e retorna uma lista de ParsedPayload (1 por item em Data)."""
    sha256 = _compute_sha256(path)
    if root_dir is not None and path.parent != root_dir:
        try:
            display_name = path.relative_to(root_dir).as_posix()
        except ValueError:
            display_name = path.name
    else:
        display_name = path.name

    try:
        content = _read_text_with_fallback(path)
        envelope = json.loads(content)
    except Exception as exc:
        return [
            _error_payload(
                arquivo_origem=display_name,
                caminho_origem=path,
                sha256=sha256,
                json_erro=f"Falha ao ler JSON raiz: {exc}",
            )
        ]

    if not isinstance(envelope, dict):
        return [
            _error_payload(
                arquivo_origem=display_name,
                caminho_origem=path,
                sha256=sha256,
                json_erro="JSON raiz não é um objeto dict",
            )
        ]

    schema_versao = envelope.get("Schema")
    data_list = envelope.get("Data")
    if not isinstance(data_list, list) or not data_list:
        return [
            _error_payload(
                arquivo_origem=display_name,
                caminho_origem=path,
                sha256=sha256,
                json_erro="Campo 'Data' ausente, não é lista ou está vazio",
                schema_versao=schema_versao,
                qtd_itens_data=0 if not isinstance(data_list, list) else len(data_list),
                detail_erro="Campo 'Data' vazio",
            )
        ]

    qtd_itens = len(data_list)
    results: list[ParsedPayload] = []
    for idx, item in enumerate(data_list):
        nome_registro = display_name if qtd_itens == 1 else f"{display_name}[{idx}]"
        if not isinstance(item, dict):
            results.append(
                _error_payload(
                    arquivo_origem=nome_registro,
                    caminho_origem=path,
                    sha256=sha256,
                    json_erro=f"Item Data[{idx}] não é um objeto",
                    schema_versao=schema_versao,
                    qtd_itens_data=qtd_itens,
                    item_indice=idx + 1,
                    detail_erro="Item inválido",
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
