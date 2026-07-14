from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: Literal["mock", "http_chat", "openai_compatible"]
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int | float | None = Field(default=None, gt=0)


class VectorStoreConfig(BaseModel):
    provider: Literal["memory", "chroma"]
    persist_path: str | None = None
    collection_name: str | None = None


class LessonPackConfig(BaseModel):
    chunk_size_chars: int = Field(gt=0)
    chunk_overlap_chars: int = Field(ge=0)
    retrieval_top_k: int = Field(gt=0)
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
