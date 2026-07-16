import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_mvp_dataset import validate_dataset


class DatasetValidationTests(unittest.TestCase):
    def test_valid_dataset_reports_counts_without_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            self._write_minimal_dataset(data_dir)

            report = validate_dataset(data_dir)

            self.assertEqual(report["errors"], [])
            self.assertEqual(report["counts"]["chunks"], 2)
            self.assertEqual(report["counts"]["retrieval_gold"], 1)
            self.assertEqual(report["counts"]["generation_gold"], 1)
            self.assertEqual(report["counts"]["selected_sources"], 1)

    def test_retrieval_gold_must_reference_existing_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            self._write_minimal_dataset(data_dir, expected_chunk_ids=["missing-c999"])

            report = validate_dataset(data_dir)

            self.assertTrue(any("missing-c999" in error for error in report["errors"]))

    def _write_minimal_dataset(self, data_dir: Path, expected_chunk_ids=None):
        expected_chunk_ids = expected_chunk_ids or ["source-a-c001"]
        processed = data_dir / "processed"
        gold = data_dir / "gold"
        processed.mkdir(parents=True)
        gold.mkdir(parents=True)

        chunks = [
            {
                "chunk_id": "source-a-c001",
                "source_id": "source-a",
                "source_name": "Sample Source",
                "source_url": "https://example.test/source-a",
                "license": "sample",
                "section": "Section 1",
                "source_file": "data/raw/materials/source-a.md",
                "text": "Python 함수는 입력을 받아 결과를 반환한다.",
                "char_count": 24,
                "token_estimate": 6,
                "tags": ["python", "function"],
                "review_status": "needs_review",
            },
            {
                "chunk_id": "source-a-c002",
                "source_id": "source-a",
                "source_name": "Sample Source",
                "source_url": "https://example.test/source-a",
                "license": "sample",
                "section": "Section 1",
                "source_file": "data/raw/materials/source-a.md",
                "text": "평가 문항은 근거 chunk citation을 포함해야 한다.",
                "char_count": 29,
                "token_estimate": 7,
                "tags": ["assessment"],
                "review_status": "needs_review",
            },
        ]
        self._write_jsonl(processed / "chunks.jsonl", chunks)

        (processed / "chunk_index.csv").write_text(
            "chunk_id,source_id,section,char_count,token_estimate,tags,review_status\n"
            "source-a-c001,source-a,Section 1,24,6,python;function,needs_review\n"
            "source-a-c002,source-a,Section 1,29,7,assessment,needs_review\n",
            encoding="utf-8",
        )
        self._write_yaml(
            processed / "selected_sources.yaml",
            {
                "dataset_version": "test",
                "sources": [
                    {
                        "source_id": "source-a",
                        "path": "data/raw/materials/source-a.md",
                        "source_name": "Sample Source",
                        "source_url": "https://example.test/source-a",
                        "license": "sample",
                        "use_for": ["lesson_plan", "assessment"],
                    }
                ],
            },
        )
        (processed / "source_file_map.csv").write_text(
            "role,original_path,alias_path,selected_for_mvp\n"
            "selected_source,data/raw/materials/source-a.md,data/raw/materials/source-a.md,True\n",
            encoding="utf-8",
        )
        (processed / "dataset_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_version": "test",
                    "raw_sources": 1,
                    "chunk_count": 2,
                    "retrieval_gold_count": 1,
                    "generation_gold_count": 1,
                    "quality_thresholds": {
                        "min_chunks": 2,
                        "min_retrieval_gold": 1,
                        "min_generation_gold": 1,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self._write_jsonl(
            gold / "retrieval_gold.jsonl",
            [
                {
                    "query_id": "q001",
                    "query": "Python 함수 평가 문항을 생성하라",
                    "expected_chunk_ids": expected_chunk_ids,
                    "required_concepts": ["function"],
                }
            ],
        )
        self._write_yaml(
            gold / "generation_gold.yaml",
            {
                "cases": [
                    {
                        "case_id": "g001",
                        "input": {
                            "curriculum_id": "curr-test",
                            "ncs_unit_id": "2001020231",
                            "source_ids": ["source-a"],
                        },
                        "expected": {
                            "lesson_plan_sections": ["도입", "전개", "정리"],
                            "practice_required": ["실습"],
                            "assessment_required": {
                                "mcq_count": 5,
                                "performance_task_count": 1,
                            },
                            "citation_required": True,
                        },
                    }
                ]
            },
        )
        self._write_yaml(
            gold / "human_eval_rubric.yaml",
            {
                "scale": "1-5",
                "criteria": [
                    {
                        "name": "근거 신뢰도",
                        "pass_score": 4,
                        "description": "citation 포함 여부",
                    }
                ],
            },
        )

    def _write_jsonl(self, path: Path, rows):
        with path.open("w", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_yaml(self, path: Path, data):
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
