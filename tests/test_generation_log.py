import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.app.main import create_app
from lectureops_agent.models.schemas import MaterialChunk, NCSUnit, ProjectCreate
from lectureops_agent.services.generation_service import generate_lesson_package_with_log


class StaticLLMProvider:
    name = "static-test"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Provider outline: explain inputs, returns, guided practice, and assessment."


class StructuredLLMProvider:
    name = "structured-test"
    ncs_criterion = "Analyze requirements and write simple automation code."

    def __init__(self, citation_id: str) -> None:
        self.citation_id = citation_id

    def generate(self, *, prompt: str) -> str:
        question = {
            "question": "함수의 반환값을 확인하는 방법은 무엇인가?",
            "options": ["호출 결과를 출력한다.", "코드를 실행하지 않는다.", "입력을 삭제한다.", "함수를 제거한다."],
            "answer_index": 0,
            "explanation": "호출 결과를 확인하면 반환값을 검증할 수 있다.",
            "citation_ids": [self.citation_id],
            "ncs_criteria": [self.ncs_criterion],
        }
        payload = {
            "lesson_plan": {
                "lecture_flow": [
                    {
                        "section": "도입",
                        "duration_min": 10,
                        "content": "함수의 입력과 반환값을 실제 예제로 확인한다.",
                        "citation_ids": [self.citation_id],
                        "ncs_criteria": [self.ncs_criterion],
                    },
                    {
                        "section": "전개",
                        "duration_min": 40,
                        "content": "매개변수를 받는 함수를 작성하고 호출 결과를 비교한다.",
                        "citation_ids": [self.citation_id],
                        "ncs_criteria": [self.ncs_criterion],
                    },
                    {
                        "section": "정리",
                        "duration_min": 10,
                        "content": "작성한 함수의 입력과 반환값을 설명한다.",
                        "citation_ids": [self.citation_id],
                        "ncs_criteria": [self.ncs_criterion],
                    },
                ]
            },
            "practice": {
                "scenario": "입력값을 받아 결과를 반환하는 자동화 함수를 작성한다.",
                "steps": ["함수 요구사항을 정리한다.", "함수를 구현한다.", "호출 결과를 검증한다."],
                "submission": "소스 코드와 실행 결과를 제출한다.",
                "rubric": ["함수가 입력을 받는다.", "결과를 반환한다.", "실행 결과가 재현된다."],
                "citation_ids": [self.citation_id],
                "ncs_criteria": [self.ncs_criterion],
            },
            "assessment": {
                "multiple_choice": [question for _ in range(5)],
                "performance_task": {
                    "title": "함수 자동화 수행평가",
                    "description": "입력값을 처리해 결과를 반환하는 함수를 작성한다.",
                    "rubric": ["요구사항을 충족한다.", "결과가 정확하다.", "코드 설명이 명확하다."],
                    "citation_ids": [self.citation_id],
                    "ncs_criteria": [self.ncs_criterion],
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False)


class RepairingLLMProvider(StructuredLLMProvider):
    name = "repairing-test"
    schema_retries = 1

    def __init__(self, citation_id: str) -> None:
        super().__init__(citation_id)
        self.prompts: list[str] = []

    def generate(self, *, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return "not-json"
        return super().generate(prompt=prompt)


class MissingNCSCriteriaProvider(StructuredLLMProvider):
    name = "missing-ncs-criteria-test"

    def generate(self, *, prompt: str) -> str:
        payload = json.loads(super().generate(prompt=prompt))
        for flow in payload["lesson_plan"]["lecture_flow"]:
            flow.pop("ncs_criteria")
        payload["practice"].pop("ncs_criteria")
        for question in payload["assessment"]["multiple_choice"]:
            question.pop("ncs_criteria")
        payload["assessment"]["performance_task"].pop("ncs_criteria")
        return json.dumps(payload, ensure_ascii=False)


def sample_project_create() -> ProjectCreate:
    return ProjectCreate(
        course_type="ncs",
        course_title="Generative AI Python Basics",
        lesson_title="Python functions and prompt automation practice",
        learner_profile="Job training learners with basic Python experience",
        learning_objectives=[
            "Explain function inputs and return values.",
            "Write a simple prompt automation function.",
        ],
        ncs_units=[
            NCSUnit(
                unit_code="MVP-NCS-001",
                unit_name="AI-assisted programming basics",
                elements=["Analyze requirements and write simple automation code."],
            )
        ],
    )


def sample_chunk(project_id: str) -> MaterialChunk:
    return MaterialChunk(
        chunk_id="doc001-p000-c001",
        project_id=project_id,
        document_id="doc001",
        source_name="python_tutorial_sample.md",
        source_type="md",
        page=None,
        text="A function can receive input and return output.",
        metadata={"license": "PSF License"},
    )


class GenerationLogTests(unittest.TestCase):
    def test_generation_records_provider_response_without_leaking_free_text_into_package(self):
        project = sample_project_create().to_project(project_id="project-001")
        provider = StaticLLMProvider()
        chunk = sample_chunk(project.project_id)

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[chunk],
            llm_provider=provider,
            package_id="package-001",
        )

        self.assertEqual(result.package.package_id, "package-001")
        self.assertNotIn("Provider outline", result.package.lesson_plan.lecture_flow[1].content)
        self.assertEqual(result.log.package_id, "package-001")
        self.assertEqual(result.log.provider_name, "static-test")
        self.assertFalse(result.log.structured_output_applied)
        self.assertIn("Provider outline", result.log.response_text)
        self.assertEqual(result.log.citation_ids, [chunk.chunk_id])
        self.assertEqual(result.log.retrieved_chunk_ids, [chunk.chunk_id])
        self.assertTrue(result.log.trace_id)
        self.assertEqual(result.log.generation_attempts, 1)
        self.assertEqual(len(result.log.schema_validation_errors), 1)
        self.assertIn(project.lesson_title, result.log.prompt)
        self.assertIn(chunk.text, result.log.prompt)
        self.assertIn("Training plan: 2 total hours across 1 lessons", result.log.prompt)
        self.assertIn("Delivery ratio: theory 30% and practice 70%", result.log.prompt)
        self.assertEqual(provider.prompts, [result.log.prompt])

    def test_generation_applies_valid_structured_provider_output(self):
        project = sample_project_create().to_project(project_id="project-001")
        chunk = sample_chunk(project.project_id)

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[chunk],
            llm_provider=StructuredLLMProvider(chunk.chunk_id),
            package_id="package-structured",
        )

        self.assertTrue(result.log.structured_output_applied)
        self.assertEqual(result.package.lesson_plan.lecture_flow[1].content, "매개변수를 받는 함수를 작성하고 호출 결과를 비교한다.")
        self.assertEqual(result.package.practice.scenario, "입력값을 받아 결과를 반환하는 자동화 함수를 작성한다.")
        self.assertIn("함수화", result.package.practice.submission)
        self.assertEqual(
            sum(item.duration_min or 0 for item in result.package.lesson_plan.lecture_flow),
            project.lesson_duration_minutes,
        )
        self.assertEqual(len(result.package.assessment.multiple_choice), 5)
        self.assertEqual(result.log.citation_ids, [chunk.chunk_id])
        self.assertIn("Return one JSON object only", result.log.prompt)

    def test_generation_repairs_invalid_structured_output_once(self):
        project = sample_project_create().to_project(project_id="project-001")
        chunk = sample_chunk(project.project_id)
        provider = RepairingLLMProvider(chunk.chunk_id)

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[chunk],
            llm_provider=provider,
            package_id="package-repaired",
        )

        self.assertTrue(result.log.structured_output_applied)
        self.assertEqual(result.log.generation_attempts, 2)
        self.assertEqual(len(result.log.schema_validation_errors), 1)
        self.assertIn("validation feedback", provider.prompts[1])
        self.assertIn("response did not contain a JSON object", provider.prompts[1])

    def test_generation_rejects_structured_output_with_unknown_citation(self):
        project = sample_project_create().to_project(project_id="project-001")
        chunk = sample_chunk(project.project_id)

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[chunk],
            llm_provider=StructuredLLMProvider("unknown-citation"),
            package_id="package-invalid-citation",
        )

        self.assertFalse(result.log.structured_output_applied)
        self.assertNotEqual(
            result.package.lesson_plan.lecture_flow[1].content,
            "매개변수를 받는 함수를 작성하고 호출 결과를 비교한다.",
        )
        self.assertEqual(result.log.citation_ids, [chunk.chunk_id])

    def test_ncs_generation_rejects_structured_output_without_criterion_mapping(self):
        project = sample_project_create().to_project(project_id="project-001")
        chunk = sample_chunk(project.project_id)

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[chunk],
            llm_provider=MissingNCSCriteriaProvider(chunk.chunk_id),
            package_id="package-missing-ncs-criteria",
        )

        self.assertFalse(result.log.structured_output_applied)
        self.assertIn("items without ncs_criteria", result.log.schema_validation_errors[0])

    def test_fastapi_generate_stores_generation_log(self):
        provider = StaticLLMProvider()
        with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")}, clear=True):
            client = TestClient(create_app(llm_provider=provider))
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        chunk = sample_chunk(project_id)

        generated = client.post(
            f"/api/projects/{project_id}/generate",
            json={"retrieved_chunks": [chunk.model_dump()]},
        )
        self.assertEqual(generated.status_code, 200)
        package_id = generated.json()["package_id"]

        log_response = client.get(f"/api/packages/{package_id}/generation-log")

        self.assertEqual(log_response.status_code, 200)
        log = log_response.json()
        self.assertEqual(log["package_id"], package_id)
        self.assertEqual(log["project_id"], project_id)
        self.assertEqual(log["provider_name"], "static-test")
        self.assertFalse(log["structured_output_applied"])
        self.assertEqual(log["citation_ids"], [chunk.chunk_id])
        self.assertIn("Python functions", log["prompt"])


if __name__ == "__main__":
    unittest.main()
