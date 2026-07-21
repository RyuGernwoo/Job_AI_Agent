import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SupabaseMigrationTests(unittest.TestCase):
    def test_rag_persistence_migration_contains_required_contracts(self):
        sql = (ROOT / "supabase" / "migrations" / "002_rag_persistence.sql").read_text(
            encoding="utf-8"
        )

        for table_name in (
            "lessonpack_projects",
            "lessonpack_documents",
            "lessonpack_retrieval_runs",
            "lessonpack_generation_runs",
        ):
            self.assertIn(f"public.{table_name}", sql)
        self.assertIn("match_lessonpack_chunks_v2", sql)
        self.assertIn("embedding_v2 extensions.vector(1536)", sql)
        self.assertIn("alter column embedding drop not null", sql)
        self.assertIn("set enable_indexscan = off", sql)


if __name__ == "__main__":
    unittest.main()
