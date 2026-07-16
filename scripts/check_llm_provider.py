"""Check LessonPack AI LLM provider readiness."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.llm_provider import create_llm_provider_from_env
from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check LessonPack AI LLM provider readiness.")
    parser.add_argument("--config", type=Path, help="Optional config path. Also sets LESSONPACK_CONFIG for probing.")
    parser.add_argument("--require-real", action="store_true", help="Fail unless a non-mock provider is ready.")
    parser.add_argument("--probe", action="store_true", help="Call the configured provider with a short smoke prompt.")
    args = parser.parse_args(argv)

    if args.config:
        os.environ["LESSONPACK_CONFIG"] = str(args.config)

    report = check_llm_provider_readiness(config_path=args.config)
    if args.probe and report["ready"]:
        probe = _probe_provider()
        report["probe"] = probe
        if not probe["ok"]:
            report["ready"] = False
            report["real_provider_ready"] = False

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.require_real:
        return 0 if report["real_provider_ready"] else 1
    return 0 if report["ready"] else 1


def _probe_provider() -> dict:
    try:
        provider = create_llm_provider_from_env()
        response = provider.generate(prompt="LessonPack AI provider smoke test. Reply with a short confirmation.")
    except Exception as exc:  # noqa: BLE001 - CLI diagnostic boundary.
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "provider_name": provider.name,
        "response_preview": response[:160],
    }


if __name__ == "__main__":
    sys.exit(main())
