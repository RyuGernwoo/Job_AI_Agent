from lectureops_agent.models.schemas import MaterialChunk


def chunk_text(
    *,
    project_id: str,
    document_id: str,
    source_name: str,
    source_type: str,
    text: str,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    metadata: dict[str, object] | None = None,
    page: int | None = None,
) -> list[MaterialChunk]:
    if not text.strip():
        raise ValueError("text must not be empty")
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be greater than 0")
    if chunk_overlap_chars < 0:
        raise ValueError("chunk_overlap_chars must be greater than or equal to 0")
    if chunk_overlap_chars >= chunk_size_chars:
        raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")

    chunks: list[MaterialChunk] = []
    start = 0
    chunk_index = 1
    page_number = page or 0
    chunk_metadata = dict(metadata or {})

    while start < len(text):
        end = min(start + chunk_size_chars, len(text))
        chunk_body = text[start:end]
        chunks.append(
            MaterialChunk(
                chunk_id=f"{document_id}-p{page_number:03d}-c{chunk_index:03d}",
                project_id=project_id,
                document_id=document_id,
                source_name=source_name,
                source_type=source_type,
                page=page,
                text=chunk_body,
                metadata=chunk_metadata,
            )
        )

        if end == len(text):
            break

        start = end - chunk_overlap_chars
        chunk_index += 1

    return chunks
