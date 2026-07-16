import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.models.schemas import MaterialChunk, NCSUnit, ProjectCreate
from lectureops_agent.services.generation_evaluation import evaluate_lesson_package, load_generation_gold
from lectureops_agent.services.generation_service import generate_lesson_package


def sample_project() -> ProjectCreate:
    return ProjectCreate(
        course_title="생성형 AI 활용 Python 기초",
        lesson_title="Python 자료구조와 자동화 실습",
        learner_profile="Python 기초 문법을 학습한 직업훈련 수강생",
        learning_objectives=[
            "list 또는 dictionary를 활용해 데이터를 처리할 수 있다.",
            "정렬 또는 탐색 알고리즘을 설명하고 실습할 수 있다.",
        ],
        ncs_units=[
            NCSUnit(
                unit_code="2001020235",
                unit_name="자료구조 활용",
                elements=["기본 자료구조 활용", "정렬 및 탐색 알고리즘 활용"],
            )
        ],
    ).to_project(project_id="project-generation-eval")


def sample_chunks(project_id: str) -> list[MaterialChunk]:
    return [
        MaterialChunk(
            chunk_id="python-data-structures-c004",
            project_id=project_id,
            document_id="python-data-structures",
            source_name="Python Tutorial - Data Structures",
            source_type="md",
            page=None,
            text="The list methods append() and pop() support stack style practice.",
            metadata={"tags": ["python", "list", "dictionary"], "section": "5. Data Structures"},
        ),
        MaterialChunk(
            chunk_id="ncs-data-structure-use-c005",
            project_id=project_id,
            document_id="ncs-data-structure-use",
            source_name="NCS Learning Module - 자료구조 활용",
            source_type="md",
            page=None,
            text="자료구조 활용 학습모듈은 정렬 및 탐색 알고리즘 실습과 평가 기준을 포함한다.",
            metadata={"tags": ["NCS", "data-structure", "search", "sort"], "section": "자료구조 활용"},
        ),
    ]


class GenerationEvaluationTests(unittest.TestCase):
    def test_load_generation_gold_reads_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generation_gold.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "cases": [
                            {
                                "case_id": "g001",
                                "input": {"source_ids": ["python-functions"]},
                                "expected": {"lesson_plan_sections": ["도입"]},
                            }
                        ]
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            gold = load_generation_gold(path)

            self.assertEqual(gold["cases"][0]["case_id"], "g001")

    def test_generated_package_satisfies_generation_gold_expectations(self):
        project = sample_project()
        chunks = sample_chunks(project.project_id)
        package = generate_lesson_package(project=project, retrieved_chunks=chunks, package_id="package-g003")
        expected = {
            "lesson_plan_sections": ["도입", "전개", "정리"],
            "practice_required": ["list 또는 dictionary", "정렬 또는 탐색", "평가 기준"],
            "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
            "citation_required": True,
        }

        result = evaluate_lesson_package(package=package, expected=expected, retrieved_chunk_ids=[c.chunk_id for c in chunks])

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["missing_lesson_sections"], [])
        self.assertEqual(result["missing_practice_items"], [])
        self.assertEqual(result["missing_citation_items"], [])
        self.assertEqual(result["citation_coverage"]["coverage"], 1.0)

    def test_generation_evaluation_fails_missing_citations(self):
        project = sample_project()
        chunks = sample_chunks(project.project_id)
        package = generate_lesson_package(project=project, retrieved_chunks=chunks, package_id="package-bad")
        package.practice.citation_ids = []
        expected = {
            "lesson_plan_sections": ["도입", "전개", "정리"],
            "practice_required": ["평가 기준"],
            "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
            "citation_required": True,
        }

        result = evaluate_lesson_package(package=package, expected=expected, retrieved_chunk_ids=[c.chunk_id for c in chunks])

        self.assertFalse(result["passed"])
        self.assertIn("practice", result["missing_citation_items"])
        self.assertLess(result["citation_coverage"]["coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
