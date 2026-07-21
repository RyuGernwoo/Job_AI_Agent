import os
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.app.main import create_app
from lectureops_agent.models.schemas import MaterialChunk, NCSUnit, ProjectCreate


def sample_project_create() -> ProjectCreate:
    return ProjectCreate(
        course_title="Generative AI Python Basics",
        lesson_title="Python functions and prompt automation practice",
        learner_profile="Job training learners with basic Python experience",
        learning_objectives=["Explain function inputs and return values."],
        ncs_units=[NCSUnit(unit_code="MVP-NCS-001", unit_name="AI basics", elements=[])],
    )


def create_isolated_test_client() -> TestClient:
    with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env")}, clear=True):
        return TestClient(create_app())


class ExportApiTests(unittest.TestCase):
    def test_fastapi_generated_package_exports_without_review(self):
        client = create_isolated_test_client()
        created = client.post("/api/projects", json=sample_project_create().model_dump())
        project_id = created.json()["project_id"]
        chunk = MaterialChunk(
            chunk_id="doc001-p000-c001",
            project_id=project_id,
            document_id="doc001",
            source_name="sample.pdf",
            source_type="pdf",
            page=None,
            text="A function can receive input and return output.",
            metadata={"license": "PSF License"},
        )
        generated = client.post(
            f"/api/projects/{project_id}/generate",
            json={"retrieved_chunks": [chunk.model_dump()]},
        )
        package_id = generated.json()["package_id"]
        self.assertEqual(generated.json()["status"], "generated")

        exported = client.get(f"/api/packages/{package_id}/export.docx")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(
            exported.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(exported.content.startswith(b"PK"))
        content_disposition = unquote(exported.headers["content-disposition"])
        self.assertIn("Python_functions_and_prompt_automation_practice_교안.docx", content_disposition)
        self.assertNotIn(package_id, content_disposition)

        exported_pptx = client.get(f"/api/packages/{package_id}/export.pptx")
        self.assertEqual(exported_pptx.status_code, 200)
        self.assertEqual(
            exported_pptx.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        self.assertTrue(exported_pptx.content.startswith(b"PK"))
        content_disposition = unquote(exported_pptx.headers["content-disposition"])
        self.assertIn("Python_functions_and_prompt_automation_practice_강의자료.pptx", content_disposition)
        self.assertNotIn(package_id, content_disposition)


if __name__ == "__main__":
    unittest.main()
