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

from lectureops_agent.app.main import _merge_revision_evidence_chunks, create_app
from lectureops_agent.models.schemas import MaterialChunk, NCSUnit, ProjectCreate
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import MockLLMProvider
from lectureops_agent.services.rag_repository import InMemoryRAGRepository
from lectureops_agent.services.vector_store import InMemoryVectorStore


def project_payload() -> dict:
    return ProjectCreate(
        course_type="ncs",
        course_title="Python automation",
        lesson_title="Functions and return values",
        learner_profile="Beginning job training learners",
        learning_objectives=["Explain function inputs and return values."],
        ncs_units=[
            NCSUnit(
                unit_code="MVP-NCS-001",
                unit_name="Programming basics",
                elements=["Explain function inputs and return values."],
            )
        ],
        retrieval_queries=["function inputs", "return values"],
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
    ncs_criterion = "Explain function inputs and return values."

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
            "ncs_criteria": [self.ncs_criterion],
        }
        payload = {
            "lesson_plan": {
                "lecture_flow": [
                    {
                        "section": "도입",
                        "duration_min": 10,
                        "content": "초급 예제로 수정한 도입" if revised else "함수 입력과 반환값 도입",
                        "citation_ids": [citation_id],
                        "ncs_criteria": [self.ncs_criterion],
                    },
                    {
                        "section": "전개",
                        "duration_min": 40,
                        "content": "함수를 작성하고 호출 결과를 비교한다.",
                        "citation_ids": [citation_id],
                        "ncs_criteria": [self.ncs_criterion],
                    },
                    {
                        "section": "정리",
                        "duration_min": 10,
                        "content": "입력과 반환값의 관계를 정리한다.",
                        "citation_ids": [citation_id],
                        "ncs_criteria": [self.ncs_criterion],
                    },
                ]
            },
            "practice": {
                "scenario": "간단한 함수 실습" if revised else "함수 자동화 실습",
                "steps": ["요구사항을 확인한다.", "함수를 작성한다.", "결과를 확인한다."],
                "submission": "코드와 실행 결과를 제출한다.",
                "rubric": ["입력을 받는다.", "결과를 반환한다.", "실행 결과가 정확하다."],
                "citation_ids": [citation_id],
                "ncs_criteria": [self.ncs_criterion],
            },
            "assessment": {
                "multiple_choice": [question for _ in range(5)],
                "performance_task": {
                    "title": "함수 수행평가",
                    "description": "입력값을 처리해 결과를 반환하는 함수를 작성한다.",
                    "rubric": ["요구사항을 충족한다.", "결과가 정확하다.", "설명이 명확하다."],
                    "citation_ids": [citation_id],
                    "ncs_criteria": [self.ncs_criterion],
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False)


class RevisionFailureProvider(PromptAwareStructuredProvider):
    def generate(self, *, prompt: str) -> str:
        if "Revision mode:" in prompt:
            raise RuntimeError("upstream provider unavailable")
        return super().generate(prompt=prompt)


class IgnoringRevisionProvider:
    name = "ignoring-revision"
    schema_retries = 1

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.delegate = PromptAwareStructuredProvider()

    def generate(self, *, prompt: str) -> str:
        self.prompts.append(prompt)
        unchanged_prompt = prompt.replace("Revision mode:", "Ignored revision:")
        return self.delegate.generate(prompt=unchanged_prompt)


class RAGApiTests(unittest.TestCase):
    def test_revision_evidence_keeps_source_citations_and_deduplicates_new_chunks(self):
        project = ProjectCreate.model_validate(project_payload()).to_project(
            project_id="project-001"
        )
        source_chunk = MaterialChunk(
            chunk_id="source-c001",
            project_id=project.project_id,
            document_id="doc-source",
            source_name="source.md",
            source_type="md",
            text="Source evidence for function inputs and return values.",
        )
        source_package = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=[source_chunk],
            llm_provider=MockLLMProvider(),
            package_id="package-source",
        ).package
        new_chunk = source_chunk.model_copy(
            update={
                "chunk_id": "new-c001",
                "document_id": "doc-new",
                "source_name": "new.txt",
                "source_type": "txt",
                "text": "New evidence found for the revision request.",
            }
        )

        merged = _merge_revision_evidence_chunks(
            source_package=source_package,
            retrieved_chunks=[source_chunk, new_chunk],
            project_id=project.project_id,
        )

        self.assertEqual([chunk.chunk_id for chunk in merged], ["source-c001", "new-c001"])
        self.assertEqual(merged[0].metadata["revision_source"], True)
        self.assertEqual(merged[1].source_type, "txt")

    def test_project_persistence_failure_returns_service_unavailable(self):
        client, _, _ = isolated_client(repository=FailingProjectRepository())

        response = client.post("/api/projects", json=project_payload())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Project persistence is temporarily unavailable. Please try again shortly.",
        )

    def test_project_normalizes_and_deduplicates_multiple_retrieval_queries(self):
        client, _, _ = isolated_client()
        payload = project_payload()
        payload["retrieval_queries"] = [
            "  함수   입력과 반환값  ",
            "함수 입력과 반환값",
            "list 자료구조 실습",
        ]

        response = client.post("/api/projects", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["retrieval_queries"],
            ["함수 입력과 반환값", "list 자료구조 실습"],
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

    def test_uploaded_material_generates_when_baseline_has_no_matching_ncs_field(self):
        client, _, repository = isolated_client()
        created = client.post("/api/projects", json=project_payload())
        project_id = created.json()["project_id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/materials",
            files={
                "file": (
                    "custom-welding-guide.md",
                    "토치 각도와 보호 가스 유량을 기록한다. 시편의 비드 상태를 관찰하고 점검표에 남긴다.",
                    "text/markdown",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(
            uploaded.json()["chunks"][0]["metadata"]["evidence_origin"],
            "user_upload",
        )

        retrieved = client.post(
            f"/api/projects/{project_id}/rag/retrieve",
            json={
                "query": "Supabase 공통 자료에 등록되지 않은 신규 NCS 능력단위",
                "top_k": 5,
                "include_baseline": True,
            },
        )

        self.assertEqual(retrieved.status_code, 200)
        retrieval_body = retrieved.json()
        self.assertEqual(len(retrieval_body["evidence"]), 1)
        evidence = retrieval_body["evidence"][0]
        self.assertEqual(evidence["scope"], "project")
        self.assertEqual(evidence["strategy"], "project_material_fallback")
        self.assertEqual(evidence["chunk"]["metadata"]["evidence_origin"], "user_upload")

        generated = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={
                "retrieval_run_id": retrieval_body["retrieval_run_id"],
                "selected_chunk_ids": [evidence["chunk"]["chunk_id"]],
            },
        )

        self.assertEqual(generated.status_code, 200)
        generation_body = generated.json()
        self.assertEqual(
            generation_body["retrieval_run_id"],
            retrieval_body["retrieval_run_id"],
        )
        source = generation_body["package"]["evidence_sources"][0]
        self.assertEqual(source["evidence_origin"], "user_upload")
        self.assertEqual(source["evidence_authority"], "user_provided")
        self.assertIn(generation_body["package"]["package_id"], repository.generation_runs)

    def test_multi_query_generation_merges_evidence_into_one_retrieval_run(self):
        client, _, repository = isolated_client()
        payload = project_payload()
        payload["retrieval_queries"] = ["함수 입력과 반환값", "list append 실습"]
        created = client.post("/api/projects", json=payload)
        project_id = created.json()["project_id"]
        for filename, content in (
            ("functions.md", "함수는 입력을 받아 처리한 뒤 반환값을 제공한다."),
            ("lists.md", "list append는 목록 끝에 항목을 추가하는 실습에 사용한다."),
        ):
            uploaded = client.post(
                f"/api/projects/{project_id}/materials",
                files={"file": (filename, content, "text/markdown")},
            )
            self.assertEqual(uploaded.status_code, 200)

        generated = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={
                "queries": payload["retrieval_queries"],
                "top_k": 5,
                "include_baseline": False,
            },
        )

        self.assertEqual(generated.status_code, 200)
        body = generated.json()
        run = repository.retrieval_runs[body["retrieval_run_id"]]
        self.assertIn("함수 입력과 반환값", run.query)
        self.assertIn("list append 실습", run.query)
        self.assertGreaterEqual(len(run.evidence), 2)
        matched_queries = {
            query
            for item in run.evidence
            for query in item.chunk.metadata.get("matched_queries", [])
        }
        self.assertEqual(matched_queries, set(payload["retrieval_queries"]))
        self.assertEqual(body["package"]["template_metadata"]["generation_scope"], "single_lesson_mvp")

    def test_rag_generate_rejects_chunks_outside_referenced_retrieval_run(self):
        client, _, _ = isolated_client()
        created = client.post("/api/projects", json=project_payload())
        project_id = created.json()["project_id"]
        client.post(
            f"/api/projects/{project_id}/materials",
            files={"file": ("guide.md", "함수 입력과 반환값을 설명한다.", "text/markdown")},
        )
        retrieved = client.post(
            f"/api/projects/{project_id}/rag/retrieve",
            json={"query": "함수 반환값", "include_baseline": False},
        ).json()

        generated = client.post(
            f"/api/projects/{project_id}/rag/generate",
            json={
                "retrieval_run_id": retrieved["retrieval_run_id"],
                "selected_chunk_ids": ["client-injected-c001"],
            },
        )

        self.assertEqual(generated.status_code, 422)
        self.assertIn("client-injected-c001", generated.text)

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
        # The revision instruction must lead the prompt so the model does not under-weight it.
        self.assertIn("PRIORITY EDIT REQUEST", provider.prompts[-1])
        self.assertLess(
            provider.prompts[-1].index("PRIORITY EDIT REQUEST"),
            provider.prompts[-1].index("LessonPack AI generation request"),
        )

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

    def test_regenerate_rejects_non_meaningful_instruction(self):
        client, _, _ = isolated_client()

        response = client.post(
            "/api/packages/unknown/regenerate",
            json={"instruction": ".", "include_baseline": False},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("meaningful natural-language request", response.text)

    def test_regenerate_retries_and_rejects_unchanged_provider_output(self):
        provider = IgnoringRevisionProvider()
        client, _, _ = isolated_client(llm_provider=provider)
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
        source_package_id = generated.json()["package"]["package_id"]

        response = client.post(
            f"/api/packages/{source_package_id}/regenerate",
            json={
                "instruction": "실습 난이도를 초급으로 낮춰 주세요.",
                "include_baseline": False,
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("수정 요청이 패키지 내용에 반영되지 않았습니다", response.text)
        self.assertEqual(len(provider.prompts), 3)
        self.assertIn("previous revision was structurally valid", provider.prompts[-1])

    def test_regenerate_provider_failure_returns_cors_enabled_gateway_error(self):
        provider = RevisionFailureProvider()
        client, _, _ = isolated_client(llm_provider=provider)
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
        source_package_id = generated.json()["package"]["package_id"]

        response = client.post(
            f"/api/packages/{source_package_id}/regenerate",
            headers={"Origin": "https://lessonpack-ai.lovable.app"},
            json={"instruction": "Make the practice easier.", "include_baseline": False},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "https://lessonpack-ai.lovable.app",
        )
        self.assertEqual(
            response.json()["detail"],
            "Lesson package regeneration is temporarily unavailable. Please try again shortly.",
        )

    def test_rag_health_exposes_runtime_provider_without_secrets(self):
        client, _, _ = isolated_client()

        response = client.get("/health/rag")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["vector_store"], "InMemoryVectorStore")
        self.assertEqual(response.json()["repository"], "InMemoryRAGRepository")
        self.assertNotIn("key", response.text.casefold())


if __name__ == "__main__":
    unittest.main()
