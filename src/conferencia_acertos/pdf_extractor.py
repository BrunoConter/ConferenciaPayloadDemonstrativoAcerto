from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field

import pdfplumber
from pypdf import PdfReader


@dataclass
class PdfExtractedData:
    pdf_valido: bool
    pdf_erro: str | None
    pdf_paginas: int
    texto_completo: str
    pdf_bytes_sha256: str | None = None
    pdf_texto_sha256: str | None = None
    pdf_texto_canonico_sha256: str | None = None
    produtor: str | None = None
    matricula: str | None = None
    bp: str | None = None
    bps_encontrados: list[str] = field(default_factory=list)
    municipio: str | None = None
    uf: str | None = None
    data_pdf: str | None = None
    tecnico: str | None = None
    aviario_codigo: str | None = None
    lote_pdf: str | None = None
    numero_extrato_pdf: str | None = None
    aviario_lote_composto_pdf: str | None = None
    quitacao_aviario: str | None = None
    quitacao_lote: str | None = None
    aves_alojadas: int | None = None
    aves_abatidas: int | None = None
    mortalidade_pct: float | None = None
    viabilidade_pct: float | None = None
    conversao_alimentar: float | None = None
    peso_lote: float | None = None
    peso_medio: float | None = None
    iep: float | None = None
    valor_base: float | None = None
    valor_lote: float | None = None
    valor_liquido: float | None = None
    valor_por_m2: float | None = None
    tem_valor_extenso_en: bool = False


def _parse_int(val: str | None) -> int | None:
    if not val:
        return None
    cleaned = val.replace(",", "").replace(".", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    cleaned = val.replace("R$", "").replace("%", "").strip()
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # Padrão PT-BR: 73.500,00
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Padrão EN-US: 73,500.00
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        after_comma = cleaned.split(",")[-1]
        if len(after_comma) <= 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _search(pattern: str, text: str, flags: int = 0) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def compute_canonical_text_hash(text: str) -> str:
    """Gera hash SHA-256 das linhas normalizadas e ordenadas para ignorar reordenação de tabelas."""
    lines = sorted(re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip())
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def extract_pdf_data(pdf_bytes: bytes | None) -> PdfExtractedData:
    """Valida a integridade do PDF e extrai campos estruturados do demonstrativo."""
    if not pdf_bytes:
        return PdfExtractedData(
            pdf_valido=False,
            pdf_erro="Bytes do PDF vazios ou ausentes",
            pdf_paginas=0,
            texto_completo="",
        )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
        num_pages = len(reader.pages)
        if num_pages == 0:
            return PdfExtractedData(
                pdf_valido=False,
                pdf_erro="PDF possui 0 páginas",
                pdf_paginas=0,
                texto_completo="",
            )
    except Exception as exc:
        return PdfExtractedData(
            pdf_valido=False,
            pdf_erro=f"PDF corrompido ou ilegível (pypdf): {exc}",
            pdf_paginas=0,
            texto_completo="",
        )

    pages_text: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text(layout=True) or ""
                pages_text.append(txt)
    except Exception as exc:
        return PdfExtractedData(
            pdf_valido=False,
            pdf_erro=f"Falha ao extrair texto do PDF (pdfplumber): {exc}",
            pdf_paginas=num_pages,
            texto_completo="",
        )

    full_text = "\n\f\n".join(pages_text)
    if not full_text.strip():
        return PdfExtractedData(
            pdf_valido=False,
            pdf_erro="PDF válido estruturalmente, porém sem texto extraível",
            pdf_paginas=num_pages,
            texto_completo="",
        )

    produtor = _search(r"PRODUTOR\s*[-:]\s*(.+?)\s+MATR[ÍI]CULA\s*[-:]", full_text)
    matricula = _search(r"MATR[ÍI]CULA\s*[-:]\s*(\S+)", full_text)
    bps_encontrados = [b.strip() for b in re.findall(r"BP\s*[-:]\s*(\S+)", full_text) if b.strip()]
    bp = bps_encontrados[0] if bps_encontrados else None
    municipio = _search(r"MUNIC[ÍI]PIO\s*[-:]\s*(.+?)\s+UF\s*[-:]", full_text)
    uf = _search(r"UF\s*[-:]\s*([A-Z]{2})\b", full_text)
    data_pdf = _search(r"DATA\s*[-:]\s*(\d{2}/\d{2}/\d{4})", full_text)
    tecnico = _search(r"T[ÉE]CNICO\s*[-:]\s*(.+?)\s+AVI[ÁA]RIO\s*[-:]", full_text)
    aviario_codigo = _search(r"AVI[ÁA]RIO\s*[-:]\s*([A-Za-z0-9]+)", full_text)
    lote_pdf = _search(r"LOTE\s*[-:]\s*(\S+)", full_text)

    aviario_lote_composto_pdf = (
        f"{aviario_codigo}-{lote_pdf}" if aviario_codigo and lote_pdf else None
    )

    numero_extrato_pdf = None
    if aviario_lote_composto_pdf and aviario_lote_composto_pdf in full_text:
        numero_extrato_pdf = aviario_lote_composto_pdf
    if not numero_extrato_pdf:
        numero_extrato_pdf = _search(r"\n\s*([A-Za-z0-9]{2,}-\S+)\s+PAR[ÂA]METROS", full_text)

    quitacao_match = re.search(
        r"lote[,\s]+(\S+?)[,\s]+do\s+avi[áa]rio\s+([A-Za-z0-9]+)",
        full_text,
        flags=re.IGNORECASE,
    )
    quitacao_lote = quitacao_match.group(1).strip() if quitacao_match else None
    quitacao_aviario = quitacao_match.group(2).strip() if quitacao_match else None

    aves_alojadas = _parse_int(_search(r"Aves Alojadas\s+([\d.,]+)", full_text))
    aves_abatidas = _parse_int(_search(r"Aves Abatidas\s+([\d.,]+)", full_text))
    mortalidade_pct = _parse_float(_search(r"Mortalidade\s+([\d.,]+)%", full_text))
    viabilidade_pct = _parse_float(_search(r"Viabilidade\s+([\d.,]+)%", full_text))
    conversao_alimentar = _parse_float(_search(r"Convers[ãa]o Alimentar Realizada\s+([\d.,]+)", full_text))
    peso_lote = _parse_float(_search(r"Peso Lote\s+([\d.,]+)", full_text))
    peso_medio = _parse_float(_search(r"Peso M[ée]dio\s+([\d.,]+)", full_text))
    iep = _parse_float(_search(r"\bIEP\s+([\d.,]+)", full_text))

    valor_base = _parse_float(_search(r"1\.\s*Valor base\s+R\$\s*([\d.,]+)", full_text))
    valor_lote = _parse_float(_search(r"VALOR DO LOTE\s+R\$\s*([\d.,]+)", full_text))
    valor_liquido = _parse_float(_search(r"VALOR L[ÍI]QUIDO\s+R\$\s*([\d.,]+)", full_text))
    valor_por_m2 = _parse_float(_search(r"VALOR POR M[²2]\s+R\$\s*([\d.,]+)", full_text))

    tem_valor_extenso_en = bool(
        re.search(
            r"\((?:[A-Za-z-]+\s+)*(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|"
            r"Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|Eighteen|Nineteen|"
            r"Twenty|Thirty|Forty|Fifty|Sixty|Seventy|Eighty|Ninety|Hundred|Thousand|Million|Dollars|Reais|Cents)\b",
            full_text,
        )
    )

    pdf_bytes_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_texto_sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    pdf_texto_canonico_sha256 = compute_canonical_text_hash(full_text)

    return PdfExtractedData(
        pdf_valido=True,
        pdf_erro=None,
        pdf_paginas=num_pages,
        texto_completo=full_text,
        pdf_bytes_sha256=pdf_bytes_sha256,
        pdf_texto_sha256=pdf_texto_sha256,
        pdf_texto_canonico_sha256=pdf_texto_canonico_sha256,
        produtor=produtor,
        matricula=matricula,
        bp=bp,
        bps_encontrados=bps_encontrados,
        municipio=municipio,
        uf=uf,
        data_pdf=data_pdf,
        tecnico=tecnico,
        aviario_codigo=aviario_codigo,
        lote_pdf=lote_pdf,
        numero_extrato_pdf=numero_extrato_pdf,
        aviario_lote_composto_pdf=aviario_lote_composto_pdf,
        quitacao_aviario=quitacao_aviario,
        quitacao_lote=quitacao_lote,
        aves_alojadas=aves_alojadas,
        aves_abatidas=aves_abatidas,
        mortalidade_pct=mortalidade_pct,
        viabilidade_pct=viabilidade_pct,
        conversao_alimentar=conversao_alimentar,
        peso_lote=peso_lote,
        peso_medio=peso_medio,
        iep=iep,
        valor_base=valor_base,
        valor_lote=valor_lote,
        valor_liquido=valor_liquido,
        valor_por_m2=valor_por_m2,
        tem_valor_extenso_en=tem_valor_extenso_en,
    )
