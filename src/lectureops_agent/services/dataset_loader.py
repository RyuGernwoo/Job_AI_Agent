from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from lectureops_agent.models.schemas import MaterialChunk


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_DATASET_PROJECT_ID = "mvp-dataset"


def load_processed_chunks(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
) -> list[MaterialChunk]:
    chunks_path = Path(data_dir) / "processed" / "chunks.jsonl"
    return load_chunks_file(chunks_path, project_id=project_id)


def load_chunks_file(
    chunks_path: Path | str,
    *,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
) -> list[MaterialChunk]:
    return list(iter_chunks_file(chunks_path, project_id=project_id))


def iter_chunks_file(
    chunks_path: Path | str,
    *,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
) -> Iterator[MaterialChunk]:
    for row in _read_jsonl(Path(chunks_path)):
        yield _row_to_material_chunk(row, project_id=project_id)


def _row_to_material_chunk(row: dict[str, Any], *, project_id: str) -> MaterialChunk:
    source_id = str(row["source_id"])
    source_file = str(row.get("source_file", ""))
    metadata_value = row.get("metadata") or {}
    if not isinstance(metadata_value, dict):
        raise ValueError("chunk metadata must be a JSON object")
    metadata = dict(metadata_value)
    excluded = {
        "chunk_id",
        "project_id",
        "document_id",
        "source_name",
        "source_type",
        "page",
        "text",
        "metadata",
    }
    for key, value in row.items():
        if key not in excluded:
            metadata.setdefault(key, value)
    metadata.setdefault("source_id", source_id)
    metadata.setdefault("source_file", source_file)
    return MaterialChunk(
        chunk_id=str(row["chunk_id"]),
        project_id=project_id,
        document_id=str(row.get("document_id") or source_id),
        source_name=str(row["source_name"]),
        source_type=str(row.get("source_type") or _infer_source_type(source_file)),
        page=_optional_page(row.get("page")),
        text=str(row["text"]),
        metadata=metadata,
    )


def _infer_source_type(source_file: str) -> str:
    suffix = Path(source_file).suffix.casefold()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".md":
        return "md"
    return "txt"


def _optional_page(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing processed chunks file: {path}")
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name} line {line_number} must be a JSON object")
            yield value
