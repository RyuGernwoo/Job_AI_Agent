from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from lectureops_agent.models.schemas import MaterialChunk


NCS_INFO_SOURCE_URL = "https://www.data.go.kr/data/15157547/openapi.do"
NCS_MODULE_SOURCE_URL = "https://www.data.go.kr/data/15086442/openapi.do"
_VERSION = re.compile(r"_(?P<version>\d{2}v\d+)", re.IGNORECASE)

_UNIT_CODE_KEYS = (
    "ncsClCd",
    "ncsUnitCd",
    "ncsCompeUnitCd",
    "compeUnitCd",
    "compeUnitCode",
    "능력단위분류번호",
    "능력단위코드",
)
_UNIT_NAME_KEYS = (
    "compeUnitName",
    "compeUnitNm",
    "ncsCompeUnitName",
    "ncsCompeUnitNm",
    "능력단위명",
    "능력단위명칭",
)
_UNIT_DEFINITION_KEYS = (
    "compeUnitDef",
    "compeUnitDefinition",
    "ncsCompeUnitDef",
    "능력단위정의",
)
_LEVEL_KEYS = (
    "compeUnitLevel",
    "compeUnitLvl",
    "ncsLevel",
    "능력단위수준",
    "수준",
)
_ELEMENT_CODE_KEYS = (
    "compeUnitFactrCd",
    "compeUnitFactorCd",
    "elementCode",
    "능력단위요소코드",
    "능력단위요소번호",
)
_ELEMENT_NAME_KEYS = (
    "compeUnitFactrName",
    "compeUnitFactrNm",
    "compeUnitFactorName",
    "elementName",
    "능력단위요소명",
    "능력단위요소설명",
)
_CRITERION_CODE_KEYS = (
    "performCrtrCd",
    "performCrtrNo",
    "performanceCriterionCode",
    "performanceCriterionNo",
    "수행준거코드",
    "수행준거번호",
)
_CRITERION_TEXT_KEYS = (
    "performCrtr",
    "performCrtrText",
    "performanceCriteria",
    "performanceCriterion",
    "수행준거",
    "수행준거내용",
)
_KSA_TYPE_KEYS = ("ksaType", "ksaSe", "ksaCd", "ksa구분", "KSA구분")
_KSA_CODE_KEYS = ("ksaNo", "ksaSeq", "ksaItemCd", "KSA번호", "KSA코드")
_KSA_TEXT_KEYS = ("ksaText", "ksaName", "ksaCn", "ksaDesc", "KSA명", "KSA설명")
_MODULE_ID_KEYS = ("learnModulSeq", "learningModuleId", "학습모듈번호")
_MODULE_NAME_KEYS = ("learnModulName", "modulNm", "학습모듈명", "학습모듈명칭")
_MODULE_TEXT_KEYS = ("learnModulText", "moduleText", "학습모듈내용")

_CLASSIFICATION_KEYS = {
    "large_code": ("ncsLclasCd", "대분류코드"),
    "large_name": ("ncsLclasCdnm", "ncsLclasCdNm", "대분류코드명", "대분류명"),
    "middle_code": ("ncsMclasCd", "중분류코드"),
    "middle_name": ("ncsMclasCdnm", "ncsMclasCdNm", "중분류코드명", "중분류명"),
    "small_code": ("ncsSclasCd", "소분류코드"),
    "small_name": ("ncsSclasCdnm", "ncsSclasCdNm", "소분류코드명", "소분류명"),
    "sub_code": ("ncsSubdCd", "세분류코드"),
    "sub_name": ("ncsSubdCdnm", "ncsSubdCdNm", "세분류코드명", "세분류명"),
}

_CHUNK_TYPES = {
    "ncsCompeUnitInfo": "ncs_unit_overview",
    "ncsCompeUnitFactrInfo": "ncs_element_criteria",
    "ncsKsaInfo": "ncs_element_criteria",
    "ncsScopeInfo": "ncs_scope",
    "ncsEvalInfo": "ncs_evaluation",
    "ncsjobInfo": "ncs_job_foundation",
    "ncsFusInfo": "ncs_related_unit",
    "ncsTrainCsdrInfo": "ncs_training_standard",
    "ncsCompeTrainInfo": "ncs_training_standard",
    "ncsSetqInfo": "ncs_training_standard",
    "ncsStudyModule": "ncs_learning_module_summary",
}


@dataclass(frozen=True)
class CanonicalNCSRecord:
    source_key: str
    operation: str
    entity_type: str
    payload: dict[str, Any]
    payload_hash: str
    unit_code: str | None
    unit_name: str | None
    definition: str | None
    level: int | None
    catalog_version: str | None
    classification: dict[str, str]
    element_code: str | None
    element_name: str | None
    criterion_code: str | None
    criterion_text: str | None
    ksa_type: str | None
    ksa_text: str | None
    module_id: str | None
    module_name: str | None
    module_text: str | None

    @property
    def source_url(self) -> str:
        return (
            NCS_MODULE_SOURCE_URL
            if self.operation == "ncsStudyModule"
            else NCS_INFO_SOURCE_URL
        )


def canonicalize_ncs_record(
    *,
    operation: str,
    payload: Mapping[str, Any],
    position: int = 0,
) -> CanonicalNCSRecord:
    normalized_payload = _normalize_payload(payload)
    fields = _flatten_scalars(normalized_payload)
    unit_code = _pick(fields, *_UNIT_CODE_KEYS)
    unit_name = _pick(fields, "compUnitName", *_UNIT_NAME_KEYS)
    definition = _pick(fields, "compUnitDef", *_UNIT_DEFINITION_KEYS)
    level = _parse_level(_pick(fields, "compUnitLevel", *_LEVEL_KEYS))
    version_match = _VERSION.search(unit_code or "")
    classification = {
        key: value
        for key, aliases in _CLASSIFICATION_KEYS.items()
        if (value := _pick(fields, *aliases))
    }
    element_code = _pick(
        fields,
        "compUnitFactrNo",
        "compUnitFactrCd",
        *_ELEMENT_CODE_KEYS,
    )
    element_name = _pick(fields, "compUnitFactrName", *_ELEMENT_NAME_KEYS)
    criterion_number = _pick(fields, *_CRITERION_CODE_KEYS)
    criterion_text = _pick(fields, *_CRITERION_TEXT_KEYS)
    ksa_type = _pick(fields, "gbnName", *_KSA_TYPE_KEYS)
    ksa_code = _pick(fields, "gbnCd", *_KSA_CODE_KEYS)
    ksa_text = _pick(fields, "gbnVal", *_KSA_TEXT_KEYS)
    if operation == "ncsKsaInfo" and _is_performance_criterion(ksa_type):
        criterion_number = criterion_number or ksa_code
        criterion_text = criterion_text or ksa_text
        ksa_type = None
        ksa_text = None
    module_id = _pick(fields, *_MODULE_ID_KEYS)
    module_name = _pick(fields, *_MODULE_NAME_KEYS)
    module_text = _pick(fields, *_MODULE_TEXT_KEYS)
    payload_hash = _json_hash(normalized_payload)
    criterion_code = _criterion_code(
        unit_code=unit_code,
        element_code=element_code,
        criterion_number=criterion_number,
        criterion_text=criterion_text,
    )
    identity = [
        module_id,
        unit_code,
        element_code,
        criterion_number,
        _normalize_ksa_type(ksa_type),
        ksa_code,
    ]
    identity_text = ":".join(_slug(value) for value in identity if value)
    if operation == "ncsKsaInfo" and not ksa_code:
        identity_text = f"{identity_text}:row-{position}" if identity_text else f"row-{position}"
    if not identity_text:
        identity_text = f"record-{position}-{payload_hash[:16]}"
    return CanonicalNCSRecord(
        source_key=f"{operation}:{identity_text}",
        operation=operation,
        entity_type=_entity_type(operation),
        payload=normalized_payload,
        payload_hash=payload_hash,
        unit_code=unit_code,
        unit_name=unit_name,
        definition=definition,
        level=level,
        catalog_version=(version_match.group("version") if version_match else None),
        classification=classification,
        element_code=element_code,
        element_name=element_name,
        criterion_code=criterion_code,
        criterion_text=criterion_text,
        ksa_type=_normalize_ksa_type(ksa_type),
        ksa_text=ksa_text,
        module_id=module_id,
        module_name=module_name,
        module_text=module_text,
    )


def build_official_ncs_chunks(
    records: Iterable[CanonicalNCSRecord],
    *,
    project_id: str,
    fetched_at: datetime | None = None,
    max_characters: int = 1800,
) -> dict[str, list[MaterialChunk]]:
    timestamp = (fetched_at or datetime.now(timezone.utc)).isoformat()
    chunks_by_source: dict[str, list[MaterialChunk]] = {}
    for record in records:
        chunk_type = _CHUNK_TYPES.get(record.operation)
        if chunk_type is None:
            chunks_by_source[record.source_key] = []
            continue
        text = _record_text(record)
        parts = _split_text(text, max_characters=max_characters)
        source_chunks: list[MaterialChunk] = []
        for part_index, part in enumerate(parts, start=1):
            source_digest = hashlib.sha256(record.source_key.encode("utf-8")).hexdigest()[:16]
            content_hash = hashlib.sha256(part.encode("utf-8")).hexdigest()
            metadata: dict[str, Any] = {
                "dataset": "ncs_official_api",
                "provider": "한국산업인력공단",
                "operation": record.operation,
                "chunk_type": chunk_type,
                "unit_code": record.unit_code,
                "ncs_unit_code": record.unit_code,
                "unit_name": record.unit_name,
                "element_code": record.element_code,
                "catalog_version": record.catalog_version,
                "classification": record.classification,
                "content_scope": (
                    "module_api_summary"
                    if record.operation == "ncsStudyModule"
                    else "structured_detail"
                ),
                "source_url": record.source_url,
                "license": "공공데이터포털 이용허락범위 제한 없음",
                "fetched_at": timestamp,
                "payload_hash": record.payload_hash,
                "source_key": record.source_key,
                "tags": ["NCS", "official-api"],
                "part": part_index,
                "parts": len(parts),
            }
            source_chunks.append(
                MaterialChunk(
                    chunk_id=f"ncs-api-{source_digest}-{content_hash[:12]}-{part_index}",
                    project_id=project_id,
                    document_id=f"ncs-api-{source_digest}",
                    source_name=record.module_name
                    or record.unit_name
                    or f"NCS 공식 {record.operation}",
                    source_type="md",
                    text=part,
                    metadata={key: value for key, value in metadata.items() if value is not None},
                )
            )
        chunks_by_source[record.source_key] = source_chunks
    return chunks_by_source


def catalog_patch(record: CanonicalNCSRecord, *, fetched_at: datetime) -> dict[str, Any] | None:
    if record.operation != "ncsCompeUnitInfo" or not record.unit_code or not record.unit_name:
        return None
    row: dict[str, Any] = {
        "unit_code": record.unit_code,
        "unit_name": record.unit_name,
        "source_url": record.source_url,
        "official_source_hash": record.payload_hash,
        "official_synced_at": fetched_at.isoformat(),
    }
    optional_values = {
        "definition": record.definition,
        "classification": record.classification or None,
        "level": record.level,
        "catalog_version": record.catalog_version,
    }
    row.update({key: value for key, value in optional_values.items() if value is not None})
    return row


def criterion_patch(record: CanonicalNCSRecord) -> dict[str, Any] | None:
    if (
        record.operation != "ncsKsaInfo"
        or not record.unit_code
        or not record.criterion_code
        or not record.criterion_text
    ):
        return None
    ksa_lists = {"knowledge": [], "skills": [], "attitudes": []}
    if record.ksa_text and record.ksa_type in ksa_lists:
        ksa_lists[record.ksa_type] = [record.ksa_text]
    fields = _flatten_scalars(record.payload)
    ksa_lists["knowledge"].extend(
        _split_list(_pick(fields, "knowledge", "knowledgeText", "지식"))
    )
    ksa_lists["skills"].extend(
        _split_list(_pick(fields, "skill", "skills", "skillText", "기술"))
    )
    ksa_lists["attitudes"].extend(
        _split_list(_pick(fields, "attitude", "attitudes", "attitudeText", "태도"))
    )
    return {
        "criterion_code": record.criterion_code,
        "unit_code": record.unit_code,
        "element_code": record.element_code,
        "element_name": record.element_name,
        "criterion_text": record.criterion_text,
        **{key: _unique(values) for key, values in ksa_lists.items()},
        "assessment_guidance": [],
    }


def module_patch(record: CanonicalNCSRecord, *, fetched_at: datetime) -> dict[str, Any] | None:
    if record.operation != "ncsStudyModule" or not record.module_id or not record.module_name:
        return None
    return {
        "module_id": record.module_id,
        "module_name": record.module_name,
        "module_text": record.module_text or "",
        "classification": record.classification,
        "unit_code": record.unit_code,
        "link_status": "exact" if record.unit_code else "unresolved",
        "source_url": record.source_url,
        "payload_hash": record.payload_hash,
        "fetched_at": fetched_at.isoformat(),
    }


def source_record_row(
    record: CanonicalNCSRecord,
    *,
    run_id: str,
    partition_key: str,
    fetched_at: datetime,
    chunk_ids: list[str],
    embedded_payload_hash: str | None,
) -> dict[str, Any]:
    return {
        "source_key": record.source_key,
        "operation": record.operation,
        "partition_key": partition_key,
        "entity_type": record.entity_type,
        "unit_code": record.unit_code,
        "payload": record.payload,
        "payload_hash": record.payload_hash,
        "fetched_at": fetched_at.isoformat(),
        "active": True,
        "last_run_id": run_id,
        "chunk_ids": chunk_ids,
        "embedded_payload_hash": embedded_payload_hash,
    }


def _record_text(record: CanonicalNCSRecord) -> str:
    title = record.module_name or record.unit_name or f"NCS {record.operation}"
    lines = [f"# {title}"]
    labeled_values = (
        ("능력단위 코드", record.unit_code),
        ("능력단위명", record.unit_name),
        ("능력단위 정의", record.definition),
        ("수준", str(record.level) if record.level is not None else None),
        ("능력단위요소 코드", record.element_code),
        ("능력단위요소", record.element_name),
        ("수행준거", record.criterion_text),
        ("KSA 구분", record.ksa_type),
        ("KSA 내용", record.ksa_text),
        ("학습모듈 번호", record.module_id),
        ("학습모듈 내용", record.module_text),
    )
    for label, value in labeled_values:
        if value:
            lines.append(f"- {label}: {value}")
    if record.classification:
        classification_text = " > ".join(
            record.classification[key]
            for key in ("large_name", "middle_name", "small_name", "sub_name")
            if key in record.classification
        )
        if classification_text:
            lines.append(f"- NCS 분류: {classification_text}")
    known_values = {str(value) for _, value in labeled_values if value}
    for key, value in _flatten_scalars(record.payload).items():
        if not value or value in known_values:
            continue
        lines.append(f"- {key}: {value}")
    lines.append(f"- 출처: {record.source_url}")
    return "\n".join(lines)


def _criterion_code(
    *,
    unit_code: str | None,
    element_code: str | None,
    criterion_number: str | None,
    criterion_text: str | None,
) -> str | None:
    if not unit_code or not criterion_text:
        return None
    number = criterion_number or hashlib.sha256(
        criterion_text.encode("utf-8")
    ).hexdigest()[:12]
    return ":".join(value for value in (unit_code, element_code, number) if value)


def _entity_type(operation: str) -> str:
    if operation == "ncsStudyModule":
        return "module"
    if operation == "ncsCompeUnitInfo":
        return "unit"
    if operation == "ncsCompeUnitFactrInfo":
        return "element"
    if operation == "ncsKsaInfo":
        return "criterion"
    if operation == "ncsCdInfo":
        return "classification"
    return "unit_detail"


def _normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key).strip(): _normalize_value(value)
        for key, value in payload.items()
        if str(key).strip()
    }


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _normalize_payload(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    return " ".join(str(value).split())


def _flatten_scalars(payload: Mapping[str, Any]) -> dict[str, str]:
    flattened: dict[str, str] = {}

    def visit(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        for key, item in value.items():
            if isinstance(item, Mapping):
                visit(item)
            elif isinstance(item, list):
                texts = [
                    " ".join(str(entry).split())
                    for entry in item
                    if not isinstance(entry, (dict, list)) and str(entry).strip()
                ]
                if texts:
                    flattened[_key(key)] = " | ".join(texts)
            elif item not in (None, ""):
                flattened[_key(key)] = " ".join(str(item).split())

    visit(payload)
    return flattened


def _pick(fields: Mapping[str, str], *aliases: str) -> str | None:
    for alias in aliases:
        value = fields.get(_key(alias))
        if value:
            return value
    return None


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value).casefold())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", value.strip())
    return normalized.strip("-")[:120]


def _json_hash(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_level(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    parsed = int(value)
    return parsed if 1 <= parsed <= 8 else None


def _normalize_ksa_type(value: str | None) -> str | None:
    normalized = _key(value or "")
    if normalized in {"k", "knowledge", "지식"} or "지식" in normalized:
        return "knowledge"
    if normalized in {"s", "skill", "skills", "기술"} or "기술" in normalized:
        return "skills"
    if normalized in {"a", "attitude", "attitudes", "태도"} or "태도" in normalized:
        return "attitudes"
    return None


def _is_performance_criterion(value: str | None) -> bool:
    normalized = _key(value or "")
    return normalized in {
        "performancecriterion",
        "performancecriteria",
        "\uc218\ud589\uc900\uac70",
    }


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        item.strip(" -•\t")
        for item in re.split(r"[|\n;]+", value)
        if item.strip(" -•\t")
    ]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _split_text(text: str, *, max_characters: int) -> list[str]:
    if max_characters <= 0:
        raise ValueError("max_characters must be greater than 0")
    if len(text) <= max_characters:
        return [text]
    lines = text.splitlines()
    parts: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        if current and current_length + len(line) + 1 > max_characters:
            parts.append("\n".join(current))
            current = []
            current_length = 0
        if len(line) > max_characters:
            if current:
                parts.append("\n".join(current))
                current = []
                current_length = 0
            parts.extend(
                line[index : index + max_characters]
                for index in range(0, len(line), max_characters)
            )
            continue
        current.append(line)
        current_length += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return [part for part in parts if part.strip()]
