import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lectureops_agent.services.mvp_verification import render_mvp_verification_markdown, run_mvp_verification


class MVPVerificationTests(unittest.TestCase):
    def test_run_mvp_verification_returns_passed_report_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            output_dir = Path(tmp) / "outputs" / "eval"
            self._write_dataset(data_dir)

            missing_env = Path(tmp) / "missing.env"
            with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(missing_env)}, clear=True):
                report = run_mvp_verification(
                    data_dir=data_dir,
                    output_dir=output_dir,
                    demo_case_id="g-demo",
                    retrieval_top_k=1,
                    chunks_per_source=1,
                    min_retrieval_hit_rate=1.0,
                    min_generation_case_pass_rate=1.0,
                )
            markdown = render_mvp_verification_markdown(report)

            self.assertTrue(report["passed"], report)
            self.assertEqual(report["validation"]["counts"]["chunks"], 2)
            self.assertEqual(report["retrieval"]["hit_rate"], 1.0)
            self.assertEqual(report["retrieval"]["average_context_recall"], 1.0)
            self.assertEqual(report["retrieval"]["average_ndcg_at_k"], 1.0)
            self.assertEqual(report["retrieval"]["average_required_concept_coverage"], 1.0)
            self.assertEqual(report["generation"]["case_pass_rate"], 1.0)
            self.assertEqual(report["generation"]["average_citation_coverage"], 1.0)
            self.assertEqual(report["generation"]["average_ncs_criterion_coverage"], 1.0)
            self.assertEqual(report["generation"]["average_ncs_assessment_coverage"], 1.0)
            self.assertEqual(report["generation"]["average_assessment_quality"], 1.0)
            self.assertEqual(report["generation"]["average_duration_alignment"], 1.0)
            self.assertTrue(report["demo"]["docx_exists"])
            self.assertTrue(report["demo"]["pptx_exists"])
            self.assertIn("MVP 품질 평가 결과", markdown)
            self.assertIn("PASS", markdown)

    def _write_dataset(self, data_dir: Path) -> None:
        processed = data_dir / "processed"
        gold = data_dir / "gold"
        raw_curriculum = data_dir / "raw" / "curriculum"
        raw_ncs = data_dir / "raw" / "ncs"
        processed.mkdir(parents=True)
        gold.mkdir(parents=True)
        raw_curriculum.mkdir(parents=True)
        raw_ncs.mkdir(parents=True)

        chunks = [
            {
                "chunk_id": "python-functions-c001",
                "source_id": "python-functions",
                "source_name": "Python Tutorial - Defining Functions",
                "source_url": "https://docs.python.org/3/tutorial/controlflow.html",
                "license": "PSF",
                "section": "Functions",
                "source_file": "data/raw/materials/tutorial_functions.md",
                "text": "Python function def return practice.",
                "tags": ["python", "function", "def", "return"],
                "review_status": "needs_review",
            },
            {
                "chunk_id": "ncs-demo-c001",
                "source_id": "ncs-demo",
                "source_name": "NCS Demo",
                "source_url": "https://www.ncs.go.kr/",
                "license": "NCS",
                "section": "NCS Demo",
                "source_file": "data/raw/ncs/converted_md/ncs-demo.md",
                "text": "NCS practice scenario steps submission rubric assessment criteria.",
                "tags": ["NCS", "assessment"],
                "review_status": "needs_review",
            },
        ]
        for row in chunks:
            row["char_count"] = len(row["text"])
            row["token_estimate"] = max(1, len(row["text"].split()))
        with (processed / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            for row in chunks:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

        self._write_csv(
            processed / "chunk_index.csv",
            ["chunk_id", "source_id", "section", "char_count", "token_estimate", "tags", "review_status"],
            [
                {
                    "chunk_id": row["chunk_id"],
                    "source_id": row["source_id"],
                    "section": row["section"],
                    "char_count": str(row["char_count"]),
                    "token_estimate": str(row["token_estimate"]),
                    "tags": ";".join(row["tags"]),
                    "review_status": row["review_status"],
                }
                for row in chunks
            ],
        )
        self._write_yaml(
            processed / "selected_sources.yaml",
            {
                "sources": [
                    {
                        "source_id": "python-functions",
                        "path": "data/raw/materials/tutorial_functions.md",
                        "source_name": "Python Tutorial - Defining Functions",
                        "source_url": "https://docs.python.org/3/tutorial/controlflow.html",
                        "license": "PSF",
                        "use_for": ["lesson_plan", "practice", "assessment"],
                    },
                    {
                        "source_id": "ncs-demo",
                        "path": "data/raw/ncs/converted_md/ncs-demo.md",
                        "source_name": "NCS Demo",
                        "source_url": "https://www.ncs.go.kr/",
                        "license": "NCS",
                        "use_for": ["ncs_alignment", "assessment"],
                    },
                ]
            },
        )
        self._write_csv(
            processed / "source_file_map.csv",
            ["source_id", "source_file", "alias_file"],
            [
                {
                    "source_id": row["source_id"],
                    "source_file": row["source_file"],
                    "alias_file": Path(row["source_file"]).name,
                }
                for row in chunks
            ],
        )
        (processed / "dataset_manifest.json").write_text(
            json.dumps(
                {
                    "chunk_count": 2,
                    "retrieval_gold_count": 1,
                    "generation_gold_count": 1,
                    "raw_sources": 2,
                    "quality_thresholds": {
                        "min_chunks": 2,
                        "min_retrieval_gold": 1,
                        "min_generation_gold": 1,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        with (gold / "retrieval_gold.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            file.write(
                json.dumps(
                    {
                        "query_id": "q-demo",
                        "query": "Python function return",
                        "expected_chunk_ids": ["python-functions-c001"],
                        "required_concepts": ["function", "return"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        self._write_yaml(
            gold / "generation_gold.yaml",
            {
                "cases": [
                    {
                        "case_id": "g-demo",
                        "input": {
                            "curriculum_id": "curr-demo",
                            "ncs_unit_id": "2001020231",
                            "source_ids": ["python-functions", "ncs-demo"],
                        },
                        "expected": {
                            "lesson_plan_sections": ["도입", "전개", "정리"],
                            "practice_required": [
                                "실습 시나리오",
                                "수행 절차",
                                "제출물",
                                "평가 기준",
                            ],
                            "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
                            "citation_required": True,
                        },
                    }
                ]
            },
        )
        self._write_yaml(
            gold / "human_eval_rubric.yaml",
            {
                "criteria": [
                    {
                        "name": "grounding",
                        "pass_score": 4,
                        "description": "Generated output cites source chunks.",
                    }
                ]
            },
        )
        self._write_yaml(
            raw_curriculum / "curriculum_python_prompt_automation.yaml",
            {
                "course_title": "Generative AI Python Basics",
                "lesson_title": "Python function automation practice",
                "learner_profile": "Job training learners",
                "learning_objectives": ["Use Python functions for automation practice."],
            },
        )
        self._write_yaml(
            raw_ncs / "ncs_application_sw_programming.yaml",
            {
                "selected_units": [
                    {
                        "unit_code": "2001020231",
                        "unit_name": "Programming language use",
                        "learning_topics": ["Script language use"],
                    }
                ]
            },
        )

    def _write_yaml(self, path: Path, data) -> None:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _write_csv(self, path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
