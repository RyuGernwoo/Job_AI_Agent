"""Convert NCS_raw sources to Markdown and build RAG-ready JSONL chunks.

The pipeline is deliberately two-pass: every PDF/XLS source is first persisted
as Markdown, and chunks are then built by reading those Markdown artifacts.
Generated data is stored below ignored data directories; this tracked script is
the reproducible transformation contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator

import fitz
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_ROOT = ROOT / "data" / "NCS_raw"
DEFAULT_MARKDOWN_ROOT = ROOT / "data" / "raw" / "ncs_expansion" / "converted_md"
DEFAULT_PROCESSED_ROOT = ROOT / "data" / "processed" / "ncs_expansion"
DATASET_VERSION = "ncs-expansion-v1"
SOURCE_URL = "https://www.ncs.go.kr/"
LICENSE_NOTICE = "NCS 학습모듈 교육 목적 활용, 출처 명시 및 재배포 조건 확인 필요"
PAGE_HEADING = re.compile(r"^## Page (\d+)\s*$", flags=re.MULTILINE)
UNIT_HEADING = re.compile(r"^## 능력단위: (.+?)\s*$", flags=re.MULTILINE)
NUMBERED_PREFIX = re.compile(r"^\d+\.\s*")
YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
NCS_CODE_PATTERN = re.compile(r"\b\d{8,}_(\d{2})v\d+\b", flags=re.IGNORECASE)
PAGE_NUMBER_LINE = re.compile(r"^(?:-\s*)?\d{1,4}(?:\s*-)?$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative_path: str
    source_kind: str
    source_id: str
    document_id: str
    sha256: str
    duplicate_of: str | None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert NCS_raw PDF/XLS files to Markdown and build RAG chunks."
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--markdown-root", type=Path, default=DEFAULT_MARKDOWN_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--chunk-size", type=int, default=1400)
    parser.add_argument("--chunk-overlap", type=int, default=160)
    parser.add_argument("--force", action="store_true", help="Rewrite existing Markdown artifacts.")
    args = parser.parse_args(argv)

    if args.chunk_size < 300:
        parser.error("--chunk-size must be at least 300")
    if args.chunk_overlap < 0 or args.chunk_overlap >= args.chunk_size:
        parser.error("--chunk-overlap must be non-negative and smaller than --chunk-size")

    report = prepare_dataset(
        raw_root=args.raw_root.resolve(),
        markdown_root=args.markdown_root.resolve(),
        processed_root=args.processed_root.resolve(),
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        force=args.force,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def prepare_dataset(
    *,
    raw_root: Path,
    markdown_root: Path,
    processed_root: Path,
    chunk_size: int,
    chunk_overlap: int,
    force: bool,
) -> dict[str, Any]:
    if not raw_root.exists():
        raise FileNotFoundError(f"NCS raw root does not exist: {raw_root}")

    markdown_root.mkdir(parents=True, exist_ok=True)
    processed_root.mkdir(parents=True, exist_ok=True)
    sources = inventory_sources(raw_root)
    if not sources:
        raise RuntimeError(f"No PDF or XLS files found below {raw_root}")

    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for index, source in enumerate(sources, start=1):
        try:
            record = convert_source_to_markdown(
                source=source,
                raw_root=raw_root,
                markdown_root=markdown_root,
                force=force,
            )
            records.append(record)
        except Exception as exc:  # Keep the complete failure inventory for a large batch.
            errors.append(
                {
                    "source_id": source.source_id,
                    "original_path": source.relative_path,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if index % 10 == 0 or index == len(sources):
            print(f"[convert] {index}/{len(sources)}", file=sys.stderr, flush=True)

    chunks_path = processed_root / "chunks.jsonl"
    chunks_temp_path = chunks_path.with_suffix(".jsonl.tmp")
    chunk_count = 0
    chunk_counts_by_kind: Counter[str] = Counter()
    chunk_counts_by_category: Counter[str] = Counter()
    with chunks_temp_path.open("w", encoding="utf-8", newline="\n") as output:
        for index, record in enumerate(records, start=1):
            if record.get("duplicate_of"):
                record["chunk_count"] = 0
                record["rag_status"] = "excluded_exact_duplicate"
                continue
            markdown_path = ROOT / record["converted_markdown"]
            source_chunks = list(
                chunks_from_markdown(
                    markdown_path=markdown_path,
                    record=record,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            )
            for chunk in source_chunks:
                output.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            record["chunk_count"] = len(source_chunks)
            record["rag_status"] = "ready" if source_chunks else "excluded_no_meaningful_text"
            chunk_count += len(source_chunks)
            chunk_counts_by_kind[record["source_kind"]] += len(source_chunks)
            chunk_counts_by_category[record["top_category"]] += len(source_chunks)
            if index % 10 == 0 or index == len(records):
                print(f"[chunk] {index}/{len(records)}", file=sys.stderr, flush=True)
    chunks_temp_path.replace(chunks_path)

    source_manifest_path = processed_root / "source_manifest.jsonl"
    write_jsonl(source_manifest_path, records)
    errors_path = processed_root / "conversion_errors.jsonl"
    write_jsonl(errors_path, errors)

    source_counts = Counter(record["source_kind"] for record in records)
    duplicate_count = sum(1 for record in records if record.get("duplicate_of"))
    page_count = sum(int(record.get("page_count", 0)) for record in records)
    blank_page_count = sum(int(record.get("blank_page_count", 0)) for record in records)
    unit_count = sum(int(record.get("unit_count", 0)) for record in records)
    manifest = {
        "dataset_version": DATASET_VERSION,
        "generated_on": date.today().isoformat(),
        "source_root": repo_relative(raw_root),
        "markdown_root": repo_relative(markdown_root),
        "chunks_file": repo_relative(chunks_path),
        "source_manifest": repo_relative(source_manifest_path),
        "conversion_errors": repo_relative(errors_path),
        "pipeline": "PDF/XLS -> Markdown -> page/ability-unit chunks -> embeddings -> Supabase",
        "extraction": {
            "pdf": "PyMuPDF sorted text extraction; repeated edge headers and page numbers removed",
            "xls": "xlrd cell extraction grouped by NCS ability unit",
            "ocr_used": False,
        },
        "chunking": {
            "chunk_size_chars": chunk_size,
            "chunk_overlap_chars": chunk_overlap,
            "pdf_boundary": "page",
            "xls_boundary": "NCS ability unit",
        },
        "counts": {
            "source_files": len(sources),
            "converted_sources": len(records),
            "pdf_files": source_counts.get("pdf", 0),
            "xls_files": source_counts.get("xls", 0),
            "exact_duplicates_excluded_from_rag": duplicate_count,
            "pdf_pages": page_count,
            "blank_or_near_blank_pdf_pages": blank_page_count,
            "xls_ability_units": unit_count,
            "chunks": chunk_count,
            "chunks_by_source_kind": dict(sorted(chunk_counts_by_kind.items())),
            "chunks_by_top_category": dict(sorted(chunk_counts_by_category.items())),
            "conversion_errors": len(errors),
        },
        "source_policy": {
            "source_url": SOURCE_URL,
            "license_notice": LICENSE_NOTICE,
            "version_review": "원본 파일명과 능력단위 코드의 연도/버전을 메타데이터로 보존",
        },
    }
    manifest_path = processed_root / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "ready": not errors and chunk_count > 0,
        "dataset_version": DATASET_VERSION,
        **manifest["counts"],
        "dataset_manifest": repo_relative(manifest_path),
        "chunks_file": repo_relative(chunks_path),
    }
    if errors:
        raise RuntimeError(
            f"{len(errors)} source conversion(s) failed; inspect {repo_relative(errors_path)}"
        )
    return result


def inventory_sources(raw_root: Path) -> list[SourceFile]:
    paths = sorted(
        [*raw_root.rglob("*.pdf"), *raw_root.rglob("*.xls")],
        key=lambda item: item.relative_to(raw_root).as_posix().casefold(),
    )
    provisional: list[dict[str, Any]] = []
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        relative_path = path.relative_to(raw_root).as_posix()
        source_kind = path.suffix.casefold().lstrip(".")
        digest = sha256_file(path)
        path_digest = hashlib.sha256(relative_path.casefold().encode("utf-8")).hexdigest()[:16]
        item = {
            "path": path,
            "relative_path": relative_path,
            "source_kind": source_kind,
            "source_id": f"ncs-src-{path_digest}",
            "document_id": f"ncs-{source_kind}-{digest[:16]}",
            "sha256": digest,
        }
        provisional.append(item)
        grouped[(source_kind, digest)].append(item)

    duplicate_of_by_source: dict[str, str] = {}
    for items in grouped.values():
        canonical = min(items, key=lambda item: (len(item["relative_path"]), item["relative_path"]))
        for item in items:
            if item is not canonical:
                duplicate_of_by_source[item["source_id"]] = canonical["source_id"]

    return [
        SourceFile(
            path=item["path"],
            relative_path=item["relative_path"],
            source_kind=item["source_kind"],
            source_id=item["source_id"],
            document_id=item["document_id"],
            sha256=item["sha256"],
            duplicate_of=duplicate_of_by_source.get(item["source_id"]),
        )
        for item in provisional
    ]


def convert_source_to_markdown(
    *,
    source: SourceFile,
    raw_root: Path,
    markdown_root: Path,
    force: bool,
) -> dict[str, Any]:
    hierarchy = hierarchy_parts(source.path, raw_root)
    top_category = hierarchy[0] if hierarchy else "미분류"
    destination = markdown_root / source.source_kind / safe_component(top_category) / f"{source.source_id}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    title = source_title(source.path, hierarchy)
    base_metadata: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "source_id": source.source_id,
        "document_id": source.document_id,
        "source_kind": source.source_kind,
        "source_name": title,
        "original_path": repo_relative(source.path),
        "sha256": source.sha256,
        "duplicate_of": source.duplicate_of or "",
        "source_url": SOURCE_URL,
        "license": LICENSE_NOTICE,
        "ncs_hierarchy": hierarchy,
        "top_category": top_category,
        "source_year": source_year(source.path.name),
        "conversion_method": "pymupdf" if source.source_kind == "pdf" else "xlrd",
    }

    if destination.exists() and not force:
        existing_metadata, _ = read_markdown(destination)
        if existing_metadata.get("sha256") == source.sha256:
            return {
                **existing_metadata,
                "converted_markdown": repo_relative(destination),
                "conversion_status": "reused",
            }

    if source.source_kind == "pdf":
        body, details = pdf_to_markdown_body(source.path, title=title)
    elif source.source_kind == "xls":
        body, details = xls_to_markdown_body(source.path, title=title)
    else:  # inventory_sources limits this, but keep the contract explicit.
        raise ValueError(f"unsupported NCS source type: {source.source_kind}")

    metadata = {**base_metadata, **details}
    destination.write_text(render_markdown(metadata, body), encoding="utf-8", newline="\n")
    return {
        **metadata,
        "converted_markdown": repo_relative(destination),
        "conversion_status": "converted",
    }


def pdf_to_markdown_body(path: Path, *, title: str) -> tuple[str, dict[str, Any]]:
    with fitz.open(path) as document:
        raw_pages = [normalize_page_text(page.get_text("text", sort=True)) for page in document]
    repeated_edges = repeated_edge_lines(raw_pages)
    pages = [remove_repeated_edges(text, repeated_edges) for text in raw_pages]
    meaningful_chars = sum(len(text) for text in pages)
    blank_pages = sum(1 for text in pages if not is_meaningful(text))
    classification_codes = sorted(set(NCS_CODE_PATTERN.findall("\n".join(pages))))

    lines = [f"# {title}", "", f"> 원본: `{path.name}`", "> 변환: PyMuPDF 텍스트 추출", ""]
    for page_number, text in enumerate(pages, start=1):
        lines.extend([f"## Page {page_number}", ""])
        if is_meaningful(text):
            lines.extend([text, ""])
        else:
            lines.extend(["> 추출 가능한 본문 텍스트 없음", ""])
    return "\n".join(lines).rstrip() + "\n", {
        "page_count": len(pages),
        "blank_page_count": blank_pages,
        "extracted_char_count": meaningful_chars,
        "repeated_edge_lines_removed": sorted(repeated_edges),
        "source_year": latest_ncs_code_year(classification_codes) or source_year(path.name),
    }


def xls_to_markdown_body(path: Path, *, title: str) -> tuple[str, dict[str, Any]]:
    try:
        import xlrd
    except ModuleNotFoundError as exc:
        raise RuntimeError("xlrd is required for NCS .xls conversion; install requirements-data.txt") from exc

    book = xlrd.open_workbook(path, on_demand=True)
    lines = [f"# {title}", "", f"> 원본: `{path.name}`", "> 변환: xlrd 셀 텍스트 추출", ""]
    unit_count = 0
    row_count = 0
    classification_codes: list[str] = []
    try:
        for sheet in book.sheets():
            lines.extend([f"# Sheet: {clean_cell_text(sheet.name)}", ""])
            for row_index in range(sheet.nrows):
                cells = []
                for column_index in range(sheet.ncols):
                    value = format_xls_cell(sheet, row_index, column_index, book.datemode)
                    if value:
                        cells.append((column_index + 1, value))
                if not cells:
                    continue
                row_count += 1
                classification_code = classification_code_from_cells(cells)
                if classification_code:
                    unit_count += 1
                    classification_codes.append(classification_code)
                    lines.extend([f"## 능력단위: {classification_code}", ""])
                lines.extend([f"### Row {row_index + 1}", ""])
                if len(cells) == 2 and cells[0][1].rstrip().endswith(":"):
                    label = cells[0][1].rstrip().rstrip(":").strip()
                    lines.extend([f"**{label}:** {cells[1][1]}", ""])
                else:
                    for column, value in cells:
                        indented = value.replace("\n", "\n  ")
                        lines.append(f"- 열 {column}: {indented}")
                    lines.append("")
    finally:
        book.release_resources()
    body = "\n".join(lines).rstrip() + "\n"
    return body, {
        "sheet_count": book.nsheets,
        "nonempty_row_count": row_count,
        "unit_count": unit_count,
        "classification_codes": classification_codes,
        "extracted_char_count": len(body),
        "source_year": latest_ncs_code_year(classification_codes),
    }


def chunks_from_markdown(
    *,
    markdown_path: Path,
    record: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
) -> Iterator[dict[str, Any]]:
    metadata, body = read_markdown(markdown_path)
    if metadata.get("sha256") != record.get("sha256"):
        raise RuntimeError(f"Markdown source hash mismatch: {markdown_path}")
    if record["source_kind"] == "pdf":
        yield from pdf_chunks(
            body=body,
            record=record,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    else:
        yield from xls_chunks(
            body=body,
            record=record,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def pdf_chunks(
    *, body: str, record: dict[str, Any], chunk_size: int, chunk_overlap: int
) -> Iterator[dict[str, Any]]:
    matches = list(PAGE_HEADING.finditer(body))
    for match_index, match in enumerate(matches):
        page_number = int(match.group(1))
        end = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(body)
        page_text = body[match.end() : end].strip()
        if not is_meaningful(page_text) or page_text.startswith("> 추출 가능한 본문 텍스트 없음"):
            continue
        for chunk_index, piece in enumerate(
            split_text(page_text, chunk_size=chunk_size, overlap=chunk_overlap), start=1
        ):
            yield chunk_row(
                record=record,
                section=f"Page {page_number}",
                text=piece,
                chunk_id=f"{record['document_id']}-p{page_number:04d}-c{chunk_index:03d}",
                page=page_number,
                extra_metadata={"page": page_number},
            )


def xls_chunks(
    *, body: str, record: dict[str, Any], chunk_size: int, chunk_overlap: int
) -> Iterator[dict[str, Any]]:
    matches = list(UNIT_HEADING.finditer(body))
    sections: list[tuple[str, str]] = []
    if matches:
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections.append((match.group(1).strip(), body[match.end() : end].strip()))
    else:
        sections.append((record["source_name"], body))

    chunk_sequence = 0
    for unit_code, section_text in sections:
        if not is_meaningful(section_text):
            continue
        for piece in split_text(section_text, chunk_size=chunk_size, overlap=chunk_overlap):
            chunk_sequence += 1
            yield chunk_row(
                record=record,
                section=f"능력단위 {unit_code}",
                text=piece,
                chunk_id=f"{record['document_id']}-u{chunk_sequence:04d}",
                page=None,
                extra_metadata={"ncs_unit_code": unit_code},
            )


def chunk_row(
    *,
    record: dict[str, Any],
    section: str,
    text: str,
    chunk_id: str,
    page: int | None,
    extra_metadata: dict[str, Any],
) -> dict[str, Any]:
    hierarchy_text = " > ".join(record["ncs_hierarchy"])
    context = [
        f"자료명: {record['source_name']}",
        f"NCS 분류: {hierarchy_text}",
        f"구간: {section}",
    ]
    content = "\n".join(context) + "\n\n" + text.strip()
    source_year_value = record.get("source_year")
    review_status = "needs_version_review" if source_year_value else "needs_review"
    metadata = {
        "source_id": record["source_id"],
        "source_url": SOURCE_URL,
        "license": LICENSE_NOTICE,
        "section": section,
        "source_file": record["converted_markdown"],
        "original_file": record["original_path"],
        "original_source_type": record["source_kind"],
        "sha256": record["sha256"],
        "dataset_version": DATASET_VERSION,
        "ncs_hierarchy": record["ncs_hierarchy"],
        "top_category": record["top_category"],
        "source_year": source_year_value,
        "review_status": review_status,
        "tags": ["NCS", *record["ncs_hierarchy"], record["source_kind"]],
        **extra_metadata,
    }
    return {
        "chunk_id": chunk_id,
        "source_id": record["source_id"],
        "document_id": record["document_id"],
        "source_name": record["source_name"],
        "source_type": "md",
        "page": page,
        "text": content,
        "char_count": len(content),
        "token_estimate": max(1, math.ceil(len(content) / 4)),
        "metadata": metadata,
        **metadata,
    }


def split_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    cleaned = normalize_page_text(text)
    if len(cleaned) <= chunk_size:
        return [cleaned] if is_meaningful(cleaned) else []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        proposed_end = min(len(cleaned), start + chunk_size)
        end = proposed_end
        if proposed_end < len(cleaned):
            minimum_break = start + int(chunk_size * 0.6)
            candidates = [
                cleaned.rfind("\n\n", minimum_break, proposed_end),
                cleaned.rfind("\n", minimum_break, proposed_end),
                cleaned.rfind(" ", minimum_break, proposed_end),
            ]
            boundary = max(candidates)
            if boundary >= minimum_break:
                end = boundary
        piece = cleaned[start:end].strip()
        if is_meaningful(piece):
            chunks.append(piece)
        if end >= len(cleaned):
            break
        next_start = max(start + 1, end - overlap)
        start = next_start
    return chunks


def normalize_page_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHARS.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line for line in text.splitlines() if not PAGE_NUMBER_LINE.fullmatch(line.strip())]
    return "\n".join(lines).strip()


def repeated_edge_lines(pages: list[str]) -> set[str]:
    nonempty_pages = [page for page in pages if page.strip()]
    if len(nonempty_pages) < 3:
        return set()
    edge_counts: Counter[str] = Counter()
    for text in nonempty_pages:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in {*lines[:3], *lines[-3:]}:
            if 2 <= len(line) <= 120:
                edge_counts[line] += 1
    threshold = max(3, math.ceil(len(nonempty_pages) * 0.5))
    return {line for line, count in edge_counts.items() if count >= threshold}


def remove_repeated_edges(text: str, repeated: set[str]) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    edge_indexes = set(nonempty_indexes[:3] + nonempty_indexes[-3:])
    kept = [line for index, line in enumerate(lines) if not (index in edge_indexes and line.strip() in repeated)]
    return normalize_page_text("\n".join(kept))


def hierarchy_parts(path: Path, raw_root: Path) -> list[str]:
    return [strip_number_prefix(part) for part in path.relative_to(raw_root).parts[:-1]]


def source_title(path: Path, hierarchy: list[str]) -> str:
    stem = strip_number_prefix(path.stem)
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    if path.suffix.casefold() == ".xls" and hierarchy:
        return f"NCS 능력단위 보고서 - {hierarchy[-1]}"
    stem = stem.replace("+", " ").replace("_", " ").strip()
    stem = re.sub(r"^LM\d{8,}\s*", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"^\d{4}년도\s*NCS\s*학습모듈\s*", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"(?:19|20)\d{6}\s*수정.*$", "", stem)
    stem = re.sub(r"\s*(?:19|20)\d{2}(?:\s*\d+)?$", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" _-")
    return stem or (hierarchy[-1] if hierarchy else path.stem)


def source_year(filename: str) -> int | None:
    years = [int(value) for value in YEAR_PATTERN.findall(filename)]
    return years[-1] if years else None


def latest_ncs_code_year(values: Iterable[str]) -> int | None:
    two_digit_years: list[int] = []
    for value in values:
        if re.fullmatch(r"\d{2}", value):
            two_digit_years.append(int(value))
            continue
        match = NCS_CODE_PATTERN.search(value)
        if match:
            two_digit_years.append(int(match.group(1)))
    years = [2000 + value if value <= 49 else 1900 + value for value in two_digit_years]
    return max(years) if years else None


def strip_number_prefix(value: str) -> str:
    return NUMBERED_PREFIX.sub("", value).strip()


def safe_component(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    return value or "uncategorized"


def classification_code_from_cells(cells: list[tuple[int, str]]) -> str | None:
    for index, (_, value) in enumerate(cells):
        if "분류번호" not in value.replace(" ", ""):
            continue
        for _, candidate in cells[index + 1 :]:
            compact = candidate.strip()
            if re.search(r"\d{8,}.*v\d+", compact, flags=re.IGNORECASE):
                return compact.splitlines()[0]
    return None


def format_xls_cell(sheet: Any, row: int, column: int, datemode: int) -> str:
    value = sheet.cell_value(row, column)
    if value in (None, ""):
        return ""
    cell_type = sheet.cell_type(row, column)
    try:
        import xlrd
    except ModuleNotFoundError:
        xlrd = None
    if xlrd is not None and cell_type == xlrd.XL_CELL_DATE:
        parts = xlrd.xldate_as_datetime(value, datemode)
        return parts.isoformat(sep=" ")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return clean_cell_text(str(value))


def clean_cell_text(value: str) -> str:
    return normalize_page_text(value).replace("|", "\\|")


def is_meaningful(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return len(compact) >= 30


def render_markdown(metadata: dict[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"


def read_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"Markdown front matter missing: {path}")
    try:
        frontmatter, body = text[4:].split("\n---\n", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"Markdown front matter is not terminated: {path}") from exc
    metadata = yaml.safe_load(frontmatter) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"Markdown front matter must be a mapping: {path}")
    return metadata, body.lstrip("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


if __name__ == "__main__":
    sys.exit(main())
