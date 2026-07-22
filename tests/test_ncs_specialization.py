import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.app.main import create_app
from lectureops_agent.models.schemas import (
    CourseType,
    MaterialChunk,
    NCSCatalogCriterion,
    NCSCatalogUnit,
    NCSSourceStatus,
    NCSUnit,
    ProjectCreate,
)
from lectureops_agent.services.export_service import export_lesson_package_docx
from lectureops_agent.services.generation_service import (
    generate_lesson_package,
    generate_lesson_package_with_log,
)
from lectureops_agent.services.ncs_catalog_dataset import catalog_row, parse_ncs_catalog_markdown
from lectureops_agent.services.rag_repository import InMemoryRAGRepository
from lectureops_agent.services.rag_service import retrieve_evidence
from lectureops_agent.services.vector_store import InMemoryVectorStore


class GeneralNCSClaimProvider:
    name = "general-ncs-claim-test"
    schema_retries = 0

    def __init__(self, citation_id: str) -> None:
        self.citation_id = citation_id

    def generate(self, *, prompt: str) -> str:
        citation_ids = [self.citation_id]
        question = {
            "question": "함수 실행 결과를 확인하는 방법은 무엇인가?",
            "options": ["결과를 출력한다.", "코드를 삭제한다.", "입력을 지운다.", "실행하지 않는다."],
            "answer_index": 0,
            "explanation": "출력된 결과로 함수 동작을 확인한다.",
            "citation_ids": citation_ids,
        }
        return json.dumps(
            {
                "lesson_plan": {
                    "lecture_flow": [
                        {
                            "section": section,
                            "duration_min": 20,
                            "content": "NCS 수행준거에 따라 함수를 실습한다.",
                            "citation_ids": citation_ids,
                        }
                        for section in ["도입", "전개", "정리"]
                    ]
                },
                "practice": {
                    "scenario": "함수 결과를 확인한다.",
                    "steps": ["요구사항 확인", "함수 작성", "결과 확인"],
                    "submission": "코드와 결과",
                    "rubric": ["정확성", "완성도", "설명력"],
                    "citation_ids": citation_ids,
                },
                "assessment": {
                    "multiple_choice": [question for _ in range(5)],
                    "performance_task": {
                        "title": "함수 실습",
                        "description": "함수를 작성하고 실행한다.",
                        "rubric": ["정확성", "완성도", "설명력"],
                        "citation_ids": citation_ids,
                    },
                },
            },
            ensure_ascii=False,
        )


def chunk(project_id: str, *, ncs: bool = False) -> MaterialChunk:
    metadata = {"source_url": "https://example.com/material", "license": "test"}
    if ncs:
        metadata.update(
            {
                "ncs_unit_code": "NCS-001",
                "tags": ["NCS"],
                "dataset_version": "ncs-test-v1",
            }
        )
    return MaterialChunk(
        chunk_id=f"{project_id}-chunk-{'ncs' if ncs else 'general'}",
        project_id=project_id,
        document_id=f"{project_id}-doc",
        source_name="NCS module" if ncs else "General material",
        source_type="md",
        text="function input return practice assessment",
        metadata=metadata,
    )


def ncs_project() -> ProjectCreate:
    return ProjectCreate(
        course_type="ncs",
        course_title="Python NCS",
        lesson_title="Function practice",
        learner_profile="Beginners",
        learning_objectives=["Write a function."],
        ncs_units=[
            NCSUnit(
                unit_code="NCS-001",
                unit_name="Programming",
                target_criteria=["함수의 입력과 반환값을 활용할 수 있다."],
                source_status="user_provided",
            )
        ],
        retrieval_queries=["function input return"],
    )


class NCSSpecializationTests(unittest.TestCase):
    def test_project_schema_separates_ncs_and_general_courses(self):
        with self.assertRaises(ValueError):
            ProjectCreate(
                course_type="ncs",
                course_title="Missing unit",
                lesson_title="Lesson",
                learner_profile="Learners",
                learning_objectives=["Learn."],
                ncs_units=[],
            )
        with self.assertRaises(ValueError):
            ProjectCreate(
                course_type="general",
                course_title="General",
                lesson_title="Lesson",
                learner_profile="Learners",
                learning_objectives=["Learn."],
                ncs_units=ncs_project().ncs_units,
            )
        with self.assertRaises(ValueError):
            ProjectCreate(
                course_type="ncs",
                course_title="Too many units",
                lesson_title="Lesson",
                learner_profile="Learners",
                learning_objectives=["Learn."],
                ncs_units=[
                    NCSUnit(
                        unit_code=f"NCS-{index}",
                        unit_name=f"Unit {index}",
                        target_criteria=["Criterion"],
                    )
                    for index in range(6)
                ],
            )

    def test_general_package_has_no_ncs_claims_or_alignment(self):
        project = ProjectCreate(
            course_type="general",
            course_title="General Python",
            lesson_title="Function practice",
            learner_profile="Beginners",
            learning_objectives=["Write a function."],
            ncs_units=[],
        ).to_project(project_id="general-project")
        package = generate_lesson_package(
            project=project,
            retrieved_chunks=[chunk(project.project_id)],
        )

        self.assertEqual(package.course_type, CourseType.GENERAL)
        self.assertIsNone(package.ncs_coverage)
        self.assertTrue(all(not item.ncs_alignment for item in package.lesson_plan.lecture_flow))
        self.assertFalse(package.practice.ncs_alignment)
        self.assertTrue(
            all(not item.ncs_alignment for item in package.assessment.multiple_choice)
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "general.docx"
            export_lesson_package_docx(package=package, output_path=path)
            text = "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
        self.assertNotIn("NCS 연계", text)
        self.assertIn("학습목표-활동-평가 연결", text)

    def test_general_generation_rejects_provider_ncs_claims(self):
        project = ProjectCreate(
            course_type="general",
            course_title="General Python",
            lesson_title="Function practice",
            learner_profile="Beginners",
            learning_objectives=["Write a function."],
        ).to_project(project_id="general-provider-project")
        material = chunk(project.project_id)

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[material],
            llm_provider=GeneralNCSClaimProvider(material.chunk_id),
        )

        self.assertFalse(result.log.structured_output_applied)
        self.assertIn("must not include NCS claims", result.log.schema_validation_errors[0])
        learner_text = " ".join(
            [
                *(item.content for item in result.package.lesson_plan.lecture_flow),
                result.package.practice.scenario,
                result.package.assessment.performance_task.description,
            ]
        )
        self.assertNotIn("NCS", learner_text)

    def test_ncs_package_includes_target_criterion_coverage(self):
        project = ncs_project().to_project(project_id="ncs-project")
        package = generate_lesson_package(
            project=project,
            retrieved_chunks=[chunk(project.project_id)],
        )

        self.assertEqual(package.course_type, CourseType.NCS)
        self.assertIsNotNone(package.ncs_coverage)
        report = package.ncs_coverage
        assert report is not None
        self.assertEqual(report.target_criteria_count, 1)
        self.assertEqual(report.coverage, 1.0)
        self.assertEqual(report.assessment_coverage, 1.0)
        self.assertEqual(report.source_statuses, [NCSSourceStatus.USER_PROVIDED])

    def test_general_retrieval_excludes_baseline_ncs_chunks(self):
        project = ProjectCreate(
            course_type="general",
            course_title="General Python",
            lesson_title="Function practice",
            learner_profile="Beginners",
            learning_objectives=["Write a function."],
        ).to_project(project_id="general-project")
        store = InMemoryVectorStore()
        store.upsert(project_id="mvp-dataset", chunks=[chunk("mvp-dataset", ncs=True)])
        repository = InMemoryRAGRepository()

        run = retrieve_evidence(
            project=project,
            query="function input return",
            vector_store=store,
            repository=repository,
            top_k=5,
            candidate_k=5,
            baseline_project_id="mvp-dataset",
            include_baseline=True,
        )

        self.assertEqual(run.course_type, CourseType.GENERAL)
        self.assertEqual(run.evidence, [])

    def test_ncs_retrieval_excludes_other_coded_baseline_units(self):
        project = ncs_project().to_project(project_id="ncs-filter-project")
        other_unit_chunk = chunk("mvp-dataset", ncs=True).model_copy(
            update={
                "chunk_id": "other-unit-chunk",
                "metadata": {
                    "ncs_unit_code": "NCS-999",
                    "tags": ["NCS"],
                    "dataset_version": "ncs-test-v1",
                },
            }
        )
        store = InMemoryVectorStore()
        store.upsert(project_id="mvp-dataset", chunks=[other_unit_chunk])

        run = retrieve_evidence(
            project=project,
            query="function input return",
            vector_store=store,
            repository=InMemoryRAGRepository(),
            top_k=5,
            candidate_k=5,
            baseline_project_id="mvp-dataset",
            include_baseline=True,
        )

        self.assertEqual(run.evidence, [])

    def test_catalog_api_resolves_verified_unit(self):
        criterion = NCSCatalogCriterion(
            criterion_code="NCS-001.1.1",
            element_code="NCS-001.1",
            element_name="함수 활용하기",
            text="함수의 입력과 반환값을 활용할 수 있다.",
        )
        catalog_unit = NCSCatalogUnit(
            unit_code="NCS-001",
            unit_name="공식 프로그래밍",
            catalog_version="24v1",
            criteria=[criterion],
        )
        repository = InMemoryRAGRepository(ncs_catalog=[catalog_unit])
        with patch.dict(
            os.environ,
            {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")},
            clear=True,
        ):
            client = TestClient(
                create_app(
                    vector_store=InMemoryVectorStore(),
                    rag_repository=repository,
                )
            )

        searched = client.get("/api/ncs/catalog/search", params={"q": "프로그래밍"})
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()[0]["unit_code"], "NCS-001")

        payload = ncs_project().model_dump(mode="json")
        payload["ncs_units"][0].update(
            {
                "unit_name": "잘못 입력한 명칭",
                "source_status": "verified",
            }
        )
        created = client.post("/api/projects", json=payload)

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["ncs_units"][0]["unit_name"], "공식 프로그래밍")
        self.assertEqual(created.json()["ncs_units"][0]["catalog_version"], "24v1")

    def test_catalog_parser_extracts_units_and_criteria(self):
        markdown = """---
ncs_hierarchy:
  - 정보통신
  - 정보기술
source_url: https://www.ncs.go.kr/
---
## 능력단위: 2001020001_24v1

**능력단위 명칭:** 프로그래밍 기초

**능력단위 정의:** 프로그램을 작성하는 능력이다.

- 열 1: 2001020001_24v1.1
  함수 활용하기
- 열 5: 1.1 함수의 입력을 정의할 수 있다.
  1.2 함수의 반환값을 활용할 수 있다.

### Row 7
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "catalog.md"
            path.write_text(markdown, encoding="utf-8")
            units = parse_ncs_catalog_markdown(path)

        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].unit_code, "2001020001_24v1")
        self.assertEqual(units[0].catalog_version, "24v1")
        self.assertEqual(len(units[0].criteria), 2)
        self.assertEqual(len(catalog_row(units[0])["source_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
