from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
from uuid import uuid4

from lectureops_agent.models.schemas import MaterialChunk, normalize_ncs_unit_code
from lectureops_agent.services.ncs_official_api import (
    NCSOfficialAPIClient,
)
from lectureops_agent.services.ncs_rag_chunk_builder import (
    CanonicalNCSRecord,
    build_official_ncs_chunks,
    canonicalize_ncs_record,
    catalog_patch,
    criterion_patch,
    module_patch,
    source_record_row,
)
from lectureops_agent.services.vector_store import VectorStore


logger = logging.getLogger(__name__)

_CATALOG_OPERATIONS = ("ncsCompeUnitInfo",)
_SELECTIVE_DUTY_OPERATIONS = ("ncsKsaInfo",)
_SELECTIVE_UNIT_OPERATIONS = (
    "ncsScopeInfo",
    "ncsEvalInfo",
    "ncsCompeTrainInfo",
    "ncsSetqInfo",
)


@dataclass(frozen=True)
class SourceRecordState:
    payload_hash: str
    embedded_payload_hash: str | None = None
    chunk_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncTarget:
    key: str
    operation: str
    params: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    selected_unit_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NCSOfficialSyncOptions:
    mode: str = "catalog"
    page_size: int = 100
    max_requests: int = 5000
    record_limit: int | None = None
    unit_code: str | None = None
    resume: bool = False
    embed: bool = False
    dry_run: bool = False
    embedding_batch_size: int = 8
    max_selected_units: int = 50

    def __post_init__(self) -> None:
        if self.mode not in {"catalog", "detail"}:
            raise ValueError("mode must be catalog or detail")
        if self.page_size <= 0:
            raise ValueError("page_size must be greater than 0")
        if self.max_requests <= 0:
            raise ValueError("max_requests must be greater than 0")
        if self.record_limit is not None and self.record_limit <= 0:
            raise ValueError("record_limit must be greater than 0")
        if self.embedding_batch_size <= 0:
            raise ValueError("embedding_batch_size must be greater than 0")
        if self.max_selected_units <= 0:
            raise ValueError("max_selected_units must be greater than 0")
        normalized_unit_code = (
            normalize_ncs_unit_code(self.unit_code) if self.unit_code else None
        )
        object.__setattr__(self, "unit_code", normalized_unit_code)
        if self.mode == "catalog" and self.embed:
            raise ValueError(
                "catalog synchronization must not embed records; "
                "use detail mode with --unit-code"
            )
        if self.mode == "detail" and not normalized_unit_code:
            raise ValueError("detail mode requires a specific unit_code")
        if self.mode == "detail" and not self.embed and not self.dry_run:
            raise ValueError("detail mode must embed records outside dry-run")


@dataclass
class NCSOfficialSyncReport:
    run_id: str
    mode: str
    status: str = "running"
    request_count: int = 0
    received_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    catalog_upsert_count: int = 0
    criterion_upsert_count: int = 0
    module_upsert_count: int = 0
    chunk_upsert_count: int = 0
    deleted_chunk_count: int = 0
    checkpoint: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    dry_run: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class NCSOfficialSyncStore(Protocol):
    def start_run(self, report: NCSOfficialSyncReport) -> None:
        ...

    def finish_run(
        self,
        report: NCSOfficialSyncReport,
        *,
        error_summary: str | None = None,
    ) -> None:
        ...

    def update_checkpoint(
        self,
        run_id: str,
        *,
        checkpoint: dict[str, Any],
        report: NCSOfficialSyncReport,
    ) -> None:
        ...

    def latest_checkpoint(self, mode: str) -> dict[str, Any] | None:
        ...

    def get_source_states(
        self, source_keys: list[str]
    ) -> dict[str, SourceRecordState]:
        ...

    def list_unit_targets(
        self, unit_code: str | None = None
    ) -> list[dict[str, Any]]:
        ...

    def list_selected_unit_codes(self) -> set[str]:
        ...

    def upsert_source_records(self, rows: list[dict[str, Any]]) -> None:
        ...

    def upsert_catalog(self, rows: list[dict[str, Any]]) -> None:
        ...

    def merge_criteria(self, rows: list[dict[str, Any]]) -> None:
        ...

    def upsert_modules(self, rows: list[dict[str, Any]]) -> None:
        ...

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        ...

    def deactivate_missing(
        self,
        *,
        partition_key: str,
        seen_source_keys: set[str],
        run_id: str,
    ) -> list[str]:
        ...


class InMemoryNCSOfficialSyncStore:
    def __init__(self) -> None:
        self.source_records: dict[str, dict[str, Any]] = {}
        self.catalog: dict[str, dict[str, Any]] = {}
        self.criteria: dict[str, dict[str, Any]] = {}
        self.modules: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.deleted_chunk_ids: list[str] = []

    def start_run(self, report: NCSOfficialSyncReport) -> None:
        self.runs[report.run_id] = report.model_dump()

    def finish_run(
        self,
        report: NCSOfficialSyncReport,
        *,
        error_summary: str | None = None,
    ) -> None:
        self.runs[report.run_id] = {
            **report.model_dump(),
            "error_summary": error_summary,
        }

    def update_checkpoint(
        self,
        run_id: str,
        *,
        checkpoint: dict[str, Any],
        report: NCSOfficialSyncReport,
    ) -> None:
        self.runs[run_id] = report.model_dump()

    def latest_checkpoint(self, mode: str) -> dict[str, Any] | None:
        candidates = [
            run
            for run in self.runs.values()
            if run["mode"] == mode and run["status"] in {"partial", "failed", "running"}
        ]
        return dict(candidates[-1].get("checkpoint") or {}) if candidates else None

    def get_source_states(
        self, source_keys: list[str]
    ) -> dict[str, SourceRecordState]:
        return {
            key: SourceRecordState(
                payload_hash=str(row["payload_hash"]),
                embedded_payload_hash=row.get("embedded_payload_hash"),
                chunk_ids=tuple(row.get("chunk_ids") or ()),
            )
            for key in source_keys
            if (row := self.source_records.get(key)) is not None
        }

    def list_unit_targets(
        self, unit_code: str | None = None
    ) -> list[dict[str, Any]]:
        return _unit_targets_from_catalog_rows(
            self.catalog.values(),
            unit_code=unit_code,
        )

    def list_selected_unit_codes(self) -> set[str]:
        return {
            normalize_ncs_unit_code(str(row["unit_code"]))
            for row in self.source_records.values()
            if row.get("active", True) and row.get("unit_code")
        }

    def upsert_source_records(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.source_records[str(row["source_key"])] = dict(row)

    def upsert_catalog(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            code = str(row["unit_code"])
            self.catalog[code] = {**self.catalog.get(code, {}), **row}

    def merge_criteria(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            code = str(row["criterion_code"])
            self.criteria[code] = _merge_criterion_rows(
                self.criteria.get(code),
                row,
            )
        for unit_code in {str(row["unit_code"]) for row in rows}:
            criteria = [
                _catalog_criterion(row)
                for row in self.criteria.values()
                if row["unit_code"] == unit_code
            ]
            self.catalog.setdefault(unit_code, {"unit_code": unit_code})["criteria"] = criteria

    def upsert_modules(self, rows: list[dict[str, Any]]) -> None:
        linked_rows = _link_module_rows(rows, list(self.catalog.values()))
        for row in linked_rows:
            self.modules[str(row["module_id"])] = dict(row)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        self.deleted_chunk_ids.extend(chunk_ids)

    def deactivate_missing(
        self,
        *,
        partition_key: str,
        seen_source_keys: set[str],
        run_id: str,
    ) -> list[str]:
        stale_rows = [
            row
            for row in self.source_records.values()
            if row.get("partition_key") == partition_key
            and row.get("active", True)
            and row["source_key"] not in seen_source_keys
        ]
        for row in stale_rows:
            row["active"] = False
            row["last_run_id"] = run_id
        return [
            str(chunk_id)
            for row in stale_rows
            for chunk_id in (row.get("chunk_ids") or [])
        ]


class SupabaseNCSOfficialSyncStore:
    def __init__(
        self,
        *,
        client: Any,
        source_table: str = "lessonpack_ncs_source_records",
        run_table: str = "lessonpack_ncs_sync_runs",
        module_table: str = "lessonpack_ncs_modules",
        catalog_table: str = "lessonpack_ncs_catalog",
        criteria_table: str = "lessonpack_ncs_criteria",
        chunk_table: str = "lessonpack_chunks",
    ) -> None:
        self.client = client
        self.source_table = source_table
        self.run_table = run_table
        self.module_table = module_table
        self.catalog_table = catalog_table
        self.criteria_table = criteria_table
        self.chunk_table = chunk_table

    def start_run(self, report: NCSOfficialSyncReport) -> None:
        row = _run_row(report)
        _execute(self.client.table(self.run_table).insert(row).execute())

    def finish_run(
        self,
        report: NCSOfficialSyncReport,
        *,
        error_summary: str | None = None,
    ) -> None:
        row = _run_row(report)
        row["error_summary"] = error_summary
        _execute(
            self.client.table(self.run_table)
            .update(row)
            .eq("run_id", report.run_id)
            .execute()
        )

    def update_checkpoint(
        self,
        run_id: str,
        *,
        checkpoint: dict[str, Any],
        report: NCSOfficialSyncReport,
    ) -> None:
        row = _run_row(report)
        row["checkpoint"] = checkpoint
        _execute(
            self.client.table(self.run_table)
            .update(row)
            .eq("run_id", run_id)
            .execute()
        )

    def latest_checkpoint(self, mode: str) -> dict[str, Any] | None:
        response = (
            self.client.table(self.run_table)
            .select("checkpoint")
            .eq("mode", mode)
            .in_("status", ["partial", "failed", "running"])
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = _execute(response)
        return dict(rows[0].get("checkpoint") or {}) if rows else None

    def get_source_states(
        self, source_keys: list[str]
    ) -> dict[str, SourceRecordState]:
        if not source_keys:
            return {}
        rows = _execute(
            self.client.table(self.source_table)
            .select("source_key,payload_hash,embedded_payload_hash,chunk_ids")
            .in_("source_key", source_keys)
            .execute()
        )
        return {
            str(row["source_key"]): SourceRecordState(
                payload_hash=str(row["payload_hash"]),
                embedded_payload_hash=(
                    str(row["embedded_payload_hash"])
                    if row.get("embedded_payload_hash")
                    else None
                ),
                chunk_ids=tuple(str(value) for value in (row.get("chunk_ids") or [])),
            )
            for row in rows
        }

    def list_unit_targets(
        self, unit_code: str | None = None
    ) -> list[dict[str, Any]]:
        query = self.client.table(self.catalog_table).select(
            "unit_code,unit_name,duty_code,component_code,classification"
        )
        if unit_code:
            query = query.eq("unit_code", normalize_ncs_unit_code(unit_code))
        rows = _execute(query.limit(1000).execute())
        return _unit_targets_from_catalog_rows(rows, unit_code=unit_code)

    def list_selected_unit_codes(self) -> set[str]:
        selected: set[str] = set()
        page_size = 1000
        offset = 0
        while True:
            page = _execute(
                self.client.table(self.source_table)
                .select("unit_code")
                .eq("active", True)
                .not_.is_("unit_code", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            selected.update(
                normalize_ncs_unit_code(str(row["unit_code"]))
                for row in page
                if row.get("unit_code")
            )
            if len(page) < page_size:
                break
            offset += page_size
        return selected

    def upsert_source_records(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            _execute(
                self.client.table(self.source_table)
                .upsert(rows, on_conflict="source_key")
                .execute()
            )

    def upsert_catalog(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            _execute(
                self.client.table(self.catalog_table)
                .upsert(rows, on_conflict="unit_code")
                .execute()
            )

    def merge_criteria(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        codes = [str(row["criterion_code"]) for row in rows]
        existing_rows = _execute(
            self.client.table(self.criteria_table)
            .select("*")
            .in_("criterion_code", codes)
            .execute()
        )
        existing_by_code = {
            str(row["criterion_code"]): row for row in existing_rows
        }
        merged = [
            _merge_criterion_rows(
                existing_by_code.get(str(row["criterion_code"])),
                row,
            )
            for row in rows
        ]
        _execute(
            self.client.table(self.criteria_table)
            .upsert(merged, on_conflict="criterion_code")
            .execute()
        )
        unit_codes = sorted({str(row["unit_code"]) for row in merged})
        for unit_code in unit_codes:
            unit_criteria = _execute(
                self.client.table(self.criteria_table)
                .select(
                    "criterion_code,element_code,element_name,criterion_text"
                )
                .eq("unit_code", unit_code)
                .order("criterion_code")
                .execute()
            )
            criteria_payload = [_catalog_criterion(row) for row in unit_criteria]
            _execute(
                self.client.table(self.catalog_table)
                .update({"criteria": criteria_payload})
                .eq("unit_code", unit_code)
                .execute()
            )

    def upsert_modules(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            module_names = sorted({str(row["module_name"]) for row in rows})
            catalog_rows = _execute(
                self.client.table(self.catalog_table)
                .select("unit_code,unit_name,classification")
                .in_("unit_name", module_names)
                .execute()
            )
            linked_rows = _link_module_rows(rows, catalog_rows)
            _execute(
                self.client.table(self.module_table)
                .upsert(linked_rows, on_conflict="module_id")
                .execute()
            )

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if chunk_ids:
            _execute(
                self.client.table(self.chunk_table)
                .delete()
                .in_("chunk_id", chunk_ids)
                .execute()
            )

    def deactivate_missing(
        self,
        *,
        partition_key: str,
        seen_source_keys: set[str],
        run_id: str,
    ) -> list[str]:
        existing: list[dict[str, Any]] = []
        page_size = 1000
        offset = 0
        while True:
            page = _execute(
                self.client.table(self.source_table)
                .select("source_key,chunk_ids")
                .eq("partition_key", partition_key)
                .eq("active", True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            existing.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        stale = [
            row
            for row in existing
            if str(row["source_key"]) not in seen_source_keys
        ]
        stale_keys = [str(row["source_key"]) for row in stale]
        for batch in _value_batches(stale_keys, 200):
            _execute(
                self.client.table(self.source_table)
                .update({"active": False, "last_run_id": run_id})
                .in_("source_key", batch)
                .execute()
            )
        return [
            str(chunk_id)
            for row in stale
            for chunk_id in (row.get("chunk_ids") or [])
        ]


class NCSOfficialSyncService:
    def __init__(
        self,
        *,
        api_client: NCSOfficialAPIClient,
        store: NCSOfficialSyncStore,
        vector_store: VectorStore | None,
        project_id: str = "mvp-dataset",
    ) -> None:
        self.api_client = api_client
        self.store = store
        self.vector_store = vector_store
        self.project_id = project_id

    def sync(self, options: NCSOfficialSyncOptions) -> NCSOfficialSyncReport:
        if options.embed and self.vector_store is None and not options.dry_run:
            raise ValueError("vector_store is required when embed is enabled")
        if options.mode == "detail" and not options.dry_run:
            selected_units = self.store.list_selected_unit_codes()
            assert options.unit_code is not None
            if (
                options.unit_code not in selected_units
                and len(selected_units) >= options.max_selected_units
            ):
                raise RuntimeError(
                    "Selective NCS RAG unit limit reached: "
                    f"{len(selected_units)}/{options.max_selected_units}. "
                    "Remove an unused unit before synchronizing a new one."
                )
        report = NCSOfficialSyncReport(
            run_id=str(uuid4()),
            mode=options.mode,
            dry_run=options.dry_run,
        )
        targets = _sync_targets(options, self.store)
        target_index, page_no = self._resume_position(options, targets)
        if not options.dry_run:
            self.store.start_run(report)
        stopped_early = False
        try:
            index = target_index
            while index < len(targets):
                target = targets[index]
                current_page = page_no if index == target_index else 1
                can_finalize_target = current_page == 1
                seen_source_keys: set[str] = set()
                while True:
                    if report.request_count >= options.max_requests:
                        stopped_early = True
                        break
                    page = self.api_client.fetch_page(
                        target.operation,
                        page_no=current_page,
                        page_size=options.page_size,
                        params=target.params,
                    )
                    report.request_count += 1
                    page_item_count = len(page.items)
                    records = _canonical_records(
                        operation=target.operation,
                        items=page.items,
                        page_no=current_page,
                        page_size=options.page_size,
                        context=target.context,
                    )
                    records = _filter_selected_unit_records(
                        records,
                        selected_unit_codes=target.selected_unit_codes,
                    )
                    if options.record_limit is not None:
                        remaining = options.record_limit - report.received_count
                        records = records[: max(0, remaining)]
                    page_was_truncated = len(records) < page_item_count
                    seen_source_keys.update(record.source_key for record in records)
                    self._process_records(
                        records,
                        report=report,
                        options=options,
                        partition_key=target.key,
                    )
                    report.received_count += len(records)

                    has_more = page.has_next and bool(page.items)
                    if page_was_truncated:
                        next_checkpoint = {
                            "target_key": target.key,
                            "next_page": current_page,
                        }
                    elif has_more:
                        next_checkpoint = {
                            "target_key": target.key,
                            "next_page": current_page + 1,
                        }
                    else:
                        next_checkpoint = _next_target_checkpoint(targets, index)
                    report.checkpoint = next_checkpoint
                    if not options.dry_run:
                        self.store.update_checkpoint(
                            report.run_id,
                            checkpoint=next_checkpoint,
                            report=report,
                        )
                    if (
                        options.record_limit is not None
                        and report.received_count >= options.record_limit
                    ):
                        stopped_early = (
                            page_was_truncated
                            or has_more
                            or index < len(targets) - 1
                        )
                        break
                    if not has_more:
                        if (
                            can_finalize_target
                            and seen_source_keys
                            and options.mode == "detail"
                            and not options.dry_run
                        ):
                            stale_chunk_ids = self.store.deactivate_missing(
                                partition_key=target.key,
                                seen_source_keys=seen_source_keys,
                                run_id=report.run_id,
                            )
                            self.store.delete_chunks(stale_chunk_ids)
                            report.deleted_chunk_count += len(
                                set(stale_chunk_ids)
                            )
                        break
                    current_page += 1
                if stopped_early:
                    break
                page_no = 1
                index += 1
            report.status = "partial" if stopped_early else "completed"
            report.finished_at = datetime.now(timezone.utc)
            if not options.dry_run:
                self.store.finish_run(report)
            return report
        except Exception as exc:
            report.status = "failed"
            report.finished_at = datetime.now(timezone.utc)
            if not options.dry_run:
                self.store.finish_run(
                    report,
                    error_summary=f"{type(exc).__name__}: {exc}",
                )
            raise

    def _process_records(
        self,
        records: list[CanonicalNCSRecord],
        *,
        report: NCSOfficialSyncReport,
        options: NCSOfficialSyncOptions,
        partition_key: str,
    ) -> None:
        if not records:
            return
        persist_source_records = options.mode == "detail"
        states = (
            self.store.get_source_states([record.source_key for record in records])
            if persist_source_records
            else {}
        )
        changed = [
            record
            for record in records
            if states.get(record.source_key) is None
            or states[record.source_key].payload_hash != record.payload_hash
        ]
        report.changed_count += len(changed)
        report.unchanged_count += len(records) - len(changed)
        embed_records = (
            [
                record
                for record in records
                if states.get(record.source_key) is None
                or states[record.source_key].embedded_payload_hash
                != record.payload_hash
            ]
            if options.embed
            else []
        )
        fetched_at = datetime.now(timezone.utc)
        chunks_by_source = build_official_ncs_chunks(
            embed_records,
            project_id=self.project_id,
            fetched_at=fetched_at,
        )
        generated_chunks = [
            chunk
            for source_chunks in chunks_by_source.values()
            for chunk in source_chunks
        ]
        report.chunk_upsert_count += len(generated_chunks)
        catalog_rows = [
            row
            for record in changed
            if (row := catalog_patch(record, fetched_at=fetched_at)) is not None
        ]
        criterion_rows = _collapse_criterion_patches(
            row
            for record in changed
            if (row := criterion_patch(record)) is not None
        )
        module_rows = [
            row
            for record in changed
            if (row := module_patch(record, fetched_at=fetched_at)) is not None
        ]
        report.catalog_upsert_count += len(catalog_rows)
        report.criterion_upsert_count += len(criterion_rows)
        report.module_upsert_count += len(module_rows)
        if options.dry_run:
            return

        self.store.upsert_catalog(catalog_rows)
        self.store.merge_criteria(criterion_rows)
        self.store.upsert_modules(module_rows)
        if generated_chunks:
            assert self.vector_store is not None
            for batch in _batches(generated_chunks, options.embedding_batch_size):
                self.vector_store.upsert(project_id=self.project_id, chunks=batch)

        old_chunk_ids: list[str] = []
        for record in embed_records:
            state = states.get(record.source_key)
            new_ids = {
                chunk.chunk_id for chunk in chunks_by_source.get(record.source_key, [])
            }
            if state is not None:
                old_chunk_ids.extend(
                    chunk_id for chunk_id in state.chunk_ids if chunk_id not in new_ids
                )
        old_chunk_ids = list(dict.fromkeys(old_chunk_ids))
        self.store.delete_chunks(old_chunk_ids)
        report.deleted_chunk_count += len(old_chunk_ids)

        if not persist_source_records:
            return

        source_rows: list[dict[str, Any]] = []
        embedded_keys = {record.source_key for record in embed_records}
        for record in records:
            state = states.get(record.source_key)
            if record.source_key in embedded_keys:
                chunks = chunks_by_source.get(record.source_key, [])
                chunk_ids = [chunk.chunk_id for chunk in chunks]
                embedded_hash = record.payload_hash
            else:
                chunk_ids = list(state.chunk_ids) if state else []
                embedded_hash = state.embedded_payload_hash if state else None
            source_rows.append(
                source_record_row(
                    record,
                    run_id=report.run_id,
                    partition_key=partition_key,
                    fetched_at=fetched_at,
                    chunk_ids=chunk_ids,
                    embedded_payload_hash=embedded_hash,
                )
            )
        self.store.upsert_source_records(source_rows)

    def _resume_position(
        self,
        options: NCSOfficialSyncOptions,
        targets: list[SyncTarget],
    ) -> tuple[int, int]:
        if not options.resume:
            return 0, 1
        checkpoint = self.store.latest_checkpoint(options.mode) or {}
        target_key = str(checkpoint.get("target_key") or "")
        for index, target in enumerate(targets):
            if target.key == target_key:
                return index, max(1, int(checkpoint.get("next_page") or 1))
        return 0, 1


def _sync_targets(
    options: NCSOfficialSyncOptions,
    store: NCSOfficialSyncStore,
) -> list[SyncTarget]:
    targets: list[SyncTarget] = []
    if options.mode == "catalog":
        targets.extend(
            SyncTarget(key=f"catalog:{operation}", operation=operation)
            for operation in _CATALOG_OPERATIONS
        )
    if options.mode == "detail":
        detail_targets = _detail_targets(
            store.list_unit_targets(options.unit_code)
        )
        if not detail_targets:
            raise RuntimeError(
                f"NCS unit {options.unit_code!r} is not in the synchronized catalog. "
                "Run catalog synchronization first and verify the unit code."
            )
        targets.extend(detail_targets)
    return targets


def _detail_targets(units: list[dict[str, Any]]) -> list[SyncTarget]:
    if not units:
        return []
    targets: list[SyncTarget] = []
    units_by_duty: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        units_by_duty.setdefault(str(unit["dutyCd"]), []).append(unit)
    for duty_code, duty_units in sorted(units_by_duty.items()):
        context = {"dutyCd": duty_code}
        selected_codes = tuple(
            sorted(
                normalize_ncs_unit_code(str(unit["ncsClCd"]))
                for unit in duty_units
                if unit.get("ncsClCd")
            )
        )
        for operation in _SELECTIVE_DUTY_OPERATIONS:
            targets.append(
                SyncTarget(
                    key=f"detail:{operation}:units:{','.join(selected_codes)}",
                    operation=operation,
                    params={"dutyCd": duty_code},
                    context=context,
                    selected_unit_codes=selected_codes,
                )
            )
    for unit in units:
        duty_code = str(unit["dutyCd"])
        component_code = str(unit["compUnitCd"])
        context = {
            key: value
            for key, value in unit.items()
            if key in {"dutyCd", "compUnitCd", "ncsClCd", "compUnitName"}
            and value
        }
        params = {"dutyCd": duty_code, "compUnitCd": component_code}
        for operation in _SELECTIVE_UNIT_OPERATIONS:
            targets.append(
                SyncTarget(
                    key=(
                        f"detail:{operation}:unit:"
                        f"{unit.get('ncsClCd') or component_code}"
                    ),
                    operation=operation,
                    params=params,
                    context=context,
                )
            )
    return targets


def _unit_targets_from_catalog_rows(
    rows: Iterable[dict[str, Any]],
    *,
    unit_code: str | None = None,
) -> list[dict[str, Any]]:
    units: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        duty_code = str(row.get("duty_code") or "").strip()
        component_code = str(row.get("component_code") or "").strip()
        full_code = normalize_ncs_unit_code(str(row.get("unit_code") or ""))
        if not duty_code or not component_code:
            continue
        if unit_code and full_code != normalize_ncs_unit_code(unit_code):
            continue
        units[(duty_code, component_code)] = {
            "dutyCd": duty_code,
            "compUnitCd": component_code,
            "ncsClCd": full_code,
            "compUnitName": row.get("unit_name"),
        }
    return [
        units[key]
        for key in sorted(units, key=lambda value: (value[0], value[1]))
    ]


def _filter_selected_unit_records(
    records: list[CanonicalNCSRecord],
    *,
    selected_unit_codes: tuple[str, ...],
) -> list[CanonicalNCSRecord]:
    if not selected_unit_codes:
        return records
    selected = {
        normalize_ncs_unit_code(unit_code) for unit_code in selected_unit_codes
    }
    return [
        record
        for record in records
        if record.unit_code
        and normalize_ncs_unit_code(record.unit_code) in selected
    ]


def _payload_value(payload: dict[str, Any], key: str) -> str | None:
    target = key.casefold()
    for payload_key, value in payload.items():
        if str(payload_key).casefold() == target and value not in (None, ""):
            return " ".join(str(value).split())
        if isinstance(value, dict):
            nested = _payload_value(value, key)
            if nested:
                return nested
    return None


def _canonical_records(
    *,
    operation: str,
    items: Iterable[dict[str, Any]],
    page_no: int,
    page_size: int,
    context: dict[str, Any] | None = None,
) -> list[CanonicalNCSRecord]:
    records = [
        canonicalize_ncs_record(
            operation=operation,
            payload={**(context or {}), **item},
            position=(page_no - 1) * page_size + index,
        )
        for index, item in enumerate(items, start=1)
    ]
    seen: dict[str, int] = {}
    unique: list[CanonicalNCSRecord] = []
    for record in records:
        duplicate_index = seen.get(record.source_key, 0)
        seen[record.source_key] = duplicate_index + 1
        unique.append(
            record
            if duplicate_index == 0
            else replace(record, source_key=f"{record.source_key}:dup-{duplicate_index}")
        )
    return unique


def _collapse_criterion_patches(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    collapsed: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row["criterion_code"])
        collapsed[code] = _merge_criterion_rows(collapsed.get(code), row)
    return list(collapsed.values())


def _merge_criterion_rows(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = {**(existing or {}), **incoming}
    for key in ("knowledge", "skills", "attitudes", "assessment_guidance"):
        merged[key] = list(
            dict.fromkeys(
                [
                    *(existing or {}).get(key, []),
                    *incoming.get(key, []),
                ]
            )
        )
    return merged


def _catalog_criterion(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "criterion_code": row["criterion_code"],
        "element_code": row.get("element_code"),
        "element_name": row.get("element_name"),
        "text": row["criterion_text"],
    }


def _link_module_rows(
    rows: list[dict[str, Any]],
    catalog_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for catalog in catalog_rows:
        normalized_name = _normalized_name(catalog.get("unit_name"))
        if normalized_name:
            by_name.setdefault(normalized_name, []).append(catalog)
    linked: list[dict[str, Any]] = []
    for row in rows:
        if row.get("unit_code"):
            linked.append({**row, "link_status": "exact"})
            continue
        candidates = by_name.get(_normalized_name(row.get("module_name")), [])
        module_sub_name = _classification_sub_name(row.get("classification"))
        exact_candidates = [
            candidate
            for candidate in candidates
            if module_sub_name
            and module_sub_name
            in {
                _normalized_name(value)
                for value in (candidate.get("classification") or {}).values()
            }
        ]
        if len(exact_candidates) == 1:
            linked.append(
                {
                    **row,
                    "unit_code": exact_candidates[0]["unit_code"],
                    "link_status": "exact",
                }
            )
        elif candidates:
            linked.append({**row, "unit_code": None, "link_status": "candidate"})
        else:
            linked.append({**row, "unit_code": None, "link_status": "unresolved"})
    return linked


def _classification_sub_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("sub_name", "level_4", "세분류명"):
        normalized = _normalized_name(value.get(key))
        if normalized:
            return normalized
    return ""


def _normalized_name(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _next_target_checkpoint(
    targets: list[SyncTarget],
    current_index: int,
) -> dict[str, Any]:
    next_index = current_index + 1
    if next_index >= len(targets):
        return {}
    return {"target_key": targets[next_index].key, "next_page": 1}


def _batches(values: list[MaterialChunk], size: int) -> Iterable[list[MaterialChunk]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _value_batches(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _run_row(report: NCSOfficialSyncReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "mode": report.mode,
        "status": report.status,
        "checkpoint": report.checkpoint,
        "request_count": report.request_count,
        "received_count": report.received_count,
        "changed_count": report.changed_count,
        "chunk_upsert_count": report.chunk_upsert_count,
        "error_count": 1 if report.status == "failed" else 0,
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat() if report.finished_at else None,
    }


def _execute(response: Any) -> list[dict[str, Any]]:
    error = getattr(response, "error", None)
    if error is None and isinstance(response, dict):
        error = response.get("error")
    if error:
        raise RuntimeError(f"Supabase NCS sync request failed: {error}")
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise RuntimeError("Supabase NCS sync response data must be a list")
    return data
