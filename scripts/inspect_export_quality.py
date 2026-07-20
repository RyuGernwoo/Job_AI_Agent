from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docx import Document
from pptx import Presentation


ENGLISH_LABELS = [
    "Learning Objectives",
    "Lesson Plan",
    "Practice",
    "Assessment",
    "Submission",
    "Answer",
    "Explanation",
    "Citations",
    "Evidence Sources",
]


def inspect_exports(*, docx_path: Path | None, pptx_path: Path | None) -> dict[str, Any]:
    report: dict[str, Any] = {"passed": True, "files": {}}
    if docx_path:
        report["files"]["docx"] = _inspect_text(_docx_text(docx_path))
    if pptx_path:
        report["files"]["pptx"] = _inspect_text(_pptx_text(pptx_path))

    for result in report["files"].values():
        if not result["passed"]:
            report["passed"] = False
    return report


def _docx_text(path: Path) -> str:
    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())


def _pptx_text(path: Path) -> str:
    presentation = Presentation(path)
    values: list[str] = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                values.append(shape.text)
    return "\n".join(values)


def _inspect_text(text: str) -> dict[str, Any]:
    signals = {
        "has_korean_objectives": "학습 목표" in text,
        "has_evidence_sources": "근거 출처" in text,
        "has_license": "라이선스:" in text,
        "has_ncs_alignment": "NCS 연계:" in text,
        "has_review_section": "검수 이력" in text,
        "has_english_labels": any(label in text for label in ENGLISH_LABELS),
    }
    passed = (
        signals["has_korean_objectives"]
        and signals["has_evidence_sources"]
        and signals["has_ncs_alignment"]
        and not signals["has_english_labels"]
    )
    return {"passed": passed, "signals": signals}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect LessonPack AI DOCX/PPTX export quality.")
    parser.add_argument("--docx", type=Path)
    parser.add_argument("--pptx", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if not args.docx and not args.pptx:
        parser.error("at least one of --docx or --pptx is required")

    report = inspect_exports(docx_path=args.docx, pptx_path=args.pptx)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
