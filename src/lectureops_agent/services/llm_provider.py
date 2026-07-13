from __future__ import annotations

import os
from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def generate(self, *, prompt: str) -> str:
        ...


class MockLLMProvider:
    name = "mock"

    def generate(self, *, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        return (
            "Mock provider outline: align lesson plan, practice, and assessment with "
            "the retrieved evidence and require instructor review before approval."
        )


def create_llm_provider_from_env() -> LLMProvider:
    provider_name = os.getenv("LESSONPACK_LLM_PROVIDER", "mock").strip().casefold()
    if provider_name in {"", "mock"}:
        return MockLLMProvider()
    raise ValueError(f"unsupported LLM provider: {provider_name}")
