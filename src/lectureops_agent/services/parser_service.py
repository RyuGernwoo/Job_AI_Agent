from pathlib import Path

SUPPORTED_TEXT_TYPES = {"txt", "md"}


def get_source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_TEXT_TYPES:
        raise ValueError(f"unsupported file type: {suffix or 'none'}")
    return suffix


def decode_text_material(filename: str, content: bytes) -> tuple[str, str]:
    source_type = get_source_type(filename)
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("file encoding must be utf-8 or cp949")

    if not text.strip():
        raise ValueError("uploaded material must not be empty")

    return text, source_type
