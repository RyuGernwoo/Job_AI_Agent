import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.app.main import create_app
from lectureops_agent.models.schemas import MaterialChunk, NCSUnit, ProjectCreate
from lectureops_agent.services.llm_provider import MockLLMProvider
from lectureops_agent.services.rag_repository import InMemoryRAGRepository
from lectureops_agent.services.vector_store import InMemoryVectorStore


def project_payload() -> dict:
    return ProjectCreate(
        course_title="Python automation",
        lesson_title="Functions and return values",
        learner_profile="Beginning job training learners",
        learning_objectives=["Explain function inputs and return values."],
        ncs_units=[NCSUnit(unit_code="MVP-NCS-001", unit_name="Programming basics")],
    ).model_dump()


def isolated_client(
    *,
    vector_store: InMemoryVectorStore | None = None,
    repository: InMemoryRAGRepository | None = None,
    llm_provider=None,
) -> tuple[TestClient, InMemoryVectorStore, InMemoryRAGRepository]:
    store = vector_store or InMemoryVectorStore()
    repo = repository or InMemoryRAGRepository()
    with patch.dict(
        os.environ,
        {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")},
        clear=True,
    ):
        app = create_app(
            vector_store=store,
            rag_repository=repo,
            llm_provider=llm_provider or MockLLMProvider(),
        )
    return TestClient(app), store, repo


class CountingProvider:
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, prompt: str) -> str:
        self.calls += 1
        return "unused"


class FailingProjectRepository(InMemoryRAGRepository):
    def save_project(self, project) -> None:
        raise ValueError("missing database column")


class PromptAwareStructuredProvider:
    name = "prompt-aware-structured"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, prompt: str) -> str:
        self.prompts.append(prompt)
        match = re.search(r"^\[([^\]]+)\]", prompt, re.MULTILINE)
        if match is None:
            raise AssertionError("evidence citation id missing from prompt")
        citation_id = match.group(1)
        revised = "Revision mode:" in prompt
        question = {
            "question": "함수의 반환값을 확인하는 방법은 무엇인가?",
            "options": ["호출 결과를 출력한다.", "입력을 삭제한다.", "함수를 제거한다.", "실행하지 않는다."],
            "answer_index": 0,
            "explanation": "호출 결과를 출력하면 반환값을 확인할 수 있다.",
            "citation_ids": [citation_id],
        }
        payload = {
            "lesson_plan": {
                "lecture_flow": [
                    {
                        "section": "도입",
                        "duration_min": 10,
                        "content": "초급 예제로 수정한 도입" if revised else "함수 입력과 반환값 도입",
                        "citation_ids": [citation_id],
                    },
                    {
                        "section": "전개",
                        "duration_min": 40,
                        "content": "함수를 작성하고 호출 결과를 비교한다.",
                        "citation_ids": [citation_id],
                    },
                    {
                        "section": "정리",
                        "duration_min": 10,
                        "content": "입력과 반환값의 관계를 정리한다.",
                        "citation_ids": [citation_id],
                    },
                ]
            },
            "practice": {
                "scenario": "간단한 함수 실습" if revised else "함수 자동화 실습",
                "steps": ["요구사항을 확인한다.", "함수를 작성한다.", "결과를 확인한다."],
                "submission": "코드와 실행 결과를 제출한다.",
                "rubric": ["입력을 받는다.", "결과를 반환한다.", "실행 결과가 정확하다."],
                "citation_ids": [citation_id],
            },
            "assessment": {
                "multiple_choice": [question for _ in range(5)],
                "performance_task": {
                    "title": "함수 수행평가",
                    "description": "입력값을 처리해 결과를 반환하는 함수를 작성한다.",
                    "rubric": ["요구사항을 충족한다.", "결과가 정확하다.", "설명이 명확하다."],
                    "citation_ids": [citation_id],
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False)


class RAGApiTests(unittest.TestCase):
    def test_project_persistence_failure_returns_service_unavailable(self):
        client, _, _ = isolated_client(repository=FailingProjectRepository())

        response = client.post("/api/projects", json=project_payload())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Project persistence is temporarily unavailable. Please try again shortly.",
        )

    def test_server_owned_rag_retrieval_and_generation_share_run(self):
        client, store, repository = isolated_client()
        created = client.post("/api/projects", json=project_payload())
        project_id = created.json()["project_id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/materials",
            files={
                "file": (
                    "instructor.md",
                    "A Python function receives input and returns output. " * 20,
                    "text/markdown",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 200)
        store.upsert(
            project_id="mvp-dataset",
            chunks=[
                MaterialChunk(
                    chunk_id="baseline-functions-c001",
                    project_id="mvp-dataset",
                    document_id="baseline-doc",
                    source_name="Python Tutorial",
                    source_type="md",
                    page=None,
                    text="Functions use parameters and return statements.",
                    metadata={"license": "PSF License"},
                )
            ],
        )

        retrieved = client.post(
            f"/api/projects/{project_id}/rag/retrieve",
            json={"query": "function return output", "top_k": 3},
        )
        self.assertEqual(retrieved.status_code, 200)
        retrieval_body = retrieved.json()
        self.assertGreaterEqual(len(retrieval_body["evidence"]), 1)
        self.assertEqual(retrieval_body["evidence"][0]["scope"], "project")
        self.assertIn(retrieval_body["retrieval_run_id"], repository.retrieval_runs)

        generated = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={"query": "function return output", "top_k": 3},
        )
        self.assertEqual(generated.status_code, 200)
        generation_body = generated.json()
        package_id = generation_body["package"]["package_id"]
        self.assertEqual(
            generation_body["retrieval_run_id"],
            repository.generation_runs[package_id].retrieval_run_id,
        )
        self.assertEqual(generation_body["trace_id"], repository.generation_runs[package_id].trace_id)

        log = client.get(f"/api/packages/{package_id}/generation-log")
        self.assertEqual(log.status_code, 200)
        self.assertEqual(log.json()["retrieval_run_id"], generation_body["retrieval_run_id"])
        self.assertEqual(log.json()["trace_id"], generation_body["trace_id"])

        stored_run = client.get(f"/api/retrieval-runs/{generation_body['retrieval_run_id']}")
        self.assertEqual(stored_run.status_code, 200)
        selected_ids = {item["chunk"]["chunk_id"] for item in stored_run.json()["evidence"]}
        self.assertTrue(set(log.json()["citation_ids"]).issubset(selected_ids))

    def test_rag_generate_does_not_call_llm_without_evidence(self):
        provider = CountingProvider()
        client, _, _ = isolated_client(llm_provider=provider)
        created = client.post("/api/projects", json=project_payload())
        project_id = created.json()["project_id"]

        generated = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={"query": "nonexistent evidence", "include_baseline": False},
        )

        self.assertEqual(generated.status_code, 422)
        self.assertEqual(provider.calls, 0)

    def test_rag_generate_rejects_client_supplied_chunks(self):
        client, _, _ = isolated_client()
        created = client.post("/api/projects", json=project_payload())
        project_id = created.json()["project_id"]

        response = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={"retrieved_chunks": []},
        )

        self.assertEqual(response.status_code, 422)

    def test_regenerate_applies_instruction_to_existing_package_and_issues_new_id(self):
        provider = PromptAwareStructuredProvider()
        client, _, repository = isolated_client(llm_provider=provider)
        created = client.post("/api/projects", json=project_payload())
        project_id = created.json()["project_id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/materials",
            files={
                "file": (
                    "functions.md",
                    "A Python function receives input and returns output. " * 20,
                    "text/markdown",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 200)

        generated = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={"query": "function input return output", "include_baseline": False},
        )
        self.assertEqual(generated.status_code, 200)
        source = generated.json()["package"]
        source_package_id = source["package_id"]
        self.assertEqual(source["status"], "generated")

        instruction = "실습 난이도를 초급으로 낮추고 도입 문장을 쉽게 바꿔 주세요."
        regenerated = client.post(
            f"/api/packages/{source_package_id}/regenerate",
            json={"instruction": instruction, "include_baseline": False},
        )

        self.assertEqual(regenerated.status_code, 200)
        body = regenerated.json()
        revised = body["package"]
        self.assertNotEqual(revised["package_id"], source_package_id)
        self.assertEqual(revised["status"], "regenerated")
        self.assertEqual(body["source_package_id"], source_package_id)
        self.assertEqual(revised["lesson_plan"]["lecture_flow"][0]["content"], "초급 예제로 수정한 도입")
        self.assertIn(instruction, provider.prompts[-1])
        self.assertIn("함수 입력과 반환값 도입", provider.prompts[-1])

        original = client.get(f"/api/packages/{source_package_id}")
        self.assertEqual(original.status_code, 200)
        self.assertEqual(original.json()["status"], "generated")
        self.assertEqual(original.json()["lesson_plan"]["lecture_flow"][0]["content"], "함수 입력과 반환값 도입")

        log = client.get(f"/api/packages/{revised['package_id']}/generation-log")
        self.assertEqual(log.status_code, 200)
        self.assertEqual(log.json()["source_package_id"], source_package_id)
        self.assertEqual(log.json()["revision_instruction"], instruction)
        self.assertIn(revised["package_id"], repository.generation_runs)

        exported = client.get(f"/api/packages/{revised['package_id']}/export.docx")
        self.assertEqual(exported.status_code, 200)

    def test_rag_health_exposes_runtime_provider_without_secrets(self):
        client, _, _ = isolated_client()

        response = client.get("/health/rag")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["vector_store"], "InMemoryVectorStore")
        self.assertEqual(response.json()["repository"], "InMemoryRAGRepository")
        self.assertNotIn("key", response.text.casefold())


if __name__ == "__main__":
    unittest.main()
