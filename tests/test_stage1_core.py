import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.app.main import create_app
from lectureops_agent.models.schemas import (
    MaterialChunk,
    NCSUnit,
    PackageStatus,
    ProjectCreate,
)
from lectureops_agent.services.chunk_service import chunk_text
from lectureops_agent.services.generation_service import generate_lesson_package
from lectureops_agent.services.vector_store import InMemoryVectorStore


def sample_project_create() -> ProjectCreate:
    return ProjectCreate(
        course_type="ncs",
        course_title="Generative AI Python Basics",
        lesson_title="Python functions and prompt automation practice",
        learner_profile="Job training learners with basic Python experience",
        total_training_hours=6,
        total_lessons=3,
        theory_ratio_percent=40,
        practice_ratio_percent=60,
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


def make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_isolated_test_client() -> TestClient:
    with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")}, clear=True):
        return TestClient(create_app())


class Stage1CoreTests(unittest.TestCase):
    def test_project_schema_requires_learning_objectives(self):
        with self.assertRaises(ValueError):
            ProjectCreate(
                course_type="general",
                course_title="Generative AI Python Basics",
                lesson_title="Python functions",
                learner_profile="Beginner learners",
                learning_objectives=[],
                ncs_units=[],
            )

    def test_project_schema_validates_training_plan(self):
        project = sample_project_create()

        # 패키지 duration은 총 훈련 시간 기준(6시간 = 360분)이며, 차시 수로 나누지 않는다.
        self.assertEqual(project.lesson_duration_minutes, 360)
        self.assertEqual(project.theory_ratio_percent + project.practice_ratio_percent, 100)

        invalid_payload = project.model_dump()
        invalid_payload.update(theory_ratio_percent=50, practice_ratio_percent=60)
        with self.assertRaises(ValueError):
            ProjectCreate.model_validate(invalid_payload)

    def test_chunk_text_creates_stable_ids_and_overlap(self):
        text = "abcdefghijklmnopqrstuvwxyz" * 20

        chunks = chunk_text(
            project_id="project-001",
            document_id="doc001",
            source_name="python_tutorial_sample.md",
            source_type="md",
            text=text,
            chunk_size_chars=80,
            chunk_overlap_chars=10,
            metadata={"license": "PSF License"},
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].chunk_id, "doc001-p000-c001")
        self.assertEqual(chunks[1].chunk_id, "doc001-p000-c002")
        self.assertEqual(chunks[0].text[-10:], chunks[1].text[:10])
        self.assertEqual(chunks[0].metadata["license"], "PSF License")

    def test_generation_uses_citations_and_creates_five_questions(self):
        project = sample_project_create().to_project(project_id="project-001")
        chunks = [
            MaterialChunk(
                chunk_id="doc001-p000-c001",
                project_id=project.project_id,
                document_id="doc001",
                source_name="python_tutorial_sample.md",
                source_type="md",
                page=None,
                text="A function can receive input and return output.",
                metadata={"license": "PSF License"},
            )
        ]

        package = generate_lesson_package(project=project, retrieved_chunks=chunks)

        self.assertEqual(package.status, PackageStatus.GENERATED)
        self.assertEqual(package.project_id, project.project_id)
        self.assertEqual(package.lesson_plan.title, project.lesson_title)
        self.assertEqual(package.lesson_plan.lecture_flow[0].citation_ids, [chunks[0].chunk_id])
        self.assertEqual(sum(item.duration_min or 0 for item in package.lesson_plan.lecture_flow), 360)
        self.assertEqual(package.template_metadata.total_training_hours, 6)
        self.assertEqual(package.template_metadata.total_lessons, 3)
        self.assertEqual(package.template_metadata.theory_ratio_percent, 40)
        self.assertEqual(package.template_metadata.practice_ratio_percent, 60)
        self.assertEqual(package.practice.citation_ids, [chunks[0].chunk_id])
        self.assertEqual(len(package.assessment.multiple_choice), 5)
        self.assertTrue(
            all(q.citation_ids == [chunks[0].chunk_id] for q in package.assessment.multiple_choice)
        )

    def test_fastapi_health_and_project_create(self):
        client = create_isolated_test_client()

        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["service"], "lessonpack-ai")

        created = client.post("/api/projects", json=sample_project_create().model_dump())
        self.assertEqual(created.status_code, 200)
        body = created.json()
        self.assertEqual(body["course_title"], "Generative AI Python Basics")
        self.assertEqual(body["total_training_hours"], 6)
        self.assertEqual(body["total_lessons"], 3)
        self.assertIn("project_id", body)

    def test_fastapi_cors_allows_lovable_origins(self):
        client = create_isolated_test_client()
        origins = [
            "https://7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovableproject.com",
            "https://id-preview--7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovable.app",
            "https://lessonpack-ai.lovable.app",
        ]

        for origin in origins:
            with self.subTest(origin=origin):
                response = client.options(
                    "/api/projects",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                self.assertIn("POST", response.headers["access-control-allow-methods"])

                health = client.get("/health", headers={"Origin": origin})
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.headers["access-control-allow-origin"], origin)

    def test_unexpected_upload_error_keeps_cors_header(self):
        with patch.dict(
            os.environ,
            {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")},
            clear=True,
        ):
            client = TestClient(create_app(), raise_server_exceptions=False)
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        origin = "https://lessonpack-ai.lovable.app"

        with patch(
            "lectureops_agent.app.main.decode_text_material",
            side_effect=Exception("unexpected parser failure"),
        ):
            response = client.post(
                f"/api/projects/{project_id}/materials",
                files={"file": ("sample.md", b"content", "text/markdown")},
                headers={"Origin": origin},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)
        self.assertEqual(
            response.json()["detail"],
            "An unexpected server error occurred. Please try again shortly.",
        )

    def test_material_upload_rejects_file_over_configured_limit(self):
        with patch.dict(
            os.environ,
            {
                "LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env"),
                "LESSONPACK_MAX_UPLOAD_MB": "1",
            },
            clear=True,
        ):
            client = TestClient(create_app())
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        origin = "https://lessonpack-ai.lovable.app"

        response = client.post(
            f"/api/projects/{project_id}/materials",
            files={"file": ("large.md", b"x" * (1024 * 1024 + 1), "text/markdown")},
            headers={"Origin": origin},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)
        self.assertEqual(response.json()["detail"], "File size must not exceed 1MB.")

    def test_material_indexing_failure_returns_cors_enabled_503(self):
        store = InMemoryVectorStore()
        with patch.dict(
            os.environ,
            {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")},
            clear=True,
        ):
            client = TestClient(create_app(vector_store=store))
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        origin = "https://lessonpack-ai.lovable.app"

        with patch.object(store, "upsert", side_effect=Exception("embedding provider failed")):
            response = client.post(
                f"/api/projects/{project_id}/materials",
                files={"file": ("sample.md", b"content", "text/markdown")},
                headers={"Origin": origin},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)
        self.assertEqual(
            response.json()["detail"],
            "Material indexing is temporarily unavailable. Please try again shortly.",
        )

    def test_fastapi_material_upload_chunks_markdown_file(self):
        client = create_isolated_test_client()
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]

        upload = client.post(
            f"/api/projects/{project_id}/materials",
            files={
                "file": (
                    "python_tutorial_sample.md",
                    "A function can receive input and return output.\n" * 40,
                    "text/markdown",
                )
            },
        )

        self.assertEqual(upload.status_code, 200)
        body = upload.json()
        self.assertEqual(body["project_id"], project_id)
        self.assertEqual(body["source_name"], "python_tutorial_sample.md")
        self.assertGreaterEqual(body["chunk_count"], 1)
        self.assertEqual(body["chunks"][0]["chunk_id"], f"{body['document_id']}-p000-c001")

    def test_fastapi_material_upload_extracts_pdf_text(self):
        client = create_isolated_test_client()
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        pdf_bytes = make_pdf_bytes("PDF functions return output for training materials.")

        upload = client.post(
            f"/api/projects/{project_id}/materials",
            files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        )

        self.assertEqual(upload.status_code, 200)
        body = upload.json()
        self.assertEqual(body["source_type"], "pdf")
        self.assertEqual(body["source_name"], "sample.pdf")
        self.assertIn("PDF functions return output", body["chunks"][0]["text"])

    def test_fastapi_retrieve_returns_uploaded_chunks_by_query(self):
        client = create_isolated_test_client()
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        client.post(
            f"/api/projects/{project_id}/materials",
            files={
                "file": (
                    "python_tutorial_sample.md",
                    "Functions receive input and return output. Loops repeat tasks.\n" * 20,
                    "text/markdown",
                )
            },
        )

        retrieved = client.post(
            f"/api/projects/{project_id}/retrieve",
            json={"query": "return output", "top_k": 2},
        )

        self.assertEqual(retrieved.status_code, 200)
        chunks = retrieved.json()
        self.assertGreaterEqual(len(chunks), 1)
        self.assertIn("return output", chunks[0]["text"])
        self.assertEqual(chunks[0]["project_id"], project_id)

if __name__ == "__main__":
    unittest.main()
