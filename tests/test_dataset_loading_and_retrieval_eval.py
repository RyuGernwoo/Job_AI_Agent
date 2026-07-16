import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.dataset_loader import load_processed_chunks
from lectureops_agent.services.retrieval_evaluation import evaluate_retrieval_gold


class DatasetLoadingAndRetrievalEvalTests(unittest.TestCase):
    def test_load_processed_chunks_converts_jsonl_rows_to_material_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            self._write_chunks_jsonl(data_dir)

            chunks = load_processed_chunks(data_dir, project_id="project-dataset")

            self.assertEqual(len(chunks), 2)
            first = chunks[0]
            self.assertEqual(first.chunk_id, "source-a-c001")
            self.assertEqual(first.project_id, "project-dataset")
            self.assertEqual(first.document_id, "source-a")
            self.assertEqual(first.source_type, "md")
            self.assertEqual(first.metadata["source_url"], "https://example.test/source-a")
            self.assertEqual(first.metadata["tags"], ["python", "function"])
            self.assertEqual(first.metadata["review_status"], "needs_review")

    def test_evaluate_retrieval_gold_reports_hit_rate_and_case_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            self._write_chunks_jsonl(data_dir)
            gold_rows = [
                {
                    "query_id": "q001",
                    "query": "Python 함수 return",
                    "expected_chunk_ids": ["source-a-c001"],
                    "required_concepts": ["function"],
                },
                {
                    "query_id": "q002",
                    "query": "존재하지 않는 주제",
                    "expected_chunk_ids": ["source-a-c002"],
                    "required_concepts": ["missing"],
                },
            ]

            report = evaluate_retrieval_gold(
                chunks=load_processed_chunks(data_dir, project_id="project-dataset"),
                gold_rows=gold_rows,
                top_k=1,
            )

            self.assertEqual(report["total_queries"], 2)
            self.assertEqual(report["hit_count"], 1)
            self.assertEqual(report["empty_result_count"], 1)
            self.assertEqual(report["hit_rate"], 0.5)
            self.assertEqual(report["mean_reciprocal_rank"], 0.5)
            self.assertTrue(report["cases"][0]["hit"])
            self.assertEqual(report["cases"][0]["retrieved_chunk_ids"], ["source-a-c001"])
            self.assertFalse(report["cases"][1]["hit"])

    def _write_chunks_jsonl(self, data_dir: Path) -> None:
        processed = data_dir / "processed"
        processed.mkdir(parents=True)
        rows = [
            {
                "chunk_id": "source-a-c001",
                "source_id": "source-a",
                "source_name": "Sample Markdown",
                "source_url": "https://example.test/source-a",
                "license": "sample",
                "section": "Functions",
                "source_file": "data/raw/materials/source-a.md",
                "text": "Python 함수는 값을 return 할 수 있다.",
                "char_count": 24,
                "token_estimate": 6,
                "tags": ["python", "function"],
                "review_status": "needs_review",
            },
            {
                "chunk_id": "source-a-c002",
                "source_id": "source-a",
                "source_name": "Sample Markdown",
                "source_url": "https://example.test/source-a",
                "license": "sample",
                "section": "Assessment",
                "source_file": "data/raw/materials/source-a.md",
                "text": "평가 문항은 근거 citation을 포함해야 한다.",
                "char_count": 24,
                "token_estimate": 6,
                "tags": ["assessment"],
                "review_status": "needs_review",
            },
        ]
        with (processed / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
