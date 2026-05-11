from __future__ import annotations

import contextvars
import time
import uuid
from typing import Any


_current_call: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "a0_metrics_current_call",
    default=None,
)


def begin_call(agent: Any, call_data: dict[str, Any], usage_type: str) -> None:
    """Attach per-call metadata for LiteLLM callbacks running in this context."""
    metadata = _build_metadata(agent, call_data, usage_type)
    token = _current_call.set(metadata)
    call_data["_metrics_context"] = metadata
    call_data["_metrics_context_token"] = token
    call_data["_metrics_recorded"] = False


def current_call() -> dict[str, Any] | None:
    return _current_call.get()


def mark_recorded() -> None:
    metadata = current_call()
    if metadata is not None:
        metadata["recorded"] = True
        call_data = metadata.get("call_data")
        if isinstance(call_data, dict):
            call_data["_metrics_recorded"] = True


def end_call(call_data: dict[str, Any] | None = None) -> None:
    if not call_data:
        return
    token = call_data.pop("_metrics_context_token", None)
    call_data.pop("_metrics_context", None)
    if token is not None:
        _current_call.reset(token)


def _build_metadata(agent: Any, call_data: dict[str, Any], usage_type: str) -> dict[str, Any]:
    model = call_data.get("model")
    model_name = getattr(model, "model_name", "unknown") if model else "unknown"
    model_conf = getattr(model, "a0_model_conf", None)
    provider = getattr(model_conf, "provider", "") if model_conf else getattr(model, "provider", "")

    project = ""
    context_id = ""
    chat_name = ""
    agent_name = ""
    if agent:
        agent_name = f"Agent {getattr(agent, 'number', '?')}"
        ctx = getattr(agent, "context", None)
        if ctx:
            context_id = getattr(ctx, "id", "")
            chat_name = getattr(ctx, "name", "")
            project = (ctx.data.get("project") if hasattr(ctx, "data") else "") or ""

    stream = bool(call_data.get("response_callback") or call_data.get("callback"))
    return {
        "id": uuid.uuid4().hex,
        "usage_type": usage_type,
        "model": model_name,
        "provider": provider or "",
        "agent_name": agent_name,
        "project": project,
        "context_id": context_id,
        "chat_name": chat_name,
        "stream": stream,
        "start": call_data.get("_metrics_start") or time.time(),
        "call_data": call_data,
        "recorded": False,
    }
