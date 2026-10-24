"""Shared JSON Lines loop for external-validator workers.

Workers run inside a *separate* virtual environment where sqlguard_ninja is not installed,
so this file is executed by path (copied into each worker by ``exec``) rather than imported.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from collections.abc import Callable
from typing import Any

Evaluator = Callable[[str, str, dict[str, Any], dict[str, Any]], tuple[str, list[str]]]


def serve(library: str, version: str, build: Callable[[dict[str, Any]], Evaluator]) -> None:
    """Answer one JSON request per stdin line until EOF."""
    out = sys.stdout
    out.write(json.dumps({"library": library, "version": version}) + "\n")
    out.flush()
    cache: dict[str, Evaluator] = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        key = json.dumps(req["config"], sort_keys=True)
        reply: dict[str, Any]
        try:
            if key not in cache:
                cache[key] = build(req["config"])
            started = time.perf_counter()
            decision, reasons = cache[key](
                req["sql"], req["dialect"], req["context"], req["config"]
            )
            reply = {
                "decision": decision,
                "reasons": reasons,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "error": None,
            }
        except Exception as exc:  # report, fail closed, keep serving
            reply = {
                "decision": "deny",
                "reasons": [],
                "latency_ms": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3),
            }
        out.write(json.dumps(reply) + "\n")
        out.flush()
