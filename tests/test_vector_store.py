import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.vector_store import InMemoryVectorStore


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


if __name__ == "__main__":
    unittest.main()
