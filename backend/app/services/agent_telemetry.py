"""Request-scoped, privacy-safe telemetry for evaluation and operations."""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any, AsyncIterator


_telemetry: ContextVar[dict[str, Any] | None] = ContextVar("agent_telemetry", default=None)


def _usage(response: Any) -> dict[str, int]:
    raw = getattr(response, "usage_metadata", None) or {}
    if not raw:
        raw = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
    def number(*keys: str) -> int:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        return 0
    return {
        "input_tokens": number("input_tokens", "prompt_tokens"),
        "output_tokens": number("output_tokens", "completion_tokens"),
        "total_tokens": number("total_tokens") or number("input_tokens", "prompt_tokens") + number("output_tokens", "completion_tokens"),
    }


@asynccontextmanager
async def capture_agent_telemetry() -> AsyncIterator[dict[str, Any]]:
    telemetry: dict[str, Any] = {"llm_calls": [], "tool_events": []}
    token = _telemetry.set(telemetry)
    try:
        yield telemetry
    finally:
        _telemetry.reset(token)


async def invoke_llm(client: Any, messages: list[Any], *, stage: str) -> Any:
    """Invoke a LangChain model and record only timing/usage metadata, never prompts."""
    started = perf_counter()
    try:
        response = await client.ainvoke(messages)
    except Exception as exc:
        active = _telemetry.get()
        if active is not None:
            active["llm_calls"].append({"stage": stage, "latency_ms": round((perf_counter() - started) * 1000, 2), "success": False, "error_type": type(exc).__name__, "usage": {}})
        raise
    active = _telemetry.get()
    if active is not None:
        active["llm_calls"].append({"stage": stage, "latency_ms": round((perf_counter() - started) * 1000, 2), "success": True, "usage": _usage(response)})
    return response


def record_tool_event(
    name: str,
    *,
    success: bool,
    order_sn: str = "",
    confirmed: bool | None = None,
    before: str = "",
    after: str = "",
    detail: str = "",
    error_type: str = "",
) -> None:
    """Record privacy-safe business tool execution for release evaluation."""
    active = _telemetry.get()
    if active is None:
        return
    active["tool_events"].append({
        "name": name,
        "success": success,
        "order_sn": order_sn,
        "confirmed": confirmed,
        "before": before,
        "after": after,
        "detail": detail[:160],
        "error_type": error_type,
    })


def telemetry_summary(telemetry: dict[str, Any]) -> dict[str, Any]:
    calls = list(telemetry.get("llm_calls") or [])
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for call in calls:
        for key in usage:
            usage[key] += int((call.get("usage") or {}).get(key) or 0)
    return {"llm_calls": calls, "tool_events": list(telemetry.get("tool_events") or []), "usage": usage}
