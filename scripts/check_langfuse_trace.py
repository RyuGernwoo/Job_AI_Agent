"""Emit a synthetic LiteLLM call and verify that Langfuse can read the trace."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.env import load_env_file
from lectureops_agent.services.langfuse_tracing import flush_langfuse_otel
from lectureops_agent.services.llm_provider import create_llm_provider_from_env
from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Langfuse trace smoke test.")
    parser.add_argument("--trace-id", default=f"lessonpack-smoke-{uuid4().hex}", help="Trace marker to emit and query.")
    parser.add_argument("--poll-seconds", type=int, default=90, help="How long to poll Langfuse Public API.")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between Langfuse API polls.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args(argv)

    load_env_file()
    generation_name = f"lessonpack-ai-langfuse-smoke-{args.trace_id}"
    session_id = f"lessonpack-ai-smoke-{args.trace_id}"
    os.environ["LESSONPACK_LANGFUSE_TRACE_ID"] = args.trace_id
    os.environ["LESSONPACK_LANGFUSE_TRACE_NAME"] = generation_name
    os.environ["LESSONPACK_LANGFUSE_GENERATION_NAME"] = generation_name
    os.environ["LESSONPACK_LANGFUSE_SESSION_ID"] = session_id

    readiness = check_llm_provider_readiness()
    report: dict[str, Any] = {
        "trace_id": args.trace_id,
        "generation_name": generation_name,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider_readiness": readiness,
        "llm_call": {"ok": False},
        "langfuse_query": {"detected": False, "attempts": 0},
    }

    try:
        provider = create_llm_provider_from_env()
        response = provider.generate(
            prompt=(
                "LessonPack AI Langfuse synthetic smoke test. "
                "Reply with the exact phrase: LessonPack trace smoke ok."
            )
        )
        flush_langfuse_otel()
        report["llm_call"] = {
            "ok": True,
            "provider_name": provider.name,
            "response_preview": response[:160],
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic CLI boundary.
        report["llm_call"] = {"ok": False, "error": str(exc)}
        _write_report(report, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    query_result = _poll_langfuse_trace(
        trace_id=args.trace_id,
        generation_name=generation_name,
        session_id=session_id,
        poll_seconds=args.poll_seconds,
        poll_interval=args.poll_interval,
    )
    report["langfuse_query"] = query_result
    _write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if query_result["detected"] else 1


def _poll_langfuse_trace(
    *,
    trace_id: str,
    generation_name: str,
    session_id: str,
    poll_seconds: int,
    poll_interval: int,
) -> dict[str, Any]:
    deadline = time.time() + max(0, poll_seconds)
    attempts = 0
    last_error = None
    latest_payload: dict[str, Any] | None = None
    while True:
        attempts += 1
        try:
            trace_payload = _query_observations(trace_id=trace_id)
            latest_payload = trace_payload
            trace_data = trace_payload.get("data") or []
            if trace_data:
                return _detected_result(
                    attempts=attempts,
                    observation_count=len(trace_data),
                    api="observations_v2_trace_id",
                )

            recent_payload = _query_observations()
            latest_payload = recent_payload
            matches = _matching_observations(
                recent_payload.get("data") or [],
                markers=[trace_id, generation_name, session_id],
            )
            if matches:
                return _detected_result(
                    attempts=attempts,
                    observation_count=len(matches),
                    api="observations_v2_recent_marker",
                )
        except Exception as exc:  # noqa: BLE001 - keep polling with last diagnostic.
            last_error = str(exc)

        if time.time() >= deadline:
            return {
                "detected": False,
                "attempts": attempts,
                "observation_count": 0,
                "api": "observations_v2",
                "host": _langfuse_host(),
                "last_error": last_error,
                "last_payload_keys": sorted(latest_payload.keys()) if isinstance(latest_payload, dict) else None,
            }
        time.sleep(max(1, poll_interval))


def _detected_result(*, attempts: int, observation_count: int, api: str) -> dict[str, Any]:
    return {
        "detected": True,
        "attempts": attempts,
        "observation_count": observation_count,
        "api": api,
        "host": _langfuse_host(),
    }


def _query_observations(*, trace_id: str | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    query: dict[str, str] = {
        "fromStartTime": (now - timedelta(minutes=20)).isoformat(),
        "toStartTime": (now + timedelta(minutes=5)).isoformat(),
        "limit": "100",
        "fields": "core,basic,usage",
    }
    if trace_id:
        query["traceId"] = trace_id
    request = Request(f"{_public_api_base()}/v2/observations?{urlencode(query)}", headers=_auth_headers(), method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Langfuse observations query failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Langfuse observations query failed: {exc.reason}") from exc


def _matching_observations(rows: list[dict[str, Any]], *, markers: list[str]) -> list[dict[str, Any]]:
    matches = []
    for row in rows:
        serialized = json.dumps(row, ensure_ascii=False)
        if any(marker and marker in serialized for marker in markers):
            matches.append(row)
    return matches


def _auth_headers() -> dict[str, str]:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _public_api_base() -> str:
    return f"{_langfuse_host().rstrip('/')}/api/public"


def _langfuse_host() -> str:
    host = (
        os.getenv("LANGFUSE_BASE_URL")
        or os.getenv("LANGFUSE_OTEL_HOST")
        or os.getenv("LANGFUSE_HOST")
        or "https://us.cloud.langfuse.com"
    ).strip()
    if "/api/public" in host:
        host = host.split("/api/public", 1)[0]
    return host.rstrip("/")


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())