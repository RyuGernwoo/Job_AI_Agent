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


class RAGApiTests(unittest.TestCase):
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

    def test_rag_health_exposes_runtime_provider_without_secrets(self):
        client, _, _ = isolated_client()

        response = client.get("/health/rag")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["vector_store"], "InMemoryVectorStore")
        self.assertEqual(response.json()["repository"], "InMemoryRAGRepository")
        self.assertNotIn("key", response.text.casefold())


if __name__ == "__main__":
    unittest.main()
