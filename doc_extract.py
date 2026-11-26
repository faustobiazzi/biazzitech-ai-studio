#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extrai texto de anexos para usar como referência: .txt, .md, .docx e .pdf.

- .txt / .md / .docx: só biblioteca padrão do Python.
- .pdf: usa a biblioteca "pypdf" se estiver instalada (pip install pypdf);
  sem ela, tenta um extrator simples que funciona só em PDFs básicos.
"""

import io
import re
import zlib
import zipfile
import xml.etree.ElementTree as ET

MAX_CHARS = 60_000  # por anexo (cerca de 15 mil tokens)

TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".json", ".gd", ".py", ".tscn", ".tres", ".html", ".xml", ".yml", ".yaml")


class ExtractError(Exception):
    pass


def _decode_text(data):
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            txt = data.decode(enc)
            if enc == "utf-16" and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return txt
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _docx(data):
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except Exception:
        raise ExtractError("Não parece um .docx válido.")
    root = ET.fromstring(xml)
    out = []
    for p in root.iter(W + "p"):
        parts = []
        for node in p.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                parts.append("\n")
        out.append("".join(parts))
    return "\n".join(out)


def _pdf_basic(data):
    """Extrator simples (sem pypdf): só PDFs com texto em strings literais e fontes simples."""
    chunks = []
    for m in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", data, re.S):
        head, raw = m.group(1), m.group(2)
        if b"/FlateDecode" in head:
            try:
                raw = zlib.decompress(raw)
            except Exception:
                continue
        elif b"/Filter" in head:
            continue
        if b"BT" not in raw:
            continue
        for bt in re.findall(rb"BT(.*?)ET", raw, re.S):
            line = []
            for tok in re.finditer(rb"\((?:\\.|[^\\)])*\)|T\*|Td|TD|'|\"", bt):
                t = tok.group(0)
                if t.startswith(b"("):
                    s = t[1:-1]
                    s = re.sub(rb"\\([nrtbf()\\])", lambda x: {b"n": b"\n", b"r": b"", b"t": b"\t", b"b": b"",
                                                              b"f": b""}.get(x.group(1), x.group(1)), s)
                    s = re.sub(rb"\\([0-7]{1,3})", lambda x: bytes([int(x.group(1), 8) & 255]), s)
                    line.append(s.decode("latin-1"))
                else:
                    line.append("\n")
            chunks.append("".join(line))
    return "\n".join(chunks)


def _pdf(data):
    try:
        import pypdf  # opcional
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ExtractError("PDF protegido por senha.")
        pages = []
        for i, page in enumerate(reader.pages, 1):
            pages.append(f"[página {i}]\n" + (page.extract_text() or ""))
        return "\n\n".join(pages)
    except ImportError:
        text = _pdf_basic(data)
        letters = sum(c.isalpha() for c in text)
        if letters < 40:
            raise ExtractError("Não consegui ler o texto deste PDF sem a biblioteca pypdf. "
                               "Instale com: pip install pypdf (ou use .docx/.md/.txt).")
        return text


def extract(name, data):
    """Retorna (texto, aviso_ou_None)."""
    low = (name or "").lower()
    if low.endswith(".docx"):
        text = _docx(data)
    elif low.endswith(".pdf") or data[:5] == b"%PDF-":
        text = _pdf(data)
    elif low.endswith(TEXT_EXT) or not low.rpartition(".")[1]:
        text = _decode_text(data)
    elif low.endswith(".doc"):
        raise ExtractError("Formato .doc antigo não é suportado: salve como .docx.")
    else:
        raise ExtractError("Formato não suportado. Use .docx, .md, .txt ou .pdf.")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ExtractError("O arquivo não tem texto extraível.")
    warn = None
    if len(text) > MAX_CHARS:
        warn = f"Texto grande: usei os primeiros {MAX_CHARS:,} caracteres de {len(text):,}.".replace(",", ".")
        text = text[:MAX_CHARS]
    return text, warn


def pdf_support():
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        return "basico"
