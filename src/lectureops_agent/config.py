from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: Literal["mock", "http_chat", "openai_compatible", "litellm"]
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int | float | None = Field(default=None, gt=0)
    schema_retries: int = Field(default=1, ge=0, le=3)
    fallback_models: list[str] = Field(default_factory=list)
    callbacks: list[str] = Field(default_factory=list)
    success_callbacks: list[str] = Field(default_factory=list)
    # Sampling temperature for first-pass generation. Kept low for grounded, stable output.
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    # Slightly higher temperature for natural-language revisions so the edit diverges from the
    # source package. Kept moderate so the strict output schema (exact sections, counts, and
    # citation ids from the retrieved set) is still respected; the strengthened revision prompt
    # is the primary driver of divergence, not temperature.
    revision_temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class VectorStoreConfig(BaseModel):
    provider: Literal["memory", "supabase"]
    table_name: str = "lessonpack_chunks"
    match_function: str = "match_lessonpack_chunks"
    match_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    baseline_project_id: str = "mvp-dataset"
    candidate_k: int = Field(default=20, ge=1, le=200)
    embedding_provider: Literal["hash", "litellm"] = "hash"
    embedding_model: str = "lessonpack-hash-v1"
    embedding_dimensions: int = Field(default=64, gt=0)
    embedding_column: str = "embedding"
    embedding_version: str = Field(default="v1", min_length=1)


class LessonPackConfig(BaseModel):
    chunk_size_chars: int = Field(gt=0)
    chunk_overlap_chars: int = Field(ge=0)
    retrieval_top_k: int = Field(gt=0)
    max_upload_mb: int = Field(default=20, ge=1, le=100)
    llm: LLMConfig
    vector_store: VectorStoreConfig


def load_config(path: str | Path) -> LessonPackConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required to load config.yaml") from exc

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config file must contain a YAML mapping")
    return LessonPackConfig.model_validate(raw)
