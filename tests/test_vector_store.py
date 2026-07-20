import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.config import VectorStoreConfig
from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.vector_store import (
    InMemoryVectorStore,
    SupabaseVectorStore,
    create_vector_store_from_config,
    create_vector_store_from_env,
)


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.rpc_calls: list[dict] = []
        self.rpc_rows: list[dict] = []

    def table(self, table_name: str):
        return FakeSupabaseTable(self, table_name)

    def rpc(self, function_name: str, params: dict):
        self.rpc_calls.append({"function_name": function_name, "params": params})
        return FakeSupabaseRPC(self.rpc_rows)


class FakeSupabaseTable:
    def __init__(self, client: FakeSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name

    def upsert(self, rows: list[dict], *, on_conflict: str):
        self.client.upserts.append(
            {"table_name": self.table_name, "rows": rows, "on_conflict": on_conflict}
        )
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class FakeSupabaseRPC:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def execute(self):
        return SimpleNamespace(data=self.rows)


class VectorStoreTests(unittest.TestCase):
    def test_in_memory_vector_store_upserts_and_queries_chunks(self):
        store = InMemoryVectorStore()
        chunks = [
            MaterialChunk(
                chunk_id="doc001-p000-c001",
                project_id="project-001",
                document_id="doc001",
                source_name="sample.md",
                source_type="md",
                page=None,
                text="Functions receive input and return output.",
                metadata={"license": "PSF License"},
            ),
            MaterialChunk(
                chunk_id="doc001-p000-c002",
                project_id="project-001",
                document_id="doc001",
                source_name="sample.md",
                source_type="md",
                page=None,
                text="Loops repeat tasks while a condition is true.",
                metadata={"license": "PSF License"},
            ),
        ]

        store.upsert(project_id="project-001", chunks=chunks)
        retrieved = store.query(project_id="project-001", query="return output", top_k=1)

        self.assertEqual([chunk.chunk_id for chunk in retrieved], ["doc001-p000-c001"])

    def test_in_memory_vector_store_replaces_duplicate_chunk_ids(self):
        store = InMemoryVectorStore()
        original = MaterialChunk(
            chunk_id="doc001-p000-c001",
            project_id="project-001",
            document_id="doc001",
            source_name="sample.md",
            source_type="md",
            page=None,
            text="Old text",
            metadata={},
        )
        updated = original.model_copy(update={"text": "Updated return output text"})

        store.upsert(project_id="project-001", chunks=[original])
        store.upsert(project_id="project-001", chunks=[updated])
        retrieved = store.query(project_id="project-001", query="updated", top_k=5)

        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].text, "Updated return output text")

    def test_create_vector_store_from_config_uses_memory_provider(self):
        store = create_vector_store_from_config(VectorStoreConfig(provider="memory"))

        self.assertIsInstance(store, InMemoryVectorStore)

    def test_create_vector_store_from_config_requires_supabase_url(self):
        config = VectorStoreConfig(provider="supabase")

        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": "test-key"}, clear=True):
            with self.assertRaisesRegex(ValueError, "SUPABASE_URL"):
                create_vector_store_from_config(config)

    def test_create_vector_store_from_env_defaults_to_memory(self):
        with patch.dict(
            os.environ,
            {"LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env"), "LECTUREOPS_VECTOR_STORE": "memory"},
            clear=False,
        ):
            store = create_vector_store_from_env()

        self.assertIsInstance(store, InMemoryVectorStore)

    def test_create_vector_store_from_env_requires_supabase_key(self):
        with patch.dict(
            os.environ,
            {
                "LESSONPACK_ENV_FILE": str(ROOT / "missing-test.env"),
                "LECTUREOPS_VECTOR_STORE": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "SUPABASE_SERVICE_ROLE_KEY"):
                create_vector_store_from_env()

    def test_supabase_vector_store_upserts_chunks_as_rows(self):
        client = FakeSupabaseClient()
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            table_name="lessonpack_chunks",
            match_function="match_lessonpack_chunks",
            client=client,
        )
        chunk = MaterialChunk(
            chunk_id="doc001-p000-c001",
            project_id="project-001",
            document_id="doc001",
            source_name="sample.md",
            source_type="md",
            page=None,
            text="Functions receive input and return output.",
            metadata={"project_id": "wrong", "license": "PSF License"},
        )

        store.upsert(project_id="project-001", chunks=[chunk])

        self.assertEqual(client.upserts[0]["table_name"], "lessonpack_chunks")
        self.assertEqual(client.upserts[0]["on_conflict"], "chunk_id")
        row = client.upserts[0]["rows"][0]
        self.assertEqual(row["chunk_id"], "doc001-p000-c001")
        self.assertEqual(row["project_id"], "project-001")
        self.assertEqual(row["content"], "Functions receive input and return output.")
        self.assertEqual(row["metadata"], {"license": "PSF License"})
        self.assertEqual(len(row["embedding"]), 64)

    def test_supabase_vector_store_queries_rpc_and_maps_rows(self):
        client = FakeSupabaseClient()
        client.rpc_rows = [
            {
                "chunk_id": "doc001-p000-c001",
                "project_id": "project-001",
                "document_id": "doc001",
                "source_name": "sample.md",
                "source_type": "md",
                "page": None,
                "content": "Functions receive input and return output.",
                "metadata": {"license": "PSF License"},
                "similarity": 0.91,
            }
        ]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            table_name="lessonpack_chunks",
            match_function="match_lessonpack_chunks",
            match_threshold=0.2,
            client=client,
        )

        retrieved = store.query(project_id="project-001", query="return output", top_k=3)

        self.assertEqual(client.rpc_calls[0]["function_name"], "match_lessonpack_chunks")
        self.assertEqual(client.rpc_calls[0]["params"]["match_project_id"], "project-001")
        self.assertEqual(client.rpc_calls[0]["params"]["match_count"], 3)
        self.assertEqual(client.rpc_calls[0]["params"]["match_threshold"], 0.2)
        self.assertEqual([chunk.chunk_id for chunk in retrieved], ["doc001-p000-c001"])
        self.assertEqual(retrieved[0].metadata["license"], "PSF License")


if __name__ == "__main__":
    unittest.main()
