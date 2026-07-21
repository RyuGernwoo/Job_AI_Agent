import re
from typing import Any

from lectureops_agent.models.schemas import MaterialChunk


_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣_+-]+")
_CONCEPT_SYNONYMS = {
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


def retrieve_chunks(*, query: str, chunks: list[MaterialChunk], top_k: int) -> list[MaterialChunk]:
    query_tokens = _tokenize(query)
    terms = _expand_terms(query_tokens)
    if not terms:
        raise ValueError("query must include at least one term")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    scored: list[tuple[int, int, int, MaterialChunk]] = []
    for index, chunk in enumerate(chunks):
        text_haystack = chunk.text.casefold()
        metadata_haystack = _metadata_haystack(chunk).casefold()
        score = 0
        matched_terms = 0
        for term in terms:
            text_hits = text_haystack.count(term)
            metadata_hits = metadata_haystack.count(term)
            if text_hits or metadata_hits:
                matched_terms += 1
                score += min(text_hits, 5) * 2
                score += min(metadata_hits, 5) * 3
        if "ncs" in query_tokens and "ncs" in metadata_haystack:
            score += 20
        if matched_terms:
            score += matched_terms * 2
        if score > 0:
            scored.append((score, matched_terms, -index, chunk))

    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [chunk for _, _, _, chunk in scored[:top_k]]


def expanded_query_terms(query: str) -> list[str]:
    """Return normalized query terms with the domain synonym set applied."""
    return _expand_terms(_tokenize(query))


def _tokenize(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_PATTERN.findall(text) if token.strip()]


def _expand_terms(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        variants = [token, *_CONCEPT_SYNONYMS.get(token, [])]
        for variant in variants:
            normalized = variant.casefold().strip()
            if normalized and normalized not in seen:
                expanded.append(normalized)
                seen.add(normalized)
    return expanded


def _metadata_haystack(chunk: MaterialChunk) -> str:
    values = [
        chunk.chunk_id,
        chunk.document_id,
        chunk.source_name,
        chunk.source_type,
    ]
    for value in chunk.metadata.values():
        values.extend(_flatten_metadata_value(value))
    return " ".join(values)


def _flatten_metadata_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item is not None]
    return [str(value)]
