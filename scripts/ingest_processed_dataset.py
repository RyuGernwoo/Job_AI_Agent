"""Ingest processed LessonPack AI chunks into the configured VectorStore."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.dataset_loader import (
    DEFAULT_DATASET_PROJECT_ID,
    iter_chunks_file,
)
from lectureops_agent.services.vector_store import create_vector_store_from_env, resolve_embedding_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest processed LessonPack AI chunks into VectorStore.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Path to the data directory.")
    parser.add_argument(
        "--chunks-file",
        type=Path,
        help="JSONL chunks file. Defaults to <data-dir>/processed/chunks.jsonl.",
    )
    parser.add_argument("--project-id", default=DEFAULT_DATASET_PROJECT_ID, help="Project id used for VectorStore upsert.")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding and upsert batch size.")
    parser.add_argument("--start-at", type=int, default=0, help="Skip this many input chunks before upsert.")
    parser.add_argument("--limit", type=int, help="Maximum chunks to upsert after --start-at.")
    parser.add_argument("--max-retries", type=int, default=5, help="Retries per failed batch.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Initial retry delay in seconds.")
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        help="Optional JSON checkpoint updated after every successful batch.",
    )
    parser.add_argument("--query", help="Optional smoke query after ingestion.")
    parser.add_argument("--top-k", type=int, default=3, help="Number of chunks returned for the smoke query.")
    args = parser.parse_args(argv)

    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than 0")
    if args.start_at < 0:
        parser.error("--start-at must not be negative")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than 0")
    if args.max_retries < 0:
        parser.error("--max-retries must not be negative")
    if args.retry_delay < 0:
        parser.error("--retry-delay must not be negative")

    chunks_path = (args.chunks_file or (args.data_dir / "processed" / "chunks.jsonl")).resolve()
    checkpoint_path = args.checkpoint_file.resolve() if args.checkpoint_file else None
    chunk_iterator = iter_chunks_file(chunks_path, project_id=args.project_id)
    vector_store = create_vector_store_from_env()
    ingested_count = 0
    skipped_count = 0
    batch = []
    for source_index, chunk in enumerate(chunk_iterator):
        if source_index < args.start_at:
            skipped_count += 1
            continue
        if args.limit is not None and ingested_count + len(batch) >= args.limit:
            break
        batch.append(chunk)
        if len(batch) >= args.batch_size:
            _upsert_with_retry(
                vector_store=vector_store,
                project_id=args.project_id,
                chunks=batch,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
            )
            ingested_count += len(batch)
            _write_checkpoint(
                checkpoint_path,
                chunks_path=chunks_path,
                project_id=args.project_id,
                next_start_at=args.start_at + ingested_count,
                status="running",
            )
            batch = []
            print(f"[ingest] {ingested_count} chunks", file=sys.stderr, flush=True)
    if batch:
        _upsert_with_retry(
            vector_store=vector_store,
            project_id=args.project_id,
            chunks=batch,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
        )
        ingested_count += len(batch)
        _write_checkpoint(
            checkpoint_path,
            chunks_path=chunks_path,
            project_id=args.project_id,
            next_start_at=args.start_at + ingested_count,
            status="running",
        )
        print(f"[ingest] {ingested_count} chunks", file=sys.stderr, flush=True)

    embedding_column = os.getenv("LESSONPACK_SUPABASE_EMBEDDING_COLUMN", "embedding")
    result: dict[str, Any] = {
        "project_id": args.project_id,
        "chunks_file": str(chunks_path),
        "chunk_count": ingested_count,
        "skipped_count": skipped_count,
        "batch_size": args.batch_size,
        "checkpoint_file": str(checkpoint_path) if checkpoint_path else None,
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

    _write_checkpoint(
        checkpoint_path,
        chunks_path=chunks_path,
        project_id=args.project_id,
        next_start_at=args.start_at + ingested_count,
        status="complete",
    )

    close = getattr(vector_store, "close", None)
    if close is not None:
        close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _upsert_with_retry(
    *,
    vector_store: Any,
    project_id: str,
    chunks: list[Any],
    max_retries: int,
    retry_delay: float,
) -> None:
    for attempt in range(max_retries + 1):
        try:
            vector_store.upsert(project_id=project_id, chunks=chunks)
            return
        except Exception as exc:
            if attempt >= max_retries:
                raise
            delay = retry_delay * (2**attempt)
            print(
                f"[retry] batch failed ({type(exc).__name__}); "
                f"attempt {attempt + 1}/{max_retries}, waiting {delay:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)


def _write_checkpoint(
    path: Path | None,
    *,
    chunks_path: Path,
    project_id: str,
    next_start_at: int,
    status: str,
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "chunks_file": str(chunks_path),
        "project_id": project_id,
        "next_start_at": next_start_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    sys.exit(main())
