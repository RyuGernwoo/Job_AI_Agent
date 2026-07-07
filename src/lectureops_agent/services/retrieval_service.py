from lectureops_agent.models.schemas import MaterialChunk


def retrieve_chunks(*, query: str, chunks: list[MaterialChunk], top_k: int) -> list[MaterialChunk]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        raise ValueError("query must include at least one term")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    scored: list[tuple[int, int, MaterialChunk]] = []
    for index, chunk in enumerate(chunks):
        haystack = chunk.text.casefold()
        score = sum(haystack.count(term) for term in terms)
        if score > 0:
            scored.append((score, -index, chunk))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [chunk for _, _, chunk in scored[:top_k]]
