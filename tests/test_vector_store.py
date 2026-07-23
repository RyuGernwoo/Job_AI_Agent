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
    VectorSearchResult,
    _deduplicate_and_rank,
    _lexical_overlap,
    create_vector_store_from_config,
    create_vector_store_from_env,
    resolve_embedding_version,
)


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.upsert_failures: list[Exception] = []
        self.rpc_calls: list[dict] = []
        self.rpc_rows: list[dict] = []
        self.table_rows: list[dict] = []

    def table(self, table_name: str):
        return FakeSupabaseTable(self, table_name)

    def rpc(self, function_name: str, params: dict):
        self.rpc_calls.append({"function_name": function_name, "params": params})
        return FakeSupabaseRPC(self.rpc_rows)


class FakeSupabaseTable:
    def __init__(self, client: FakeSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.mode = ""
        self.filters: dict[str, object] = {}

    def upsert(self, rows: list[dict], *, on_conflict: str):
        self.mode = "upsert"
        self.client.upserts.append(
            {"table_name": self.table_name, "rows": rows, "on_conflict": on_conflict}
        )
        return self

    def select(self, columns: str):
        self.mode = "select"
        return self

    def eq(self, key: str, value: object):
        self.filters[key] = value
        return self

    def limit(self, count: int):
        self.limit_count = count
        return self

    def execute(self):
        if self.mode == "upsert" and self.client.upsert_failures:
            raise self.client.upsert_failures.pop(0)
        if self.mode == "select":
            rows = [
                row
                for row in self.client.table_rows
                if all(row.get(key) == value for key, value in self.filters.items())
            ]
            return SimpleNamespace(data=rows[: getattr(self, "limit_count", len(rows))])
        return SimpleNamespace(data=[])


class FakeSupabaseRPC:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def execute(self):
        return SimpleNamespace(data=self.rows)


class FixedEmbeddingProvider:
    name = "fixed:test"

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.dimensions = len(vector)

    def embed(self, *, text: str) -> list[float]:
        return list(self.vector)


class BatchEmbeddingProvider(FixedEmbeddingProvider):
    def __init__(self, vector: list[float]) -> None:
        super().__init__(vector)
        self.batch_calls: list[list[str]] = []

    def embed_many(self, *, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(texts)
        return [list(self.vector) for _ in texts]


class StatementTimeoutError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            {
                "message": "canceling statement due to statement timeout",
                "code": "57014",
            }
        )


def make_chunk(index: int) -> MaterialChunk:
    return MaterialChunk(
        chunk_id=f"doc001-c{index:03d}",
        project_id="project-001",
        document_id="doc001",
        source_name="sample.md",
        source_type="md",
        page=index,
        text=f"Semantic embedding sample {index}.",
        metadata={},
    )


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

    def test_resolve_embedding_version_defaults_from_column(self):
        self.assertEqual(resolve_embedding_version(embedding_column="embedding"), "v1")
        self.assertEqual(resolve_embedding_version(embedding_column="embedding_v2"), "v2")
        self.assertEqual(
            resolve_embedding_version(embedding_column="embedding_v2", configured_version="custom-v3"),
            "custom-v3",
        )

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
        self.assertEqual(row["embedding_version"], "v1")

    def test_supabase_vector_store_writes_semantic_embedding_version(self):
        client = FakeSupabaseClient()
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            embedding_provider=FixedEmbeddingProvider([0.1] * 1536),
            embedding_column="embedding_v2",
            embedding_version="v2",
            client=client,
        )
        chunk = MaterialChunk(
            chunk_id="doc001-p000-c001",
            project_id="project-001",
            document_id="doc001",
            source_name="sample.md",
            source_type="md",
            page=None,
            text="Semantic embedding sample.",
            metadata={},
        )

        store.upsert(project_id="project-001", chunks=[chunk])

        row = client.upserts[0]["rows"][0]
        self.assertEqual(len(row["embedding_v2"]), 1536)
        self.assertEqual(row["embedding_model"], "fixed:test")
        self.assertEqual(row["embedding_version"], "v2")

    def test_supabase_vector_store_embeds_upsert_rows_in_one_batch(self):
        client = FakeSupabaseClient()
        provider = BatchEmbeddingProvider([0.1] * 64)
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            embedding_provider=provider,
            client=client,
        )
        chunks = [
            MaterialChunk(
                chunk_id=f"doc001-c{index:03d}",
                project_id="project-001",
                document_id="doc001",
                source_name="sample.md",
                source_type="md",
                page=index,
                text=f"Semantic embedding sample {index}.",
                metadata={},
            )
            for index in range(1, 3)
        ]

        store.upsert(project_id="project-001", chunks=chunks)

        self.assertEqual(len(provider.batch_calls), 1)
        self.assertEqual(provider.batch_calls[0], [chunk.text for chunk in chunks])
        self.assertEqual(len(client.upserts[0]["rows"]), 2)

    def test_supabase_vector_store_retries_statement_timeout_before_splitting(self):
        client = FakeSupabaseClient()
        client.upsert_failures = [StatementTimeoutError()]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
            upsert_timeout_retries=1,
            upsert_timeout_retry_delay_seconds=0,
        )

        store.upsert(project_id="project-001", chunks=[make_chunk(1), make_chunk(2)])

        self.assertEqual([len(call["rows"]) for call in client.upserts], [2, 2])

    def test_supabase_vector_store_splits_batch_after_statement_timeout_retries(self):
        client = FakeSupabaseClient()
        client.upsert_failures = [StatementTimeoutError()]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
            upsert_timeout_retries=0,
            upsert_timeout_retry_delay_seconds=0,
        )

        store.upsert(
            project_id="project-001",
            chunks=[make_chunk(index) for index in range(1, 5)],
        )

        self.assertEqual([len(call["rows"]) for call in client.upserts], [4, 2, 2])

    def test_supabase_vector_store_rejects_wrong_v2_dimensions(self):
        with self.assertRaisesRegex(ValueError, "1536-dimensional"):
            SupabaseVectorStore(
                url="https://example.supabase.co",
                key="test-key",
                embedding_provider=FixedEmbeddingProvider([0.1, 0.2, 0.3]),
                embedding_column="embedding_v2",
                embedding_version="v2",
                client=FakeSupabaseClient(),
            )

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
        self.assertEqual(client.rpc_calls[0]["params"]["match_count"], 200)
        self.assertEqual(client.rpc_calls[0]["params"]["match_threshold"], 0.2)
        self.assertEqual([chunk.chunk_id for chunk in retrieved], ["doc001-p000-c001"])
        self.assertEqual(retrieved[0].metadata["license"], "PSF License")

    def test_supabase_vector_store_reranks_vector_candidates_with_hybrid_score(self):
        client = FakeSupabaseClient()
        client.rpc_rows = [
            {
                "chunk_id": "vector-first",
                "project_id": "project-001",
                "document_id": "doc001",
                "source_name": "sample.md",
                "source_type": "md",
                "page": None,
                "content": "Unrelated semantic result.",
                "metadata": {},
                "similarity": 0.91,
            },
            {
                "chunk_id": "hybrid-first",
                "project_id": "project-001",
                "document_id": "doc002",
                "source_name": "sample.md",
                "source_type": "md",
                "page": None,
                "content": "Functions return output.",
                "metadata": {},
                "similarity": 0.75,
            },
        ]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
        )

        retrieved = store.query(project_id="project-001", query="functions return output", top_k=1)

        self.assertEqual([chunk.chunk_id for chunk in retrieved], ["hybrid-first"])

    def test_supabase_vector_store_reserves_a_slot_for_best_lexical_candidate(self):
        client = FakeSupabaseClient()
        client.rpc_rows = [
            {
                "chunk_id": f"semantic-{index}",
                "project_id": "project-001",
                "document_id": f"doc{index:03d}",
                "source_name": "semantic.md",
                "source_type": "md",
                "page": None,
                "content": "Related material without the exact requested terms.",
                "metadata": {},
                "similarity": 0.95 - index * 0.01,
            }
            for index in range(3)
        ] + [
            {
                "chunk_id": "lexical-best",
                "project_id": "project-001",
                "document_id": "doc999",
                "source_name": "exact.md",
                "source_type": "md",
                "page": None,
                "content": "Python function text automation assessment criteria.",
                "metadata": {},
                "similarity": 0.2,
            }
        ]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
        )

        retrieved = store.query(
            project_id="project-001",
            query="Python function text automation assessment criteria",
            top_k=3,
        )

        self.assertEqual(len(retrieved), 3)
        self.assertIn("lexical-best", [chunk.chunk_id for chunk in retrieved])

    def test_scoped_ranking_preserves_best_lexical_candidate(self):
        semantic_results = [
            VectorSearchResult(
                chunk=make_chunk(index),
                vector_similarity=0.95 - index * 0.01,
                lexical_overlap=0.1,
                score=0.8 - index * 0.01,
            )
            for index in range(1, 4)
        ]
        lexical_result = VectorSearchResult(
            chunk=make_chunk(99),
            vector_similarity=0.2,
            lexical_overlap=1.0,
            score=0.5,
        )

        selected = _deduplicate_and_rank(
            project_candidates=[*semantic_results, lexical_result],
            baseline_candidates=[],
            top_k=3,
        )

        self.assertEqual(len(selected), 3)
        self.assertIn("doc001-c099", [result.chunk.chunk_id for result in selected])

    def test_in_memory_scoped_query_prioritizes_project_evidence(self):
        store = InMemoryVectorStore()
        project_chunk = MaterialChunk(
            chunk_id="project-c001",
            project_id="project-001",
            document_id="doc001",
            source_name="instructor.md",
            source_type="md",
            page=None,
            text="Functions receive input and return output.",
            metadata={},
        )
        baseline_chunk = project_chunk.model_copy(
            update={
                "chunk_id": "baseline-c001",
                "project_id": "mvp-dataset",
                "source_name": "baseline.md",
            }
        )
        store.upsert(project_id="project-001", chunks=[project_chunk])
        store.upsert(project_id="mvp-dataset", chunks=[baseline_chunk])

        results = store.query_scoped(
            project_id="project-001",
            baseline_project_id="mvp-dataset",
            query="function return output",
            top_k=2,
            candidate_k=5,
            include_baseline=True,
        )

        self.assertEqual([item.scope for item in results], ["project"])

    def test_scoped_query_falls_back_to_uploaded_project_material_without_term_match(self):
        store = InMemoryVectorStore()
        uploaded_chunk = MaterialChunk(
            chunk_id="custom-field-c001",
            project_id="project-custom",
            document_id="custom-doc",
            source_name="institution-guide.md",
            source_type="md",
            page=None,
            text="토치 각도와 보호 가스 유량을 기록하고 시편 상태를 관찰한다.",
            metadata={
                "evidence_origin": "user_upload",
                "evidence_authority": "user_provided",
            },
        )
        store.upsert(project_id="project-custom", chunks=[uploaded_chunk])
        store.upsert(
            project_id="mvp-dataset",
            chunks=[
                MaterialChunk(
                    chunk_id="generic-baseline-c001",
                    project_id="mvp-dataset",
                    document_id="baseline-doc",
                    source_name="generic-ncs.md",
                    source_type="md",
                    page=None,
                    text="NCS 일반 안내",
                    metadata={},
                )
            ],
        )
        store.upsert(
            project_id="mvp-dataset",
            chunks=[
                MaterialChunk(
                    chunk_id="unrelated-baseline-c001",
                    project_id="mvp-dataset",
                    document_id="baseline-doc",
                    source_name="common-baseline.md",
                    source_type="md",
                    page=None,
                    text="공통 데이터셋에 존재하지 않는 완전히 다른 능력단위",
                    metadata={},
                )
            ],
        )

        results = store.query_scoped(
            project_id="project-custom",
            baseline_project_id="mvp-dataset",
            query="공통 데이터셋에 존재하지 않는 완전히 다른 능력단위",
            top_k=5,
            candidate_k=10,
            include_baseline=True,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.chunk_id, "custom-field-c001")
        self.assertEqual(results[0].scope, "project")
        self.assertEqual(results[0].strategy, "project_material_fallback")
        self.assertEqual(results[0].chunk.metadata["evidence_origin"], "user_upload")
        self.assertEqual(
            results[0].chunk.metadata["retrieval_strategy"],
            "project_material_fallback",
        )

    def test_scoped_query_uses_project_material_when_baseline_lookup_fails(self):
        class BaselineFailingStore(InMemoryVectorStore):
            def query_with_scores(self, *, project_id: str, query: str, top_k: int):
                if project_id == "mvp-dataset":
                    raise RuntimeError("baseline unavailable")
                return super().query_with_scores(project_id=project_id, query=query, top_k=top_k)

        store = BaselineFailingStore()
        store.upsert(
            project_id="project-001",
            chunks=[
                MaterialChunk(
                    chunk_id="project-c001",
                    project_id="project-001",
                    document_id="doc001",
                    source_name="uploaded.md",
                    source_type="md",
                    page=None,
                    text="현장 점검 절차와 수행 순서를 설명한다.",
                    metadata={"evidence_origin": "user_upload"},
                )
            ],
        )

        results = store.query_scoped(
            project_id="project-001",
            baseline_project_id="mvp-dataset",
            query="현장 점검 수행 순서",
            top_k=3,
            candidate_k=5,
            include_baseline=True,
        )

        self.assertEqual([item.chunk.chunk_id for item in results], ["project-c001"])
        self.assertEqual(results[0].scope, "project")

    def test_vector_lexical_overlap_expands_korean_domain_synonyms(self):
        chunk = MaterialChunk(
            chunk_id="python-functions-c001",
            project_id="mvp-dataset",
            document_id="python-functions",
            source_name="Python Functions",
            source_type="md",
            page=None,
            text="Define a function and assess it with a rubric.",
            metadata={"tags": ["function", "assessment"]},
        )

        score = _lexical_overlap("Python 함수 객관식 평가", chunk)

        self.assertGreaterEqual(score, 0.5)

    def test_supabase_query_falls_back_to_exact_project_scan_when_rpc_is_empty(self):
        client = FakeSupabaseClient()
        client.table_rows = [
            {
                "chunk_id": "baseline-c001",
                "project_id": "mvp-dataset",
                "document_id": "baseline-doc",
                "source_name": "baseline.md",
                "source_type": "md",
                "page": None,
                "content": "Functions receive input and return output.",
                "metadata": {"license": "PSF License"},
                "embedding": [0.0] * 63 + [1.0],
            }
        ]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
            embedding_provider=FixedEmbeddingProvider([0.0] * 63 + [1.0]),
        )

        retrieved = store.query(project_id="mvp-dataset", query="function return", top_k=3)

        self.assertEqual([chunk.chunk_id for chunk in retrieved], ["baseline-c001"])

    def test_supabase_scoped_query_uses_raw_project_chunks_when_vector_match_is_empty(self):
        client = FakeSupabaseClient()
        client.table_rows = [
            {
                "chunk_id": "custom-project-c001",
                "project_id": "project-custom",
                "document_id": "custom-doc",
                "source_name": "uploaded-guide.md",
                "source_type": "md",
                "page": None,
                "content": "사용자가 업로드한 신규 직무 분야의 수행 절차다.",
                "metadata": {
                    "evidence_origin": "user_upload",
                    "evidence_authority": "user_provided",
                },
            }
        ]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
        )

        results = store.query_scoped(
            project_id="project-custom",
            baseline_project_id="mvp-dataset",
            query="등록되지 않은 NCS 능력단위",
            top_k=3,
            candidate_k=5,
            include_baseline=False,
        )

        self.assertEqual([item.chunk.chunk_id for item in results], ["custom-project-c001"])
        self.assertEqual(results[0].strategy, "project_material_fallback")
        self.assertEqual(results[0].chunk.metadata["evidence_origin"], "user_upload")

    def test_supabase_lists_project_chunks_without_requiring_embeddings(self):
        client = FakeSupabaseClient()
        client.table_rows = [
            {
                "chunk_id": "uploaded-c001",
                "project_id": "project-001",
                "document_id": "uploaded-doc",
                "source_name": "custom-guide.md",
                "source_type": "md",
                "page": None,
                "content": "사용자가 업로드한 신규 분야 근거",
                "metadata": {"evidence_origin": "user_upload"},
            }
        ]
        store = SupabaseVectorStore(
            url="https://example.supabase.co",
            key="test-key",
            client=client,
        )

        chunks = store.list_chunks(project_id="project-001", limit=5)

        self.assertEqual([chunk.chunk_id for chunk in chunks], ["uploaded-c001"])
        self.assertEqual(chunks[0].metadata["evidence_origin"], "user_upload")


if __name__ == "__main__":
    unittest.main()
