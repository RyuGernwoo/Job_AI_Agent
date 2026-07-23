from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree


Transport = Callable[[str, float], bytes]

NCS_INFO_OPERATIONS = (
    "ncsCdInfo",
    "ncsDutyInfo",
    "ncsCompeUnitInfo",
    "ncsCompeUnitFactrInfo",
    "ncsKsaInfo",
    "ncsScopeInfo",
    "ncsEvalInfo",
    "ncsjobInfo",
    "ncsClposInfo",
    "ncsFusInfo",
    "ncsTrainCsdrInfo",
    "ncsCompeTrainInfo",
    "ncsSetqInfo",
)
NCS_MODULE_OPERATION = "ncsStudyModule"
NCS_REFERENCE_OPERATIONS = tuple(f"NCS{number:03d}" for number in range(1, 8))
_PAGED_INFO_OPERATIONS = {
    "ncsCdInfo",
    "ncsDutyInfo",
    "ncsCompeUnitInfo",
    "ncsCompeUnitFactrInfo",
    "ncsKsaInfo",
}
_SUCCESS_CODES = {
    "0",
    "00",
    "000",
    "200",
    "NORMAL_CODE",
    "NORMAL_SERVICE",
    "INFO-0",
    "INFO-000",
}


class NCSOfficialAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class NCSOfficialAPIPage:
    operation: str
    page_no: int
    page_size: int
    total_count: int
    total_pages: int
    items: tuple[dict[str, Any], ...]

    @property
    def has_next(self) -> bool:
        return self.page_no < self.total_pages


class NCSOfficialAPIClient:
    def __init__(
        self,
        *,
        service_key: str,
        base_url: str = "https://apis.data.go.kr/B490007/ncsInfo",
        module_url: str = (
            "https://apis.data.go.kr/B490007/ncsStudyModule/openapi21"
        ),
        reference_base_url: str = "https://apis.data.go.kr/B490007/hrdkapi",
        requests_per_second: float = 2.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not service_key.strip():
            raise ValueError("DATA_GO_KR_SERVICE_KEY is required")
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.service_key = unquote(service_key.strip())
        self.base_url = base_url.rstrip("/")
        self.module_url = module_url
        self.reference_base_url = reference_base_url.rstrip("/")
        self.requests_per_second = requests_per_second
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._transport = transport or _urlopen_transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def fetch_page(
        self,
        operation: str,
        *,
        page_no: int,
        page_size: int,
        params: Mapping[str, str | int] | None = None,
    ) -> NCSOfficialAPIPage:
        if operation not in {
            *NCS_INFO_OPERATIONS,
            *NCS_REFERENCE_OPERATIONS,
            NCS_MODULE_OPERATION,
        }:
            raise ValueError(f"unsupported NCS API operation: {operation}")
        if page_no <= 0:
            raise ValueError("page_no must be greater than 0")
        if page_size <= 0:
            raise ValueError("page_size must be greater than 0")
        if operation == NCS_MODULE_OPERATION:
            endpoint = self.module_url
        elif operation in NCS_REFERENCE_OPERATIONS:
            endpoint = f"{self.reference_base_url}/{operation}"
        else:
            endpoint = f"{self.base_url}/{operation}"
        query: dict[str, str | int] = {
            "serviceKey": self.service_key,
            "returnType": "json" if operation in NCS_REFERENCE_OPERATIONS else "xml",
        }
        if (
            operation in _PAGED_INFO_OPERATIONS
            or operation == NCS_MODULE_OPERATION
            or operation in NCS_REFERENCE_OPERATIONS
        ):
            query.update({"pageNo": page_no, "numOfRows": page_size})
        query.update(params or {})
        payload = self._request(f"{endpoint}?{urlencode(query)}")
        return parse_official_api_page(
            payload,
            operation=operation,
            requested_page_no=page_no,
            requested_page_size=page_size,
        )

    def _request(self, url: str) -> bytes:
        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()
            try:
                return self._transport(url, self.timeout_seconds)
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt >= self.max_retries:
                    raise NCSOfficialAPIError(
                        f"NCS official API HTTP error: status={exc.code}"
                    ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries:
                    raise NCSOfficialAPIError(
                        f"NCS official API request failed: {type(exc).__name__}"
                    ) from exc
            self._sleep(min(2**attempt, 30))
        raise AssertionError("retry loop must return or raise")

    def _wait_for_rate_limit(self) -> None:
        now = self._monotonic()
        minimum_interval = 1.0 / self.requests_per_second
        if self._last_request_at is not None:
            remaining = minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now


def parse_official_api_page(
    payload: bytes,
    *,
    operation: str,
    requested_page_no: int,
    requested_page_size: int,
) -> NCSOfficialAPIPage:
    stripped = payload.lstrip()
    if not stripped:
        raise NCSOfficialAPIError("NCS official API returned an empty response")
    if stripped.startswith((b"{", b"[")):
        parsed = _parse_json_payload(payload)
    else:
        parsed = _parse_xml_payload(payload)
    _raise_for_result_code(parsed["result_code"], parsed["result_message"])
    page_no = _positive_int(parsed["page_no"], default=requested_page_no)
    page_size = _positive_int(parsed["page_size"], default=requested_page_size)
    items = tuple(parsed["items"])
    total_count = _nonnegative_int(parsed["total_count"], default=len(items))
    total_pages = _positive_int(
        parsed["total_pages"],
        default=max(1, math.ceil(total_count / page_size)) if total_count else page_no,
    )
    if operation in NCS_INFO_OPERATIONS and operation not in _PAGED_INFO_OPERATIONS:
        total_pages = page_no
    return NCSOfficialAPIPage(
        operation=operation,
        page_no=page_no,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
        items=items,
    )


def _urlopen_transport(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/xml, application/json",
            "User-Agent": "LessonPack-AI-NCS-Sync/1.0",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _parse_xml_payload(payload: bytes) -> dict[str, Any]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise NCSOfficialAPIError("NCS official API returned invalid XML") from exc
    data_info = _find_xml_element(root, "dataInfo")
    rows = [
        _element_to_mapping(element)
        for element in root.iter()
        if _local_name(element.tag).casefold() == "row"
    ]
    items = rows or [
        _element_to_mapping(element)
        for element in root.iter()
        if _local_name(element.tag).casefold() == "item"
    ]
    return {
        "result_code": _find_xml_text(root, "resultCode")
        or _find_xml_text(data_info, "code"),
        "result_message": _find_xml_text(root, "resultMsg", "resultMessage")
        or _find_xml_text(data_info, "message"),
        "page_no": _find_xml_text(data_info, "pageNo")
        or _find_xml_text(root, "pageNo"),
        "page_size": _find_xml_text(data_info, "numOfRows", "pageSize")
        or _find_xml_text(root, "numOfRows", "pageSize"),
        "total_count": _find_xml_text(data_info, "totalCount", "totCnt")
        or _find_xml_text(root, "totalCount", "totCnt"),
        "total_pages": _find_xml_text(data_info, "totalPage", "totalPages")
        or _find_xml_text(root, "totalPage", "totalPages"),
        "items": items,
    }


def _parse_json_payload(payload: bytes) -> dict[str, Any]:
    try:
        root = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NCSOfficialAPIError("NCS official API returned invalid JSON") from exc
    data_info = _find_json_mapping(root, "dataInfo")
    items_value = _find_json_value(root, "row")
    if items_value is None:
        items_value = _find_json_value(root, "item")
    if items_value is None:
        items_value = _find_json_value(root, "items")
    if isinstance(items_value, Mapping):
        nested = items_value.get("item")
        items_value = nested if nested is not None else [dict(items_value)]
    if not isinstance(items_value, list):
        items_value = []
    items = [dict(item) for item in items_value if isinstance(item, Mapping)]
    return {
        "result_code": _find_json_value(root, "resultCode")
        or _mapping_value(data_info, "code"),
        "result_message": _find_json_value(
            root, "resultMsg", "resultMessage"
        )
        or _mapping_value(data_info, "message"),
        "page_no": _mapping_value(data_info, "pageNo")
        or _find_json_value(root, "pageNo"),
        "page_size": _mapping_value(data_info, "numOfRows", "pageSize")
        or _find_json_value(root, "numOfRows", "pageSize"),
        "total_count": _mapping_value(data_info, "totalCount", "totCnt")
        or _find_json_value(root, "totalCount", "totCnt"),
        "total_pages": _mapping_value(data_info, "totalPage", "totalPages")
        or _find_json_value(root, "totalPage", "totalPages"),
        "items": items,
    }


def _element_to_mapping(element: ElementTree.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in list(element):
        key = _local_name(child.tag)
        value: Any = (
            _element_to_mapping(child) if list(child) else (child.text or "").strip()
        )
        if key in result:
            current = result[key]
            result[key] = current + [value] if isinstance(current, list) else [current, value]
        else:
            result[key] = value
    return result


def _find_xml_element(
    root: ElementTree.Element, *names: str
) -> ElementTree.Element | None:
    targets = {name.casefold() for name in names}
    for element in root.iter():
        if _local_name(element.tag).casefold() in targets:
            return element
    return None


def _find_xml_text(
    root: ElementTree.Element | None, *names: str
) -> str | None:
    if root is None:
        return None
    element = _find_xml_element(root, *names)
    if element is not None:
        value = (element.text or "").strip()
        if value:
            return value
    return None


def _find_json_value(value: Any, *names: str) -> Any:
    targets = {name.casefold() for name in names}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in targets and item not in (None, ""):
                return item
        for item in value.values():
            found = _find_json_value(item, *names)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_json_value(item, *names)
            if found not in (None, ""):
                return found
    return None


def _find_json_mapping(value: Any, *names: str) -> Mapping[str, Any] | None:
    found = _find_json_value(value, *names)
    return found if isinstance(found, Mapping) else None


def _mapping_value(value: Mapping[str, Any] | None, *names: str) -> Any:
    if value is None:
        return None
    targets = {name.casefold() for name in names}
    for key, item in value.items():
        if str(key).casefold() in targets and item not in (None, ""):
            return item
    return None


def _raise_for_result_code(code: Any, message: Any) -> None:
    if code in (None, ""):
        return
    normalized = str(code).strip().upper()
    if normalized not in _SUCCESS_CODES:
        detail = " ".join(str(message or "unknown error").split())
        raise NCSOfficialAPIError(
            f"NCS official API rejected the request: code={normalized}, message={detail}"
        )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _nonnegative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
