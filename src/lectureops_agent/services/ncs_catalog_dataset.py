from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from lectureops_agent.models.schemas import NCSCatalogCriterion, NCSCatalogUnit


_UNIT_HEADING = re.compile(r"^## 능력단위:\s*(?P<code>\S+)\s*$", re.MULTILINE)
_ELEMENT_BLOCK = re.compile(
    r"- 열 1:\s*(?P<element_code>\S+\.\d+)\s*\n"
    r"\s*(?P<element_name>[^\n]+)\s*\n"
    r"- 열 5:\s*(?P<body>.*?)(?=\n### Row|\n## 능력단위:|\Z)",
    re.DOTALL,
)
_CRITERION_START = re.compile(r"^(?P<number>\d+\.\d+)\s+(?P<text>.+)$")
_VERSION = re.compile(r"_(?P<version>\d{2}v\d+)", re.IGNORECASE)


def build_ncs_catalog(markdown_root: Path) -> list[NCSCatalogUnit]:
    units: dict[str, NCSCatalogUnit] = {}
    for path in sorted(markdown_root.rglob("*.md")):
        for unit in parse_ncs_catalog_markdown(path):
            current = units.get(unit.unit_code)
            if current is None or len(unit.criteria) > len(current.criteria):
                units[unit.unit_code] = unit
    return sorted(units.values(), key=lambda item: item.unit_code)


def parse_ncs_catalog_markdown(path: Path) -> list[NCSCatalogUnit]:
    raw = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(raw)
    matches = list(_UNIT_HEADING.finditer(body))
    parsed: list[NCSCatalogUnit] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section = body[match.end() : end]
        unit_code = match.group("code").strip()
        unit_name = _label_value(section, "능력단위 명칭")
        if not unit_name:
            continue
        criteria: list[NCSCatalogCriterion] = []
        for element in _ELEMENT_BLOCK.finditer(section):
            criteria.extend(
                _criteria_from_block(
                    unit_code=unit_code,
                    element_code=element.group("element_code").strip(),
                    element_name=" ".join(element.group("element_name").split()),
                    body=element.group("body"),
                )
            )
        level_text = _label_value(section, "능력단위 수준")
        level = int(level_text) if level_text and level_text.isdigit() else None
        hierarchy = metadata.get("ncs_hierarchy", [])
        classification = {
            f"level_{item_index + 1}": str(value)
            for item_index, value in enumerate(hierarchy)
            if str(value).strip()
        }
        version_match = _VERSION.search(unit_code)
        parsed.append(
            NCSCatalogUnit(
                unit_code=unit_code,
                unit_name=" ".join(unit_name.split()),
                definition=_label_value(section, "능력단위 정의") or None,
                classification=classification,
                level=level,
                catalog_version=(version_match.group("version") if version_match else None),
                source_url=str(metadata.get("source_url") or "https://www.ncs.go.kr/"),
                criteria=criteria,
            )
        )
    return parsed


def catalog_row(unit: NCSCatalogUnit, *, source_hash: str | None = None) -> dict[str, Any]:
    payload = unit.model_dump(mode="json")
    resolved_hash = source_hash or hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **payload,
        "source_hash": resolved_hash,
    }


def criterion_rows(units: Iterable[NCSCatalogUnit]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        for criterion in unit.criteria:
            rows.append(
                {
                    "criterion_code": criterion.criterion_code,
                    "unit_code": unit.unit_code,
                    "element_code": criterion.element_code,
                    "element_name": criterion.element_name,
                    "criterion_text": criterion.text,
                    "knowledge": [],
                    "skills": [],
                    "attitudes": [],
                    "assessment_guidance": [],
                }
            )
    return rows


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _criteria_from_block(
    *,
    unit_code: str,
    element_code: str,
    element_name: str,
    body: str,
) -> list[NCSCatalogCriterion]:
    extracted: list[tuple[str, str]] = []
    current_number: str | None = None
    current_parts: list[str] = []
    for raw_line in body.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or line.startswith("【") or line.startswith("•"):
            continue
        matched = _CRITERION_START.match(line)
        if matched:
            if current_number and current_parts:
                extracted.append((current_number, " ".join(current_parts)))
            current_number = matched.group("number")
            current_parts = [matched.group("text")]
        elif current_number:
            current_parts.append(line)
    if current_number and current_parts:
        extracted.append((current_number, " ".join(current_parts)))
    return [
        NCSCatalogCriterion(
            criterion_code=f"{unit_code}.{number}",
            element_code=element_code,
            element_name=element_name,
            text=text,
        )
        for number, text in extracted
    ]


def _label_value(section: str, label: str) -> str:
    match = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(?P<value>[^\n]+)", section)
    return " ".join(match.group("value").split()) if match else ""


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw
    metadata = yaml.safe_load(raw[4:end]) or {}
    return metadata if isinstance(metadata, dict) else {}, raw[end + 5 :]
