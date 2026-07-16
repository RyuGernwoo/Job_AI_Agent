"""Evaluate keyword retrieval against the LessonPack AI retrieval Gold Set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.dataset_loader import DEFAULT_DATASET_PROJECT_ID, load_processed_chunks
from lectureops_agent.services.retrieval_evaluation import evaluate_retrieval_gold, load_retrieval_gold
from scripts.validate_mvp_dataset import validate_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LessonPack AI retrieval quality.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Path to the data directory.")
    parser.add_argument("--project-id", default=DEFAULT_DATASET_PROJECT_ID, help="Project id assigned to loaded chunks.")
    parser.add_argument("--top-k", type=int, default=3, help="Number of chunks retrieved per query.")
    parser.add_argument("--min-hit-rate", type=float, default=0.0, help="Optional minimum hit rate gate.")
    parser.add_argument("--report", type=Path, help="Optional JSON report output path.")
    args = parser.parse_args(argv)

    validation = validate_dataset(args.data_dir)
    if validation["errors"]:
        print(json.dumps({"validation": validation}, ensure_ascii=False, indent=2))
        return 1

    chunks = load_processed_chunks(args.data_dir, project_id=args.project_id)
    gold_rows = load_retrieval_gold(args.data_dir / "gold" / "retrieval_gold.jsonl")
    report = evaluate_retrieval_gold(chunks=chunks, gold_rows=gold_rows, top_k=args.top_k)
    report["project_id"] = args.project_id
    report["data_dir"] = str(args.data_dir)
    report["validation"] = validation
    report["passed_min_hit_rate"] = report["hit_rate"] >= args.min_hit_rate

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")

    return 0 if report["passed_min_hit_rate"] else 1


if __name__ == "__main__":
    sys.exit(main())
