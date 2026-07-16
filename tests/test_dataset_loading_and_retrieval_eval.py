import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.dataset_loader import load_processed_chunks
from lectureops_agent.services.retrieval_service import retrieve_chunks
from lectureops_agent.services.retrieval_evaluation import evaluate_retrieval_gold
from scripts.prepare_mvp_dataset import find_matching_chunk_ids, retrieval_gold_data


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
            self.assertEqual(report["average_context_precision"], 0.5)
            self.assertEqual(report["average_context_recall"], 0.5)
            self.assertTrue(report["cases"][0]["hit"])
            self.assertEqual(report["cases"][0]["retrieved_chunk_ids"], ["source-a-c001"])
            self.assertEqual(report["cases"][0]["context_precision"], 1.0)
            self.assertEqual(report["cases"][0]["context_recall"], 1.0)
            self.assertFalse(report["cases"][1]["hit"])

    def test_retrieve_chunks_uses_metadata_and_korean_concept_synonyms(self):
        chunks = [
            MaterialChunk(
                chunk_id="generic-python-c001",
                project_id="project-dataset",
                document_id="generic-python",
                source_name="Python Tutorial - Functions",
                source_type="md",
                page=None,
                text="Python list examples appear here, but this is not the NCS data structure unit.",
                metadata={"tags": ["python", "function"], "section": "Functions"},
            ),
            MaterialChunk(
                chunk_id="ncs-data-structure-use-c005",
                project_id="project-dataset",
                document_id="ncs-data-structure-use",
                source_name="NCS Learning Module - 자료구조 활용",
                source_type="md",
                page=None,
                text="학습 1. 기본 자료구조 활용하기. 정렬 및 탐색 알고리즘을 다룬다.",
                metadata={
                    "source_id": "ncs-data-structure-use",
                    "tags": ["NCS", "data-structure", "algorithm", "search", "sort"],
                    "section": "자료구조 활용",
                },
            ),
        ]

        results = retrieve_chunks(query="자료구조 활용 NCS list 실습", chunks=chunks, top_k=1)

        self.assertEqual(results[0].chunk_id, "ncs-data-structure-use-c005")

    def test_retrieve_chunks_boosts_ncs_sources_when_query_mentions_ncs(self):
        chunks = [
            MaterialChunk(
                chunk_id="python-data-structures-c001",
                project_id="project-dataset",
                document_id="python-data-structures",
                source_name="Python Tutorial - Data Structures",
                source_type="md",
                page=None,
                text="Python list와 dictionary 자료구조 실습 예시",
                metadata={"tags": ["python", "list", "dictionary", "data-structure"]},
            ),
            MaterialChunk(
                chunk_id="ncs-data-structure-use-c001",
                project_id="project-dataset",
                document_id="ncs-data-structure-use",
                source_name="NCS Learning Module - 자료구조 활용",
                source_type="md",
                page=None,
                text="NCS 능력단위 자료구조 활용 학습모듈",
                metadata={"tags": ["NCS", "data-structure", "algorithm"], "section": "자료구조 활용"},
            ),
        ]

        results = retrieve_chunks(query="자료구조 활용 능력과 Python list/dict 실습을 연결하라 NCS", chunks=chunks, top_k=1)

        self.assertEqual(results[0].chunk_id, "ncs-data-structure-use-c001")

    def test_gold_matching_prefers_chunks_with_more_required_concepts(self):
        chunks = [
            {
                "chunk_id": "generic-ncs-c001",
                "source_id": "ncs-programming-language-use",
                "source_name": "NCS Learning Module - 프로그래밍 언어 활용",
                "text": "NCS 학습모듈 공통 안내",
                "tags": ["NCS", "programming"],
            },
            {
                "chunk_id": "ncs-data-structure-use-c005",
                "source_id": "ncs-data-structure-use",
                "source_name": "NCS Learning Module - 자료구조 활용",
                "text": "학습 1. 기본 자료구조 활용하기. NCS 기반 정렬 및 탐색 알고리즘 실습",
                "tags": ["NCS", "data-structure", "algorithm", "search", "sort"],
            },
        ]

        expected_ids = find_matching_chunk_ids(chunks, ["자료구조", "NCS"])

        self.assertEqual(expected_ids[0], "ncs-data-structure-use-c005")

    def test_retrieval_gold_queries_include_declared_domain_terms(self):
        chunks = [
            {
                "chunk_id": "ncs-data-structure-use-c001",
                "source_id": "ncs-data-structure-use",
                "source_name": "NCS Learning Module - 자료구조 활용",
                "section": "자료구조 활용",
                "text": "NCS 자료구조 활용 학습모듈",
                "tags": ["NCS", "data-structure"],
            }
        ]

        rows = retrieval_gold_data(chunks)
        q005 = next(row for row in rows if row["query_id"] == "q005")

        self.assertIn("NCS", q005["query"])

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
