"""Prepare the local LessonPack AI MVP dataset.

This script intentionally works on local `data/` files. Raw source data and
processed artifacts are ignored by Git, while the script itself is tracked so
the preparation step is reproducible.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


DATASET_VERSION = "mvp-dataset-v0.1"
NCS_VERSION = "mvp-ncs-v0.1"
CREATED_AT = date.today().isoformat()


@dataclass(frozen=True)
class Source:
    source_id: str
    path: Path
    source_name: str
    source_url: str
    license: str
    use_for: list[str]
    max_chunks: int
    tags: list[str]
    section: str


@dataclass(frozen=True)
class FileAlias:
    role: str
    source_pattern: str
    alias_name: str
    selected: bool = True


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
MATERIALS = RAW / "materials"
RAW_NCS_ORIGINAL = MATERIALS / "ncs"
RAW_NCS = RAW / "ncs"
RAW_CURRICULUM = RAW / "curriculum"
RAW_SYNTHETIC = RAW / "synthetic"
PROCESSED = DATA / "processed"
GOLD = DATA / "gold"
CONCEPT_SYNONYMS = {
    "함수": ["function", "def"],
    "매개변수": ["parameter", "argument"],
    "자료구조": ["data-structure", "data structure", "list", "dictionary"],
    "평가": ["assessment", "rubric"],
    "객관식": ["assessment", "multiple choice", "mcq"],
    "스크립트": ["script", "script-language"],
    "라이브러리": ["library"],
    "탐색": ["search"],
    "정렬": ["sort"],
}


PDF_ALIASES = [
    FileAlias("ncs_source_pdf", "*0231*.pdf", "LM2001020231_23v5_programming_language_use.pdf"),
    FileAlias(
        "ncs_source_pdf",
        "*0230*.pdf",
        "LM2001020230_23v5_programming_language_application.pdf",
    ),
    FileAlias("ncs_source_pdf", "*0235*.pdf", "LM2001020235_23v1_data_structure_use.pdf"),
]

MD_ALIASES = [
    FileAlias("ncs_converted_md", "*0231*.md", "LM2001020231_23v5_programming_language_use.md"),
    FileAlias(
        "ncs_converted_md",
        "*0230*.md",
        "LM2001020230_23v5_programming_language_application.md",
    ),
    FileAlias("ncs_converted_md", "*0235*.md", "LM2001020235_23v1_data_structure_use.md"),
]


def main() -> None:
    ensure_directories()
    file_map = copy_ncs_alias_files()
    file_map.extend(copy_ncs_reports())
    file_map.extend(copy_old_ncs_reports())

    write_yaml(RAW_CURRICULUM / "curriculum_python_prompt_automation.yaml", curriculum_data())
    write_yaml(RAW_NCS / "ncs_application_sw_programming.yaml", ncs_yaml_data())
    write_yaml(RAW_SYNTHETIC / "practice_examples.yaml", practice_examples_data())
    write_yaml(GOLD / "human_eval_rubric.yaml", human_eval_rubric_data())
    write_yaml(GOLD / "usability_test_form.yaml", usability_test_form_data())
    write_yaml(GOLD / "ncs_yaml_review_checklist.yaml", ncs_yaml_review_checklist_data())

    sources = build_sources()
    write_yaml(PROCESSED / "selected_sources.yaml", selected_sources_data(sources))

    chunks = build_chunks(sources)
    write_jsonl(PROCESSED / "chunks.jsonl", chunks)
    write_chunk_index(PROCESSED / "chunk_index.csv", chunks)

    write_source_file_map(PROCESSED / "source_file_map.csv", file_map, sources)

    retrieval_gold = retrieval_gold_data(chunks)
    write_jsonl(GOLD / "retrieval_gold.jsonl", retrieval_gold)
    generation_gold = generation_gold_data()
    write_yaml(GOLD / "generation_gold.yaml", generation_gold)

    manifest = dataset_manifest_data(chunks, retrieval_gold, generation_gold, sources)
    write_json(PROCESSED / "dataset_manifest.json", manifest)

    print(
        json.dumps(
            {
                "dataset_version": DATASET_VERSION,
                "sources": len(sources),
                "chunks": len(chunks),
                "retrieval_gold": len(retrieval_gold),
                "generation_gold": len(generation_gold["cases"]),
                "ncs_mapped_files": len([item for item in file_map if item["role"].startswith("ncs_")]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def ensure_directories() -> None:
    for path in [
        RAW_CURRICULUM,
        RAW_NCS / "source_pdf",
        RAW_NCS / "converted_md",
        RAW_NCS / "reports",
        RAW_NCS / "old",
        RAW_SYNTHETIC,
        PROCESSED,
        GOLD,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def copy_ncs_alias_files() -> list[dict[str, Any]]:
    file_map: list[dict[str, Any]] = []
    for alias in PDF_ALIASES:
        source = find_one(RAW_NCS_ORIGINAL, alias.source_pattern)
        destination = RAW_NCS / "source_pdf" / alias.alias_name
        shutil.copy2(source, destination)
        file_map.append(file_map_row(alias.role, source, destination, alias.selected))

    for alias in MD_ALIASES:
        source = find_one(RAW_NCS_ORIGINAL, alias.source_pattern)
        destination = RAW_NCS / "converted_md" / alias.alias_name
        shutil.copy2(source, destination)
        file_map.append(file_map_row(alias.role, source, destination, alias.selected))
    return file_map


def copy_ncs_reports() -> list[dict[str, Any]]:
    file_map: list[dict[str, Any]] = []
    reports = sorted(RAW_NCS_ORIGINAL.glob("report*.xls"), key=lambda path: path.name)
    for index, source in enumerate(reports, start=1):
        destination = RAW_NCS / "reports" / f"ncs_report_{index:03d}.xls"
        shutil.copy2(source, destination)
        file_map.append(file_map_row("ncs_report", source, destination, selected=False))
    return file_map


def copy_old_ncs_reports() -> list[dict[str, Any]]:
    file_map: list[dict[str, Any]] = []
    old_root = RAW_NCS_ORIGINAL / "old"
    if not old_root.exists():
        return file_map
    reports = sorted(old_root.glob("report*.xls"), key=lambda path: path.name)
    for index, source in enumerate(reports, start=1):
        destination = RAW_NCS / "old" / f"ncs_report_old_{index:03d}.xls"
        shutil.copy2(source, destination)
        file_map.append(file_map_row("ncs_old_report", source, destination, selected=False))
    return file_map


def file_map_row(role: str, source: Path, destination: Path, selected: bool) -> dict[str, Any]:
    return {
        "role": role,
        "original_path": rel(source),
        "alias_path": rel(destination),
        "selected_for_mvp": selected,
    }


def find_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matched {root / pattern}")
    return matches[0]


def build_sources() -> list[Source]:
    return [
        Source(
            "python-functions",
            MATERIALS / "tutorial_functions.md",
            "Python Tutorial - Defining Functions",
            "https://docs.python.org/3/tutorial/controlflow.html#defining-functions",
            "Python Software Foundation License Version 2",
            ["lesson_plan", "practice", "assessment", "retrieval_gold"],
            9,
            ["python", "function", "def", "parameter", "return"],
            "4.8 Defining Functions",
        ),
        Source(
            "python-data-structures",
            MATERIALS / "python_tutorial_data_structures.md",
            "Python Tutorial - Data Structures",
            "https://docs.python.org/3/tutorial/datastructures.html",
            "Python Software Foundation License Version 2",
            ["lesson_plan", "practice", "assessment", "retrieval_gold"],
            18,
            ["python", "list", "dictionary", "stack", "queue", "data-structure"],
            "5. Data Structures",
        ),
        Source(
            "pandas-10min",
            MATERIALS / "10min.rst",
            "pandas - 10 minutes to pandas",
            "https://pandas.pydata.org/docs/user_guide/10min.html",
            "BSD 3-Clause",
            ["optional_extension"],
            6,
            ["pandas", "Series", "DataFrame", "data-analysis"],
            "10 minutes to pandas",
        ),
        Source(
            "ncs-programming-language-use",
            RAW_NCS / "converted_md" / "LM2001020231_23v5_programming_language_use.md",
            "NCS Learning Module - 프로그래밍 언어 활용",
            "https://www.ncs.go.kr/",
            "NCS 학습모듈 교육 목적 활용, 출처 명시 필요",
            ["ncs_alignment", "practice", "assessment"],
            5,
            ["NCS", "programming", "script-language", "structured-programming"],
            "프로그래밍 언어 활용",
        ),
        Source(
            "ncs-programming-language-application",
            RAW_NCS / "converted_md" / "LM2001020230_23v5_programming_language_application.md",
            "NCS Learning Module - 프로그래밍 언어 응용",
            "https://www.ncs.go.kr/",
            "NCS 학습모듈 교육 목적 활용, 출처 명시 필요",
            ["ncs_alignment", "practice", "assessment"],
            5,
            ["NCS", "programming", "library", "language-feature"],
            "프로그래밍 언어 응용",
        ),
        Source(
            "ncs-data-structure-use",
            RAW_NCS / "converted_md" / "LM2001020235_23v1_data_structure_use.md",
            "NCS Learning Module - 자료구조 활용",
            "https://www.ncs.go.kr/",
            "NCS 학습모듈 교육 목적 활용, 출처 명시 필요",
            ["ncs_alignment", "retrieval_gold", "assessment"],
            5,
            ["NCS", "data-structure", "algorithm", "search", "sort"],
            "자료구조 활용",
        ),
    ]


def build_chunks(sources: list[Source]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for source in sources:
        if not source.path.exists():
            raise FileNotFoundError(f"Missing selected source: {source.path}")
        raw_text = source.path.read_text(encoding="utf-8", errors="replace")
        if source.source_id.startswith("ncs-"):
            text = extract_ncs_relevant_text(raw_text)
        elif source.source_id == "pandas-10min":
            text = clean_rst(raw_text)
        else:
            text = clean_markdown(raw_text)

        source_chunks = chunk_text(text, max_chunks=source.max_chunks)
        for index, text_chunk in enumerate(source_chunks, start=1):
            chunks.append(
                {
                    "chunk_id": f"{source.source_id}-c{index:03d}",
                    "source_id": source.source_id,
                    "source_name": source.source_name,
                    "source_url": source.source_url,
                    "license": source.license,
                    "section": source.section,
                    "source_file": rel(source.path),
                    "text": text_chunk,
                    "char_count": len(text_chunk),
                    "token_estimate": max(1, round(len(text_chunk) / 4)),
                    "tags": source.tags,
                    "review_status": "needs_review",
                }
            )
    return chunks


def extract_ncs_relevant_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    selected: list[str] = []
    include_next = 0
    keywords = [
        "대분류/",
        "중분류/",
        "소분류/",
        "세분류/",
        "능력단위/",
        "학습 1.",
        "학습 2.",
        "학습 3.",
        "필요 지식",
        "수행 내용",
        "교수",
        "평가",
    ]
    for line in lines:
        if not line:
            continue
        if any(keyword in line for keyword in keywords):
            selected.append(line)
            include_next = 4
        elif include_next > 0:
            selected.append(line)
            include_next -= 1

    text = "\n".join(selected)
    text = re.sub(r"## Page \d+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return clean_markdown(text)


def clean_rst(text: str) -> str:
    text = re.sub(r"\.\. _[^:]+:\n", "", text)
    text = re.sub(r"\.\. ipython:: ?(?:python)?", "Example:", text)
    text = re.sub(r":(?:class|func|meth|ref):`([^`]+)`", r"\1", text)
    text = text.replace("{{ header }}", "")
    return clean_markdown(text)


def clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```yaml.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chunks: int, target_size: int = 800) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > 1200:
            parts = split_long_paragraph(paragraph, target_size)
        else:
            parts = [paragraph]
        for part in parts:
            if not current:
                current = part
            elif len(current) + len(part) + 2 <= 1200:
                current = f"{current}\n\n{part}"
            else:
                if len(current) >= 250:
                    chunks.append(current)
                current = part
            if len(chunks) >= max_chunks:
                return chunks[:max_chunks]
    if current and len(chunks) < max_chunks:
        chunks.append(current)
    return [chunk for chunk in chunks if len(chunk.strip()) >= 120][:max_chunks]


def split_long_paragraph(paragraph: str, target_size: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?。])\s+|\n", paragraph)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current) + len(sentence) + 1 <= target_size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                parts.append(current)
            current = sentence.strip()
    if current:
        parts.append(current)
    return parts


def retrieval_gold_data(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        ("q001", "Python 함수 정의와 def 키워드를 설명하는 교안을 생성하라", ["def", "function"]),
        ("q002", "Python 함수의 매개변수와 return 사용을 설명하라", ["return", "parameter"]),
        ("q003", "Python list 메서드와 append, pop을 이용한 실습을 설계하라", ["list", "append"]),
        ("q004", "Python dictionary와 key-value 개념을 설명하라", ["dictionary", "key"]),
        ("q005", "NCS 자료구조 활용 능력과 Python list/dict 실습을 연결하라", ["자료구조", "NCS"]),
        ("q006", "프로그래밍 언어 활용 NCS와 스크립트 언어 실습을 연결하라", ["스크립트", "NCS"]),
        ("q007", "프로그래밍 언어 응용 NCS와 라이브러리 활용 실습을 연결하라", ["라이브러리", "NCS"]),
        ("q008", "pandas DataFrame 생성과 데이터 분석 기초 실습을 설계하라", ["DataFrame", "pandas"]),
        ("q009", "Python 함수 기반 텍스트 자동화 실습의 평가 기준을 제시하라", ["function", "평가"]),
        ("q010", "검색 근거에 기반한 객관식 평가 문항을 생성하라", ["assessment", "NCS"]),
    ]
    rows = []
    for query_id, query, concepts in specs:
        expected_ids = find_matching_chunk_ids(chunks, concepts)
        rows.append(
            {
                "query_id": query_id,
                "query": query,
                "expected_chunk_ids": expected_ids[:3],
                "required_concepts": concepts,
                "synthetic": True,
                "authoring_method": "manual_synthetic_seed",
            }
        )
    return rows


def find_matching_chunk_ids(chunks: list[dict[str, Any]], concepts: list[str]) -> list[str]:
    scored: list[tuple[int, int, int, str]] = []
    for index, chunk in enumerate(chunks):
        haystack = chunk_searchable_text(chunk)
        concept_hits = 0
        occurrence_score = 0
        for concept in concepts:
            variants = concept_variants(concept)
            hits = sum(haystack.count(variant) for variant in variants)
            if hits:
                concept_hits += 1
                occurrence_score += min(hits, 5)
        if concept_hits:
            scored.append((concept_hits, occurrence_score, -index, chunk["chunk_id"]))

    if not scored:
        return [chunks[0]["chunk_id"]]
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [chunk_id for _, _, _, chunk_id in scored]


def concept_variants(concept: str) -> list[str]:
    variants = [concept, *CONCEPT_SYNONYMS.get(concept, [])]
    return [variant.casefold().strip() for variant in variants if variant.strip()]


def chunk_searchable_text(chunk: dict[str, Any]) -> str:
    values = [
        chunk.get("chunk_id", ""),
        chunk.get("source_id", ""),
        chunk.get("source_name", ""),
        chunk.get("section", ""),
        chunk.get("text", ""),
        " ".join(str(tag) for tag in chunk.get("tags", [])),
    ]
    return " ".join(values).casefold()


def curriculum_data() -> dict[str, Any]:
    return {
        "curriculum_id": "curr-python-prompt-automation",
        "synthetic": True,
        "created_for": "LessonPack AI MVP",
        "created_at": CREATED_AT,
        "authoring_method": "manual_synthetic",
        "course_title": "생성형 AI 활용 Python 기초",
        "lesson_title": "Python 함수와 프롬프트 자동화 실습",
        "learner_profile": "Python 변수, 조건문, 반복문을 학습한 직업훈련 수강생",
        "prerequisites": ["변수", "조건문", "반복문", "기초 입출력"],
        "learning_objectives": [
            "Python 함수를 정의하고 호출할 수 있다.",
            "입력값을 받아 문자열을 변환하는 자동화 함수를 작성할 수 있다.",
            "list와 dictionary를 활용해 간단한 데이터를 처리할 수 있다.",
            "생성형 AI가 제안한 코드를 근거 자료와 비교해 검토할 수 있다.",
        ],
        "ncs_alignment": {
            "primary_unit_code": "2001020231",
            "primary_unit_name": "프로그래밍 언어 활용",
            "supporting_unit_codes": ["2001020230", "2001020235"],
        },
        "lesson_duration_min": 120,
        "expected_outputs": ["함수 기반 텍스트 변환 코드", "실행 결과 캡처", "핵심 개념 설명 3문장"],
    }


def ncs_yaml_data() -> dict[str, Any]:
    return {
        "dataset_version": NCS_VERSION,
        "created_at": CREATED_AT,
        "synthetic": False,
        "authoring_method": "manual_summary_from_converted_md",
        "ncs_domain": {
            "large_category": "20 정보통신",
            "medium_category": "01 정보기술",
            "small_category": "02 정보기술개발",
            "detail_category": "02 응용SW엔지니어링",
        },
        "selected_units": [
            {
                "unit_code": "2001020231",
                "unit_name": "프로그래밍 언어 활용",
                "source_md": "data/raw/ncs/converted_md/LM2001020231_23v5_programming_language_use.md",
                "selected_reason": "Python 기초 문법, 구조적 프로그래밍, 스크립트 언어 활용과 직접 연결",
                "learning_topics": ["구조적 프로그래밍 언어 활용", "객체지향 프로그래밍 언어 활용", "스크립트 언어 활용"],
            },
            {
                "unit_code": "2001020230",
                "unit_name": "프로그래밍 언어 응용",
                "source_md": "data/raw/ncs/converted_md/LM2001020230_23v5_programming_language_application.md",
                "selected_reason": "함수, 라이브러리, 자동화 실습과 연결",
                "learning_topics": ["언어 특성 활용", "라이브러리 활용"],
            },
            {
                "unit_code": "2001020235",
                "unit_name": "자료구조 활용",
                "source_md": "data/raw/ncs/converted_md/LM2001020235_23v1_data_structure_use.md",
                "selected_reason": "Python list, dictionary, 정렬·탐색 실습과 연결",
                "learning_topics": ["기본 자료구조 활용", "정렬 및 탐색 알고리즘 활용"],
            },
        ],
        "ncs_unit_summary": {
            "primary_unit_code": "2001020231",
            "primary_unit_name": "프로그래밍 언어 활용",
            "source_url": "https://www.ncs.go.kr/",
            "selected_reason": "생성형 AI 활용 Python 기초 과정에서 함수 작성, 자료구조 활용, 자동화 스크립트 작성 역량을 설명하기에 가장 적합",
            "performance_criteria": [
                "프로그래밍 언어의 기본 구조와 문법을 활용할 수 있다.",
                "스크립트 언어를 활용해 간단한 기능을 구현할 수 있다.",
                "자료구조를 활용해 입력 데이터를 처리할 수 있다.",
            ],
            "knowledge": ["프로그래밍 기초", "함수와 매개변수", "자료구조와 알고리즘 기초"],
            "skills": ["Python 기초 코드 작성", "함수 기반 자동화 스크립트 작성", "list와 dictionary를 활용한 데이터 처리"],
            "attitude": ["생성 결과의 근거를 확인하는 태도", "윤리와 저작권을 고려하는 태도"],
            "license_note": "NCS 학습모듈은 출처를 명시하고 교육적 목적으로 활용한다. 도표, 사진, 삽화 등 제3자 저작물은 재사용하지 않는다.",
        },
    }


def practice_examples_data() -> dict[str, Any]:
    return {
        "synthetic": True,
        "created_for": "LessonPack AI MVP",
        "created_at": CREATED_AT,
        "authoring_method": "manual_synthetic",
        "examples": [
            {
                "example_id": "practice-function-001",
                "title": "문자열 정리 함수 만들기",
                "task": "사용자 입력 문자열의 앞뒤 공백을 제거하고 소문자로 변환하는 함수를 작성한다.",
                "required_concepts": ["def", "parameter", "return", "str.strip", "str.lower"],
                "expected_submission": "함수 코드, 테스트 입력 3개, 실행 결과",
            },
            {
                "example_id": "practice-function-002",
                "title": "프롬프트 템플릿 생성 함수 만들기",
                "task": "주제와 대상자를 입력받아 학습용 프롬프트 문장을 반환하는 함수를 작성한다.",
                "required_concepts": ["def", "f-string", "return", "docstring"],
                "expected_submission": "함수 코드, docstring, 예시 호출 결과",
            },
            {
                "example_id": "practice-function-003",
                "title": "list와 dictionary로 평가 결과 요약하기",
                "task": "수강생별 점수 dictionary 목록을 받아 평균과 통과 여부를 계산하는 함수를 작성한다.",
                "required_concepts": ["list", "dictionary", "loop", "function"],
                "expected_submission": "함수 코드, 샘플 데이터, 출력 결과",
            },
        ],
    }


def human_eval_rubric_data() -> dict[str, Any]:
    return {
        "synthetic": True,
        "created_for": "LessonPack AI MVP",
        "created_at": CREATED_AT,
        "authoring_method": "manual_synthetic",
        "scale": "1-5",
        "criteria": [
            {"name": "교안 적합성", "pass_score": 4, "description": "차시 목표와 강의 흐름이 연결되는지 평가"},
            {"name": "실습 적합성", "pass_score": 4, "description": "수강생이 120분 안에 수행 가능한지 평가"},
            {"name": "평가 문항 품질", "pass_score": 3, "description": "정답, 해설, 난이도가 일관적인지 평가"},
            {"name": "근거 신뢰도", "pass_score": 4, "description": "Python/NCS chunk citation이 핵심 항목에 붙었는지 평가"},
            {"name": "수정 편의성", "pass_score": 3, "description": "강사가 문장을 쉽게 수정할 수 있는지 평가"},
        ],
    }


def usability_test_form_data() -> dict[str, Any]:
    return {
        "synthetic": True,
        "created_for": "LessonPack AI MVP",
        "created_at": CREATED_AT,
        "authoring_method": "manual_synthetic",
        "participants_target": 3,
        "scenario": "강사 역할로 차시 정보를 입력하고 교재 근거를 확인한 뒤 강의 패키지를 승인한다.",
        "tasks": [
            "프로젝트 생성",
            "교재 업로드 또는 샘플 교재 선택",
            "RAG 검색 결과 확인",
            "교안·실습·평가 초안 검토",
            "수정 후 승인",
            "DOCX 다운로드",
        ],
        "questions": [
            "흐름을 설명 없이 이해할 수 있었는가?",
            "citation 표시가 생성 결과 신뢰도에 도움이 되었는가?",
            "다른 차시에도 사용할 의향이 있는가?",
        ],
    }


def ncs_yaml_review_checklist_data() -> dict[str, Any]:
    return {
        "synthetic": True,
        "created_for": "LessonPack AI MVP",
        "created_at": CREATED_AT,
        "authoring_method": "manual_synthetic",
        "checks": [
            "선정한 능력단위 코드와 명칭이 source_md 첫 페이지와 일치한다.",
            "learning_topics는 source_md의 차례 또는 학습 항목에서 확인된다.",
            "performance_criteria는 원문을 과장하지 않고 수업 목표에 맞게 요약했다.",
            "도표, 사진, 삽화, 도면 등 제3자 저작물은 재사용하지 않는다.",
            "license_note에 출처 명시와 교육 목적 활용 조건을 기록했다.",
            "YAML에는 source_url과 source_md가 모두 포함되어 있다.",
        ],
    }


def generation_gold_data() -> dict[str, Any]:
    return {
        "synthetic": True,
        "created_for": "LessonPack AI MVP",
        "created_at": CREATED_AT,
        "authoring_method": "manual_synthetic",
        "cases": [
            {
                "case_id": "g001",
                "input": {
                    "curriculum_id": "curr-python-prompt-automation",
                    "ncs_unit_id": "2001020231",
                    "source_ids": ["python-functions", "ncs-programming-language-use"],
                },
                "expected": {
                    "lesson_plan_sections": ["도입", "전개", "정리"],
                    "practice_required": ["실습 시나리오", "수행 절차", "제출물", "평가 기준"],
                    "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
                    "citation_required": True,
                },
            },
            {
                "case_id": "g002",
                "input": {
                    "curriculum_id": "curr-python-prompt-automation",
                    "ncs_unit_id": "2001020230",
                    "source_ids": ["python-functions", "pandas-10min"],
                },
                "expected": {
                    "lesson_plan_sections": ["도입", "전개", "정리"],
                    "practice_required": ["라이브러리 활용", "함수화", "실행 결과"],
                    "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
                    "citation_required": True,
                },
            },
            {
                "case_id": "g003",
                "input": {
                    "curriculum_id": "curr-python-prompt-automation",
                    "ncs_unit_id": "2001020235",
                    "source_ids": ["python-data-structures", "ncs-data-structure-use"],
                },
                "expected": {
                    "lesson_plan_sections": ["도입", "전개", "정리"],
                    "practice_required": ["list 또는 dictionary", "정렬 또는 탐색", "평가 기준"],
                    "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
                    "citation_required": True,
                },
            },
        ],
    }


def selected_sources_data(sources: list[Source]) -> dict[str, Any]:
    return {
        "dataset_version": DATASET_VERSION,
        "created_at": CREATED_AT,
        "sources": [
            {
                "source_id": source.source_id,
                "path": rel(source.path),
                "source_name": source.source_name,
                "source_url": source.source_url,
                "license": source.license,
                "use_for": source.use_for,
            }
            for source in sources
        ],
    }


def dataset_manifest_data(
    chunks: list[dict[str, Any]],
    retrieval_gold: list[dict[str, Any]],
    generation_gold: dict[str, Any],
    sources: list[Source],
) -> dict[str, Any]:
    return {
        "dataset_version": DATASET_VERSION,
        "created_at": CREATED_AT,
        "raw_sources": len(sources),
        "chunk_count": len(chunks),
        "retrieval_gold_count": len(retrieval_gold),
        "generation_gold_count": len(generation_gold["cases"]),
        "license_reviewed": True,
        "ncs_unit_count": 3,
        "synthetic_files": [
            "data/raw/curriculum/curriculum_python_prompt_automation.yaml",
            "data/raw/synthetic/practice_examples.yaml",
            "data/gold/human_eval_rubric.yaml",
            "data/gold/usability_test_form.yaml",
            "data/gold/ncs_yaml_review_checklist.yaml",
            "data/gold/retrieval_gold.jsonl",
            "data/gold/generation_gold.yaml",
        ],
        "quality_thresholds": {
            "min_chunks": 30,
            "min_retrieval_gold": 10,
            "min_generation_gold": 3,
        },
    }


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_chunk_index(path: Path, chunks: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "chunk_id",
                "source_id",
                "section",
                "char_count",
                "token_estimate",
                "tags",
                "review_status",
            ],
        )
        writer.writeheader()
        for chunk in chunks:
            writer.writerow(
                {
                    "chunk_id": chunk["chunk_id"],
                    "source_id": chunk["source_id"],
                    "section": chunk["section"],
                    "char_count": chunk["char_count"],
                    "token_estimate": chunk["token_estimate"],
                    "tags": ";".join(chunk["tags"]),
                    "review_status": chunk["review_status"],
                }
            )


def write_source_file_map(path: Path, file_map: list[dict[str, Any]], sources: list[Source]) -> None:
    rows = list(file_map)
    rows.extend(
        {
            "role": "selected_source",
            "original_path": rel(source.path),
            "alias_path": rel(source.path),
            "selected_for_mvp": True,
        }
        for source in sources
    )
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["role", "original_path", "alias_path", "selected_for_mvp"])
        writer.writeheader()
        writer.writerows(rows)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


if __name__ == "__main__":
    main()
