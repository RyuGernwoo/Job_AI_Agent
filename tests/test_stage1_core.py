import sys
import unittest
from pathlib import Path

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


class Stage1CoreTests(unittest.TestCase):
    def test_project_schema_requires_learning_objectives(self):
        with self.assertRaises(ValueError):
            ProjectCreate(
                course_title="Generative AI Python Basics",
                lesson_title="Python functions",
                learner_profile="Beginner learners",
                learning_objectives=[],
                ncs_units=[],
            )

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

        self.assertEqual(package.status, PackageStatus.DRAFT)
        self.assertEqual(package.project_id, project.project_id)
        self.assertEqual(package.lesson_plan.title, project.lesson_title)
        self.assertEqual(package.lesson_plan.lecture_flow[0].citation_ids, [chunks[0].chunk_id])
        self.assertEqual(package.practice.citation_ids, [chunks[0].chunk_id])
        self.assertEqual(len(package.assessment.multiple_choice), 5)
        self.assertTrue(
            all(q.citation_ids == [chunks[0].chunk_id] for q in package.assessment.multiple_choice)
        )

    def test_fastapi_health_and_project_create(self):
        client = TestClient(create_app())

        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        created = client.post("/api/projects", json=sample_project_create().model_dump())
        self.assertEqual(created.status_code, 200)
        body = created.json()
        self.assertEqual(body["course_title"], "Generative AI Python Basics")
        self.assertIn("project_id", body)

    def test_fastapi_material_upload_chunks_markdown_file(self):
        client = TestClient(create_app())
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

    def test_fastapi_retrieve_returns_uploaded_chunks_by_query(self):
        client = TestClient(create_app())
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

    def test_fastapi_review_moves_package_from_draft_to_approved(self):
        client = TestClient(create_app())
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        chunk = MaterialChunk(
            chunk_id="doc001-p000-c001",
            project_id=project_id,
            document_id="doc001",
            source_name="python_tutorial_sample.md",
            source_type="md",
            page=None,
            text="A function can receive input and return output.",
            metadata={"license": "PSF License"},
        )
        generated = client.post(
            f"/api/projects/{project_id}/generate",
            json={"retrieved_chunks": [chunk.model_dump()]},
        )
        package_id = generated.json()["package_id"]

        reviewed = client.patch(
            f"/api/packages/{package_id}/review",
            json={"status": "reviewed", "reviewer_notes": "Evidence is aligned."},
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json()["status"], "reviewed")

        approved = client.patch(
            f"/api/packages/{package_id}/review",
            json={"status": "approved", "reviewer_notes": "Approved."},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")


if __name__ == "__main__":
    unittest.main()
