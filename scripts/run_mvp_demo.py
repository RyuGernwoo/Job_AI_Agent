"""Run a reproducible LessonPack AI MVP demo flow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.llm_provider import create_llm_provider_from_env
from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness
from lectureops_agent.services.mvp_demo_runner import run_mvp_demo
from scripts.validate_mvp_dataset import validate_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LessonPack AI MVP demo flow.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Path to the data directory.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "demo", help="Demo artifact output path.")
    parser.add_argument("--case-id", default="g003", help="generation_gold.yaml case id to demo.")
    parser.add_argument("--chunks-per-source", type=int, default=2, help="Number of chunks selected per source id.")
    parser.add_argument("--require-real-llm", action="store_true", help="Fail unless a non-mock LLM provider is ready.")
    args = parser.parse_args(argv)

    validation = validate_dataset(args.data_dir)
    if validation["errors"]:
        print(json.dumps({"validation": validation}, ensure_ascii=False, indent=2))
        return 1

    provider_readiness = check_llm_provider_readiness()
    if not provider_readiness["ready"] or (args.require_real_llm and not provider_readiness["real_provider_ready"]):
        print(
            json.dumps(
                {
                    "provider_readiness": provider_readiness,
                    "require_real_llm": args.require_real_llm,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    provider = create_llm_provider_from_env()
    report = run_mvp_demo(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        case_id=args.case_id,
        chunks_per_source=args.chunks_per_source,
        llm_provider=provider,
    )
    report["validation"] = validation
    report["provider_readiness"] = provider_readiness
    Path(report["report_path"]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["evaluation"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
