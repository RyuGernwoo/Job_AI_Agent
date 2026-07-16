"""Run the LessonPack AI MVP verification protocol and write reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.mvp_verification import render_mvp_verification_markdown, run_mvp_verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LessonPack AI MVP verification protocol.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Path to the data directory.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "eval", help="Report output directory.")
    parser.add_argument("--retrieval-top-k", type=int, default=3, help="Number of chunks retrieved per gold query.")
    parser.add_argument("--chunks-per-source", type=int, default=2, help="Number of chunks selected per generation source.")
    parser.add_argument("--demo-case-id", default="g003", help="generation_gold.yaml case id used for artifact demo.")
    parser.add_argument("--min-retrieval-hit-rate", type=float, default=0.7, help="Minimum retrieval hit-rate gate.")
    parser.add_argument(
        "--min-generation-case-pass-rate",
        type=float,
        default=1.0,
        help="Minimum generation case pass-rate gate.",
    )
    parser.add_argument("--require-real-llm", action="store_true", help="Fail unless a non-mock LLM provider is ready.")
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Optional JSON report path. Defaults to output-dir/mvp_verification_report.json.",
    )
    parser.add_argument(
        "--md-report",
        type=Path,
        help="Optional Markdown report path. Defaults to output-dir/mvp_verification_report.md.",
    )
    args = parser.parse_args(argv)

    report = run_mvp_verification(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        retrieval_top_k=args.retrieval_top_k,
        chunks_per_source=args.chunks_per_source,
        demo_case_id=args.demo_case_id,
        min_retrieval_hit_rate=args.min_retrieval_hit_rate,
        min_generation_case_pass_rate=args.min_generation_case_pass_rate,
        require_real_llm=args.require_real_llm,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_report = args.json_report or args.output_dir / "mvp_verification_report.json"
    md_report = args.md_report or args.output_dir / "mvp_verification_report.md"
    json_report.parent.mkdir(parents=True, exist_ok=True)
    md_report.parent.mkdir(parents=True, exist_ok=True)
    json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_report.write_text(render_mvp_verification_markdown(report) + "\n", encoding="utf-8")

    output = {
        "passed": report["passed"],
        "run_id": report["run_id"],
        "json_report": str(json_report),
        "md_report": str(md_report),
        "gates": report["gates"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
