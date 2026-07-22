import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.models.schemas import (
    MaterialChunk,
    NCSUnit,
    ProjectCreate,
    RetrievedEvidence,
    RetrievalRun,
)
from lectureops_agent.services.rag_repository import SupabaseRAGRepository


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = {}

    def table(self, table_name: str):
        return FakeTable(self, table_name)


class FakeTable:
    def __init__(self, client: FakeSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: dict[str, object] = {}
        self.pending_row: dict | None = None

    def upsert(self, row: dict, *, on_conflict: str):
        self.pending_row = row
        self.on_conflict = on_conflict
        return self

    def select(self, columns: str):
        return self

    def eq(self, key: str, value: object):
        self.filters[key] = value
        return self

    def limit(self, count: int):
        self.limit_count = count
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.table_name, [])
        if self.pending_row is not None:
            conflict_value = self.pending_row[self.on_conflict]
            rows[:] = [row for row in rows if row.get(self.on_conflict) != conflict_value]
            rows.append(self.pending_row)
            return SimpleNamespace(data=[self.pending_row])
        selected = [
            row for row in rows if all(row.get(key) == value for key, value in self.filters.items())
        ]
        return SimpleNamespace(data=selected[: getattr(self, "limit_count", len(selected))])


class RAGRepositoryTests(unittest.TestCase):
    def test_supabase_repository_round_trips_project_and_retrieval_run(self):
        client = FakeSupabaseClient()
        repository = SupabaseRAGRepository(client=client)
        project = ProjectCreate(
            course_title="Python",
            lesson_title="Functions",
            learner_profile="Beginners",
            total_training_hours=8,
            total_lessons=4,
            theory_ratio_percent=35,
            practice_ratio_percent=65,
            learning_objectives=["Explain return values."],
            ncs_units=[NCSUnit(unit_code="NCS-001", unit_name="Programming")],
            retrieval_queries=["function inputs", "return values"],
        ).to_project(project_id="project-001")
        repository.save_project(project)

        loaded_project = repository.get_project("project-001")

        self.assertEqual(loaded_project, project)
        chunk = MaterialChunk(
            chunk_id="chunk-001",
            project_id="project-001",
            document_id="doc001",
            source_name="sample.md",
            source_type="md",
            page=None,
            text="Functions return output.",
            metadata={"license": "PSF License"},
        )
        run = RetrievalRun(
            run_id="run-001",
            trace_id="0123456789abcdef0123456789abcdef",
            project_id="project-001",
            query="function return",
            normalized_query="function return Python Functions",
            evidence=[
                RetrievedEvidence(
                    chunk=chunk,
                    score=0.9,
                    vector_similarity=0.9,
                    lexical_overlap=0.5,
                    scope="project",
                )
            ],
            created_at=datetime.now(timezone.utc),
        )
        repository.save_retrieval_run(run)

        loaded_run = repository.get_retrieval_run("run-001")

        self.assertEqual(loaded_run, run)


if __name__ == "__main__":
    unittest.main()
