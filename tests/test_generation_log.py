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


def sample_project_create() -> ProjectCreate:
    return ProjectCreate(
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
    def test_generation_uses_provider_response_and_records_log(self):
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
        self.assertIn("Provider outline", result.package.lesson_plan.lecture_flow[1].content)
        self.assertEqual(result.log.package_id, "package-001")
        self.assertEqual(result.log.provider_name, "static-test")
        self.assertEqual(result.log.citation_ids, [chunk.chunk_id])
        self.assertEqual(result.log.retrieved_chunk_ids, [chunk.chunk_id])
        self.assertIn(project.lesson_title, result.log.prompt)
        self.assertIn(chunk.text, result.log.prompt)
        self.assertEqual(provider.prompts, [result.log.prompt])

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
        self.assertEqual(log["citation_ids"], [chunk.chunk_id])
        self.assertIn("Python functions", log["prompt"])


if __name__ == "__main__":
    unittest.main()
