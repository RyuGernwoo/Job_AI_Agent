import unittest

from lectureops_agent.services.ncs_official_api import NCSOfficialAPIPage
from lectureops_agent.services.ncs_rag_chunk_builder import (
    build_official_ncs_chunks,
    canonicalize_ncs_record,
    criterion_patch,
)
from lectureops_agent.services.ncs_sync_service import (
    InMemoryNCSOfficialSyncStore,
    NCSOfficialSyncOptions,
    NCSOfficialSyncService,
)
from lectureops_agent.services.vector_store import InMemoryVectorStore


UNIT_PAYLOAD = {
    "ncsClCd": "2001020205_23v4",
    "dutyCd": "20010202",
    "dutySvcNo": "01",
    "compUnitCd": "05",
    "compUnitName": "Application software engineering",
    "compUnitDef": "Ability to develop application software.",
    "compUnitLevel": "5",
    "ncsLclasCdNm": "Information and communication",
    "ncsSubdCdNm": "Application software engineering",
}

KSA_PAYLOADS = [
    {
        **UNIT_PAYLOAD,
        "compUnitFactrNo": "1",
        "compUnitFactrName": "Confirm requirements",
        "performCrtrNo": "1.1",
        "performCrtr": "The requirements can be confirmed from work analysis.",
        "ksaType": "knowledge",
        "ksaNo": "K1",
        "ksaText": "Requirements engineering concepts",
    },
    {
        **UNIT_PAYLOAD,
        "compUnitFactrNo": "1",
        "compUnitFactrName": "Confirm requirements",
        "performCrtrNo": "1.1",
        "performCrtr": "The requirements can be confirmed from work analysis.",
        "ksaType": "skills",
        "ksaNo": "S1",
        "ksaText": "Requirements analysis skills",
    },
]

MODULE_ROW = {
    "module_id": "EDU-001",
    "module_name": "Application software engineering",
    "module_text": "Confirm requirements and develop application software.",
    "classification": {"sub_name": "Application software engineering"},
    "unit_code": None,
    "link_status": "unresolved",
    "source_url": "https://www.data.go.kr/data/15086442/openapi.do",
    "payload_hash": "hash",
    "fetched_at": "2026-07-23T00:00:00+00:00",
}


class FakeNCSAPIClient:
    def __init__(self, *, unit_items: tuple[dict[str, str], ...] | None = None) -> None:
        self.operations: list[str] = []
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.unit_items = unit_items or (UNIT_PAYLOAD,)

    def fetch_page(
        self,
        operation: str,
        *,
        page_no: int,
        page_size: int,
        params: dict[str, str] | None = None,
    ) -> NCSOfficialAPIPage:
        request_params = dict(params or {})
        self.operations.append(operation)
        self.requests.append((operation, request_params))
        if operation == "ncsCompeUnitInfo":
            items = self.unit_items
        elif operation == "ncsKsaInfo":
            self._assert_duty_params(request_params)
            items = tuple(KSA_PAYLOADS)
        else:
            items = ()
        return NCSOfficialAPIPage(
            operation=operation,
            page_no=page_no,
            page_size=page_size,
            total_count=len(items),
            total_pages=1,
            items=items,
        )

    @staticmethod
    def _assert_duty_params(params: dict[str, str]) -> None:
        if params.get("dutyCd") != UNIT_PAYLOAD["dutyCd"]:
            raise AssertionError("detail request must include the catalog dutyCd")


class NCSOfficialSyncTests(unittest.TestCase):
    def test_canonical_record_builds_official_rag_metadata(self):
        record = canonicalize_ncs_record(
            operation="ncsCompeUnitInfo",
            payload=UNIT_PAYLOAD,
        )

        chunks = build_official_ncs_chunks([record], project_id="mvp-dataset")

        self.assertEqual(record.unit_code, "2001020205_23v4")
        self.assertEqual(record.unit_name, "Application software engineering")
        self.assertEqual(record.catalog_version, "23v4")
        self.assertEqual(len(chunks[record.source_key]), 1)
        chunk = chunks[record.source_key][0]
        self.assertEqual(chunk.metadata["dataset"], "ncs_official_api")
        self.assertEqual(chunk.metadata["ncs_unit_code"], record.unit_code)
        self.assertEqual(chunk.metadata["content_scope"], "structured_detail")

    def test_actual_gbn_fields_map_performance_criterion_and_knowledge(self):
        criterion_record = canonicalize_ncs_record(
            operation="ncsKsaInfo",
            payload={
                **UNIT_PAYLOAD,
                "compUnitFactrNo": "1",
                "compUnitFactrName": "Confirm requirements",
                "gbnCd": "1.1",
                "gbnName": "\uc218\ud589\uc900\uac70",
                "gbnVal": "Requirements can be confirmed.",
            },
        )
        knowledge_record = canonicalize_ncs_record(
            operation="ncsKsaInfo",
            payload={
                **UNIT_PAYLOAD,
                "compUnitFactrNo": "1",
                "compUnitFactrName": "Confirm requirements",
                "gbnCd": "K1",
                "gbnName": "\uc9c0\uc2dd",
                "gbnVal": "Requirements engineering concepts",
            },
        )

        self.assertEqual(
            criterion_record.criterion_code,
            "2001020205_23v4:1:1.1",
        )
        self.assertEqual(
            criterion_record.criterion_text,
            "Requirements can be confirmed.",
        )
        self.assertIsNone(criterion_record.ksa_type)
        self.assertEqual(knowledge_record.ksa_type, "knowledge")
        self.assertEqual(
            knowledge_record.ksa_text,
            "Requirements engineering concepts",
        )

    def test_criterion_patch_uses_deterministic_code_and_ksa_type(self):
        record = canonicalize_ncs_record(
            operation="ncsKsaInfo",
            payload=KSA_PAYLOADS[0],
            position=1,
        )

        row = criterion_patch(record)

        assert row is not None
        self.assertEqual(
            row["criterion_code"],
            "2001020205_23v4:1:1.1",
        )
        self.assertEqual(row["knowledge"], ["Requirements engineering concepts"])
        self.assertEqual(row["skills"], [])

    def test_sync_is_idempotent_and_skips_unchanged_embeddings(self):
        api = FakeNCSAPIClient()
        store = InMemoryNCSOfficialSyncStore()
        vector_store = InMemoryVectorStore()
        service = NCSOfficialSyncService(
            api_client=api,  # type: ignore[arg-type]
            store=store,
            vector_store=vector_store,
        )
        options = NCSOfficialSyncOptions(
            mode="catalog",
            max_requests=10,
            embed=True,
        )

        first = service.sync(options)
        second = service.sync(options)

        self.assertEqual(first.status, "completed")
        self.assertEqual(first.catalog_upsert_count, 1)
        self.assertEqual(first.chunk_upsert_count, 1)
        self.assertEqual(second.changed_count, 0)
        self.assertEqual(second.chunk_upsert_count, 0)
        self.assertEqual(
            len(vector_store.list_chunks(project_id="mvp-dataset", limit=10)),
            1,
        )

    def test_detail_sync_uses_catalog_keys_and_merges_criteria(self):
        api = FakeNCSAPIClient()
        store = InMemoryNCSOfficialSyncStore()
        vector_store = InMemoryVectorStore()
        service = NCSOfficialSyncService(
            api_client=api,  # type: ignore[arg-type]
            store=store,
            vector_store=vector_store,
        )
        service.sync(NCSOfficialSyncOptions(mode="catalog", max_requests=10))

        report = service.sync(
            NCSOfficialSyncOptions(mode="detail", max_requests=20, embed=True)
        )

        self.assertEqual(report.criterion_upsert_count, 1)
        criterion = next(iter(store.criteria.values()))
        self.assertEqual(
            criterion["knowledge"],
            ["Requirements engineering concepts"],
        )
        self.assertEqual(criterion["skills"], ["Requirements analysis skills"])
        self.assertEqual(len(store.catalog["2001020205_23v4"]["criteria"]), 1)
        unit_requests = [
            params
            for operation, params in api.requests
            if operation in {
                "ncsScopeInfo",
                "ncsEvalInfo",
                "ncsjobInfo",
                "ncsCompeTrainInfo",
                "ncsSetqInfo",
            }
        ]
        self.assertTrue(unit_requests)
        self.assertTrue(
            all(
                params
                == {
                    "dutyCd": UNIT_PAYLOAD["dutyCd"],
                    "compUnitCd": UNIT_PAYLOAD["compUnitCd"],
                }
                for params in unit_requests
            )
        )

    def test_all_mode_discovers_detail_targets_after_catalog(self):
        api = FakeNCSAPIClient()
        store = InMemoryNCSOfficialSyncStore()
        service = NCSOfficialSyncService(
            api_client=api,  # type: ignore[arg-type]
            store=store,
            vector_store=None,
        )

        report = service.sync(
            NCSOfficialSyncOptions(mode="all", max_requests=50)
        )

        self.assertEqual(report.status, "completed")
        self.assertIn("ncsKsaInfo", api.operations)
        self.assertLess(
            api.operations.index("ncsCompeUnitInfo"),
            api.operations.index("ncsKsaInfo"),
        )
        self.assertEqual(report.criterion_upsert_count, 1)

    def test_detail_mode_requires_catalog_source_records(self):
        service = NCSOfficialSyncService(
            api_client=FakeNCSAPIClient(),  # type: ignore[arg-type]
            store=InMemoryNCSOfficialSyncStore(),
            vector_store=None,
        )

        with self.assertRaisesRegex(RuntimeError, "catalog synchronization"):
            service.sync(NCSOfficialSyncOptions(mode="detail"))

    def test_module_link_requires_matching_name_and_classification(self):
        store = InMemoryNCSOfficialSyncStore()
        store.catalog["2001020205_23v4"] = {
            "unit_code": "2001020205_23v4",
            "unit_name": "Application software engineering",
            "classification": {
                "sub_name": "Application software engineering"
            },
        }

        store.upsert_modules([MODULE_ROW])

        module = store.modules["EDU-001"]
        self.assertEqual(module["unit_code"], "2001020205_23v4")
        self.assertEqual(module["link_status"], "exact")

    def test_partial_run_resumes_at_next_target(self):
        api = FakeNCSAPIClient()
        store = InMemoryNCSOfficialSyncStore()
        service = NCSOfficialSyncService(
            api_client=api,  # type: ignore[arg-type]
            store=store,
            vector_store=None,
        )

        partial = service.sync(
            NCSOfficialSyncOptions(mode="catalog", max_requests=1)
        )
        resumed = service.sync(
            NCSOfficialSyncOptions(mode="catalog", max_requests=10, resume=True)
        )

        self.assertEqual(partial.status, "partial")
        self.assertEqual(
            partial.checkpoint["target_key"],
            "catalog:ncsDutyInfo",
        )
        self.assertEqual(resumed.status, "completed")
        self.assertEqual(api.operations.count("ncsCdInfo"), 1)
        self.assertIn("ncsCompeUnitInfo", api.operations)

    def test_complete_partition_deactivates_removed_source_and_old_chunks(self):
        removed_unit = {
            **UNIT_PAYLOAD,
            "ncsClCd": "2001020206_23v4",
            "compUnitCd": "06",
            "compUnitName": "Removed competency unit",
        }
        store = InMemoryNCSOfficialSyncStore()
        vector_store = InMemoryVectorStore()
        first_service = NCSOfficialSyncService(
            api_client=FakeNCSAPIClient(
                unit_items=(UNIT_PAYLOAD, removed_unit)
            ),  # type: ignore[arg-type]
            store=store,
            vector_store=vector_store,
        )
        second_service = NCSOfficialSyncService(
            api_client=FakeNCSAPIClient(
                unit_items=(UNIT_PAYLOAD,)
            ),  # type: ignore[arg-type]
            store=store,
            vector_store=vector_store,
        )
        options = NCSOfficialSyncOptions(
            mode="catalog",
            max_requests=10,
            embed=True,
        )

        first_service.sync(options)
        second = second_service.sync(options)

        removed_rows = [
            row
            for row in store.source_records.values()
            if row.get("unit_code") == "2001020206_23v4"
        ]
        self.assertEqual(len(removed_rows), 1)
        self.assertFalse(removed_rows[0]["active"])
        self.assertEqual(second.deleted_chunk_count, 1)
        self.assertEqual(len(store.deleted_chunk_ids), 1)


if __name__ == "__main__":
    unittest.main()
