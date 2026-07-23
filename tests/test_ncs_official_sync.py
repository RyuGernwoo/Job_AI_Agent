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
    def __init__(
        self,
        *,
        unit_items: tuple[dict[str, str], ...] | None = None,
        ksa_items: tuple[dict[str, str], ...] | None = None,
    ) -> None:
        self.operations: list[str] = []
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.unit_items = unit_items or (UNIT_PAYLOAD,)
        self.ksa_items = ksa_items or tuple(KSA_PAYLOADS)

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
            items = self.ksa_items
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
        service.sync(NCSOfficialSyncOptions(mode="catalog", max_requests=10))
        options = NCSOfficialSyncOptions(
            mode="detail",
            unit_code="LM2001020205_23v4",
            max_requests=10,
            embed=True,
        )

        first = service.sync(options)
        second = service.sync(options)

        self.assertEqual(first.status, "completed")
        self.assertGreater(first.chunk_upsert_count, 0)
        self.assertEqual(second.changed_count, 0)
        self.assertEqual(second.chunk_upsert_count, 0)
        self.assertGreater(
            len(vector_store.list_chunks(project_id="mvp-dataset", limit=10)),
            0,
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
            NCSOfficialSyncOptions(
                mode="detail",
                unit_code="2001020205_23v4",
                max_requests=20,
                embed=True,
            )
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

    def test_bulk_modes_and_catalog_embedding_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "catalog or detail"):
            NCSOfficialSyncOptions(mode="all")
        with self.assertRaisesRegex(ValueError, "must not embed"):
            NCSOfficialSyncOptions(mode="catalog", embed=True)

    def test_detail_mode_requires_selected_catalog_unit(self):
        service = NCSOfficialSyncService(
            api_client=FakeNCSAPIClient(),  # type: ignore[arg-type]
            store=InMemoryNCSOfficialSyncStore(),
            vector_store=InMemoryVectorStore(),
        )

        with self.assertRaisesRegex(RuntimeError, "not in the synchronized catalog"):
            service.sync(
                NCSOfficialSyncOptions(
                    mode="detail",
                    unit_code="2001020205_23v4",
                    embed=True,
                )
            )

    def test_detail_mode_blocks_new_unit_after_storage_cap(self):
        store = InMemoryNCSOfficialSyncStore()
        store.source_records["existing"] = {
            "unit_code": "2001020206_23v4",
            "active": True,
        }
        service = NCSOfficialSyncService(
            api_client=FakeNCSAPIClient(),  # type: ignore[arg-type]
            store=store,
            vector_store=InMemoryVectorStore(),
        )

        with self.assertRaisesRegex(RuntimeError, "unit limit reached"):
            service.sync(
                NCSOfficialSyncOptions(
                    mode="detail",
                    unit_code="2001020205_23v4",
                    embed=True,
                    max_selected_units=1,
                )
            )

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

    def test_catalog_uses_only_unit_api_without_raw_or_vector_storage(self):
        api = FakeNCSAPIClient()
        store = InMemoryNCSOfficialSyncStore()
        service = NCSOfficialSyncService(
            api_client=api,  # type: ignore[arg-type]
            store=store,
            vector_store=None,
        )

        report = service.sync(NCSOfficialSyncOptions(mode="catalog", max_requests=10))

        self.assertEqual(report.status, "completed")
        self.assertEqual(api.operations, ["ncsCompeUnitInfo"])
        self.assertEqual(report.chunk_upsert_count, 0)
        self.assertEqual(store.source_records, {})

    def test_duty_api_discards_records_for_unselected_units(self):
        other_unit = {
            **UNIT_PAYLOAD,
            "ncsClCd": "2001020206_23v4",
            "compUnitCd": "06",
            "compUnitName": "Other competency unit",
        }
        other_ksa = {
            **KSA_PAYLOADS[0],
            **other_unit,
            "performCrtrNo": "2.1",
            "performCrtr": "Unselected criterion.",
        }
        store = InMemoryNCSOfficialSyncStore()
        vector_store = InMemoryVectorStore()
        service = NCSOfficialSyncService(
            api_client=FakeNCSAPIClient(
                unit_items=(UNIT_PAYLOAD, other_unit),
                ksa_items=(*KSA_PAYLOADS, other_ksa),
            ),  # type: ignore[arg-type]
            store=store,
            vector_store=vector_store,
        )
        service.sync(NCSOfficialSyncOptions(mode="catalog", max_requests=10))
        report = service.sync(
            NCSOfficialSyncOptions(
                mode="detail",
                unit_code="2001020205_23v4",
                max_requests=20,
                embed=True,
            )
        )

        self.assertEqual(report.criterion_upsert_count, 1)
        self.assertTrue(
            all(
                row.get("unit_code") != "2001020206_23v4"
                for row in store.source_records.values()
            )
        )


if __name__ == "__main__":
    unittest.main()
