import os
import sys
import tempfile
import warnings
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

warnings.filterwarnings("ignore", message=r".*asyncio\.iscoroutinefunction.*", category=DeprecationWarning)

from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.vector_store import ChromaVectorStore, InMemoryVectorStore, create_vector_store_from_env


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

    def test_create_vector_store_from_env_defaults_to_memory(self):
        with patch.dict(os.environ, {}, clear=True):
            store = create_vector_store_from_env()

        self.assertIsInstance(store, InMemoryVectorStore)

    def test_create_vector_store_from_env_creates_chroma_store(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "LECTUREOPS_VECTOR_STORE": "chroma",
                    "LECTUREOPS_CHROMA_PATH": str(Path(tmpdir) / "chroma"),
                    "LECTUREOPS_CHROMA_COLLECTION": "env_chunks",
                },
                clear=False,
            ):
                store = create_vector_store_from_env()
            try:
                self.assertIsInstance(store, ChromaVectorStore)
            finally:
                store.close()

    def test_create_vector_store_from_env_requires_explicit_chroma_settings(self):
        with patch.dict(os.environ, {"LECTUREOPS_VECTOR_STORE": "chroma"}, clear=True):
            with self.assertRaisesRegex(ValueError, "LECTUREOPS_CHROMA_PATH"):
                create_vector_store_from_env()

    def test_chroma_vector_store_persists_and_queries_chunks(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            persist_path = Path(tmpdir) / "chroma"
            store = ChromaVectorStore(persist_path=str(persist_path), collection_name="test_chunks")
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
                    project_id="project-002",
                    document_id="doc001",
                    source_name="sample.md",
                    source_type="md",
                    page=None,
                    text="Unrelated project text about loops.",
                    metadata={},
                ),
            ]

            store.upsert(project_id="project-001", chunks=[chunks[0]])
            store.upsert(project_id="project-002", chunks=[chunks[1]])
            store.close()

            reopened = ChromaVectorStore(persist_path=str(persist_path), collection_name="test_chunks")
            try:
                retrieved = reopened.query(project_id="project-001", query="return output", top_k=3)
            finally:
                reopened.close()

            self.assertEqual([chunk.chunk_id for chunk in retrieved], ["doc001-p000-c001"])
            self.assertEqual(retrieved[0].metadata["license"], "PSF License")

    def test_chroma_vector_store_keeps_internal_metadata_keys_authoritative(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            persist_path = Path(tmpdir) / "chroma"
            store = ChromaVectorStore(persist_path=str(persist_path), collection_name="metadata_chunks")
            chunk = MaterialChunk(
                chunk_id="doc001-p000-c001",
                project_id="project-001",
                document_id="doc001",
                source_name="sample.md",
                source_type="md",
                page=None,
                text="Functions receive input and return output.",
                metadata={"project_id": "project-002", "page": 99, "license": "PSF License"},
            )

            try:
                store.upsert(project_id="project-001", chunks=[chunk])
                retrieved = store.query(project_id="project-001", query="return output", top_k=1)
            finally:
                store.close()

            self.assertEqual([chunk.chunk_id for chunk in retrieved], ["doc001-p000-c001"])
            self.assertIsNone(retrieved[0].page)
            self.assertNotIn("project_id", retrieved[0].metadata)
            self.assertNotIn("page", retrieved[0].metadata)
            self.assertEqual(retrieved[0].metadata["license"], "PSF License")


if __name__ == "__main__":
    unittest.main()
