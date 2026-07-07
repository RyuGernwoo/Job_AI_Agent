from pathlib import Path

import fitz

SUPPORTED_TEXT_TYPES = {"txt", "md"}
SUPPORTED_FILE_TYPES = SUPPORTED_TEXT_TYPES | {"pdf"}


def get_source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FILE_TYPES:
        raise ValueError(f"unsupported file type: {suffix or 'none'}")
    return suffix


def _decode_plain_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("file encoding must be utf-8 or cp949")


def _extract_pdf_text(content: bytes) -> str:
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several parser-specific exceptions.
        raise ValueError("invalid pdf file") from exc

    try:
        pages = [page.get_text("text", sort=True) for page in document]
    finally:
        document.close()

    return "\n\n".join(page_text.strip() for page_text in pages if page_text.strip())


def decode_text_material(filename: str, content: bytes) -> tuple[str, str]:
    source_type = get_source_type(filename)
    if source_type == "pdf":
        text = _extract_pdf_text(content)
    else:
        text = _decode_plain_text(content)

    if not text.strip():
        raise ValueError("uploaded material must not be empty")

    return text, source_type
