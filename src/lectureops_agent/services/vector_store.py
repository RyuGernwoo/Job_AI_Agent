from pathlib import Path
from typing import Protocol

from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.retrieval_service import retrieve_chunks


class VectorStore(Protocol):
    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        ...

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks_by_project: dict[str, dict[str, MaterialChunk]] = {}

    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        project_chunks = self._chunks_by_project.setdefault(project_id, {})
        for chunk in chunks:
            project_chunks[chunk.chunk_id] = chunk

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        project_chunks = list(self._chunks_by_project.get(project_id, {}).values())
        return retrieve_chunks(query=query, chunks=project_chunks, top_k=top_k)


class ChromaVectorStore:
    def __init__(self, *, persist_path: str, collection_name: str = "lectureops_chunks") -> None:
        if not persist_path:
            raise ValueError("persist_path is required for ChromaVectorStore")
        try:
            import chromadb
        except ModuleNotFoundError as exc:
            raise RuntimeError("chromadb is not installed; run pip install -r requirements.txt") from exc

        self._client = chromadb.PersistentClient(path=str(Path(persist_path)))
        self._collection = self._client.get_or_create_collection(collection_name)

    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {
                    "project_id": project_id,
                    "document_id": chunk.document_id,
                    "source_name": chunk.source_name,
                    "source_type": chunk.source_type,
                    "page": chunk.page or "",
                }
                for chunk in chunks
            ],
        )

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        result = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where={"project_id": project_id},
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        chunks: list[MaterialChunk] = []
        for chunk_id, document, metadata in zip(ids, documents, metadatas, strict=False):
            chunks.append(
                MaterialChunk(
                    chunk_id=chunk_id,
                    project_id=project_id,
                    document_id=str(metadata.get("document_id", "unknown")),
                    source_name=str(metadata.get("source_name", "unknown")),
                    source_type=str(metadata.get("source_type", "txt")),
                    page=int(metadata["page"]) if metadata.get("page") else None,
                    text=document,
                    metadata=dict(metadata),
                )
            )
        return chunks
