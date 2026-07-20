"""Smoke-check a deployed LessonPack AI API endpoint."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a deployed LessonPack AI API.")
    parser.add_argument("base_url", help="Base URL such as http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    report = {"base_url": base_url, "checks": []}
    ok = _check_health(base_url=base_url, timeout=args.timeout, report=report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def _check_health(base_url: str, timeout: float, report: dict) -> bool:
    url = f"{base_url}/health"
    check = {"name": "health", "url": url, "ok": False}
    report["checks"].append(check)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        check["error"] = str(exc)
        return False

    check["status_code"] = status_code
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        check["body_preview"] = body[:200]
        return False

    check["payload"] = payload
    check["ok"] = status_code == 200 and payload.get("status") == "ok" and payload.get("service") == "lessonpack-ai"
    return check["ok"]


if __name__ == "__main__":
    sys.exit(main())
