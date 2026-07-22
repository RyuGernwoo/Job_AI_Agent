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
        self.assertIn("using hnsw (embedding_v2 vector_cosine_ops)", sql)
        self.assertIn("language plpgsql", sql)
        self.assertIn("return query execute", sql)
        self.assertNotIn("set enable_indexscan = off", sql)

    def test_vector_performance_migration_restores_custom_hnsw_queries(self):
        sql = (
            ROOT / "supabase" / "migrations" / "004_vector_search_performance.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("lessonpack_chunks_embedding_v2_hnsw_idx", sql)
        self.assertIn("using hnsw (embedding_v2 vector_cosine_ops)", sql)
        self.assertIn("language plpgsql", sql)
        self.assertIn("return query execute", sql)
        self.assertIn("analyze public.lessonpack_chunks", sql)
        self.assertNotIn("set enable_indexscan = off", sql)

    def test_training_plan_migration_adds_project_fields_and_constraints(self):
        sql = (ROOT / "supabase" / "migrations" / "003_training_plan_fields.sql").read_text(
            encoding="utf-8"
        )

        for column_name in (
            "total_training_hours",
            "total_lessons",
            "theory_ratio_percent",
            "practice_ratio_percent",
        ):
            self.assertIn(column_name, sql)
        self.assertIn("theory_ratio_percent + practice_ratio_percent = 100", sql)
        self.assertIn("total_training_hours * 60 / total_lessons >= 15", sql)


if __name__ == "__main__":
    unittest.main()
