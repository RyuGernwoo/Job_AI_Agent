import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.models.schemas import NCSUnit, PackageStatus, ProjectCreate
from lectureops_agent.ui.workflow import approve_package, parse_multiline_items, run_text_material_workflow


class UiWorkflowTests(unittest.TestCase):
    def test_parse_multiline_items_removes_blank_lines_and_whitespace(self):
        items = parse_multiline_items("  first objective\n\nsecond objective  \n")

        self.assertEqual(items, ["first objective", "second objective"])

    def test_run_text_material_workflow_generates_draft_package_from_text(self):
        project = ProjectCreate(
            course_title="Generative AI Python Basics",
            lesson_title="Function practice",
            learner_profile="Job training learners",
            learning_objectives=["Explain function return values."],
            ncs_units=[NCSUnit(unit_code="MVP-NCS-001", unit_name="AI basics", elements=[])],
        )

        result = run_text_material_workflow(
            project_input=project,
            material_name="sample.md",
            source_type="md",
            text="Functions receive input and return output.\n" * 20,
            retrieval_query="return output",
            top_k=2,
        )

        self.assertEqual(result.package.status, PackageStatus.DRAFT)
        self.assertGreaterEqual(len(result.chunks), 1)
        self.assertGreaterEqual(len(result.retrieved_chunks), 1)
        self.assertEqual(result.package.project_id, result.project.project_id)
        self.assertIn(result.retrieved_chunks[0].chunk_id, result.package.practice.citation_ids)

    def test_approve_package_sets_approved_status(self):
        project = ProjectCreate(
            course_title="Generative AI Python Basics",
            lesson_title="Function practice",
            learner_profile="Job training learners",
            learning_objectives=["Explain function return values."],
            ncs_units=[],
        )
        result = run_text_material_workflow(
            project_input=project,
            material_name="sample.md",
            source_type="md",
            text="Functions receive input and return output.",
            retrieval_query="return output",
            top_k=1,
        )

        approved = approve_package(result.package)

        self.assertEqual(approved.status, PackageStatus.APPROVED)


if __name__ == "__main__":
    unittest.main()
