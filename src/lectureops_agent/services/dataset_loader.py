from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lectureops_agent.models.schemas import MaterialChunk


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_DATASET_PROJECT_ID = "mvp-dataset"


def load_processed_chunks(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
) -> list[MaterialChunk]:
    chunks_path = Path(data_dir) / "processed" / "chunks.jsonl"
    rows = _read_jsonl(chunks_path)
    return [_row_to_material_chunk(row, project_id=project_id) for row in rows]


def _row_to_material_chunk(row: dict[str, Any], *, project_id: str) -> MaterialChunk:
    source_id = str(row["source_id"])
    source_file = str(row.get("source_file", ""))
    metadata = {
        "source_id": source_id,
        "source_url": row.get("source_url", ""),
        "license": row.get("license", ""),
        "section": row.get("section", ""),
        "source_file": source_file,
        "tags": row.get("tags", []),
        "char_count": row.get("char_count"),
        "token_estimate": row.get("token_estimate"),
        "review_status": row.get("review_status", ""),
    }
    return MaterialChunk(
        chunk_id=str(row["chunk_id"]),
        project_id=project_id,
        document_id=source_id,
        source_name=str(row["source_name"]),
        source_type=_infer_source_type(source_file),
        page=None,
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing processed chunks file: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name} line {line_number} must be a JSON object")
            rows.append(value)
    return rows
