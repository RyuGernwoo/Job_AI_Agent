import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.models.schemas import MaterialChunk, NCSUnit, PackageStatus, ProjectCreate
from lectureops_agent.services.export_service import export_lesson_package_docx
from lectureops_agent.services.generation_service import generate_lesson_package


def make_package(status: PackageStatus = PackageStatus.APPROVED):
    project = ProjectCreate(
        course_title="Generative AI Python Basics",
        lesson_title="Python functions and prompt automation practice",
        learner_profile="Job training learners with basic Python experience",
        learning_objectives=["Explain function inputs and return values."],
        ncs_units=[NCSUnit(unit_code="MVP-NCS-001", unit_name="AI basics", elements=[])],
    ).to_project(project_id="project-001")
    chunk = MaterialChunk(
        chunk_id="doc001-p000-c001",
        project_id=project.project_id,
        document_id="doc001",
        source_name="sample.pdf",
        source_type="pdf",
        page=None,
        text="A function can receive input and return output.",
        metadata={"license": "PSF License"},
    )
    package = generate_lesson_package(project=project, retrieved_chunks=[chunk])
    return package.model_copy(update={"status": status})


class ExportServiceTests(unittest.TestCase):
    def test_export_lesson_package_docx_writes_readable_document(self):
        package = make_package(PackageStatus.APPROVED)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "lesson_package.docx"

            result = export_lesson_package_docx(package=package, output_path=output_path)

            self.assertEqual(result, output_path)
            self.assertTrue(output_path.exists())
            doc = Document(str(output_path))
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
            self.assertIn("Python functions and prompt automation practice", text)
            self.assertIn("Practice", text)
            self.assertIn("Evidence Sources", text)

    def test_export_lesson_package_docx_rejects_unapproved_package(self):
        package = make_package(PackageStatus.DRAFT)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "draft.docx"

            with self.assertRaises(ValueError):
                export_lesson_package_docx(package=package, output_path=output_path)


if __name__ == "__main__":
    unittest.main()
