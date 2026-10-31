"""
Đọc nội dung chữ từ file đặc tả người dùng upload (.txt, .md, .pdf, .docx).
"""
import io
from pathlib import Path
from typing import Tuple

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def _decode_text(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(data: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(data))
    parts = [paragraph.text for paragraph in document.paragraphs]
    # Bảng trong Word hay chứa yêu cầu chức năng, nên đọc luôn.
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def extract_text(filename: str, data: bytes) -> Tuple[str | None, str | None]:
    """Trả về (text, None) hoặc (None, thông báo lỗi)."""
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return None, f"Unsupported file type '{extension or '?'}'. Use .txt, .md, .pdf, or .docx."

    try:
        if extension == ".pdf":
            text = _read_pdf(data)
        elif extension == ".docx":
            text = _read_docx(data)
        else:
            text = _decode_text(data)
    except Exception as exc:
        return None, f"Could not read {filename}: {exc}"

    # Gộp các dòng trống liên tiếp cho gọn.
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    cleaned = cleaned.strip()

    if not cleaned:
        return None, f"No text found in {filename}. Scanned PDFs (images) are not supported."
    return cleaned, None
