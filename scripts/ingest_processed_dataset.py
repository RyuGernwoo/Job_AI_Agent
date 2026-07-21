"""Ingest processed LessonPack AI chunks into the configured VectorStore."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.dataset_loader import DEFAULT_DATASET_PROJECT_ID, load_processed_chunks
from lectureops_agent.services.vector_store import create_vector_store_from_env, resolve_embedding_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest processed LessonPack AI chunks into VectorStore.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Path to the data directory.")
    parser.add_argument("--project-id", default=DEFAULT_DATASET_PROJECT_ID, help="Project id used for VectorStore upsert.")
    parser.add_argument("--query", help="Optional smoke query after ingestion.")
    parser.add_argument("--top-k", type=int, default=3, help="Number of chunks returned for the smoke query.")
    args = parser.parse_args(argv)

    chunks = load_processed_chunks(args.data_dir, project_id=args.project_id)
    vector_store = create_vector_store_from_env()
    vector_store.upsert(project_id=args.project_id, chunks=chunks)

    embedding_column = os.getenv("LESSONPACK_SUPABASE_EMBEDDING_COLUMN", "embedding")
    result: dict[str, Any] = {
        "project_id": args.project_id,
        "chunk_count": len(chunks),
        "vector_store": os.getenv("LECTUREOPS_VECTOR_STORE", "memory"),
        "embedding": {
            "provider": os.getenv("LESSONPACK_EMBEDDING_PROVIDER", "hash"),
            "model": os.getenv("LESSONPACK_EMBEDDING_MODEL", "lessonpack-hash-v1"),
            "dimensions": int(os.getenv("LESSONPACK_EMBEDDING_DIMENSIONS", "64")),
            "column": embedding_column,
            "version": resolve_embedding_version(
                embedding_column=embedding_column,
                configured_version=os.getenv("LESSONPACK_EMBEDDING_VERSION"),
            ),
        },
    }
    if args.query:
        retrieved = vector_store.query(project_id=args.project_id, query=args.query, top_k=args.top_k)
        result["sample_query"] = args.query
        result["sample_results"] = [
            {
                "chunk_id": chunk.chunk_id,
                "source_name": chunk.source_name,
                "section": chunk.metadata.get("section"),
            }
            for chunk in retrieved
        ]

    close = getattr(vector_store, "close", None)
    if close is not None:
        close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
