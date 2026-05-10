from __future__ import annotations
from pathlib import Path
from typing import BinaryIO
import tempfile


def extract_text_from_file(uploaded_file) -> str:
    name = getattr(uploaded_file, "name", "") or ""
    suffix = Path(name).suffix.lower()
    data = uploaded_file.read()
    if suffix in [".txt", ".md"]:
        return data.decode("utf-8", errors="ignore")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix in [".docx", ".doc"]:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        return data.decode("utf-8", errors="ignore")
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
