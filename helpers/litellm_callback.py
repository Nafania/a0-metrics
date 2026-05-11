from __future__ import annotations

import datetime
from typing import Any

from helpers.print_style import PrintStyle
from helpers.tokens import approximate_tokens

from usr.plugins.metrics.helpers import correlation


CALLBACK_ID = "a0_metrics_litellm_callback"


def register_litellm_callback() -> None:
    """Register the metrics LiteLLM callback once, surviving plugin reloads."""
    try:
        import litellm
        from litellm.integrations.custom_logger import CustomLogger
    except Exception as e:
        PrintStyle.warning(f"metrics: LiteLLM callback unavailable: {e}")
        return

    class MetricsLiteLLMLogger(CustomLogger):
        _a0_metrics_callback_id = CALLBACK_ID

        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            _record_litellm_event(kwargs, response_obj, start_time, end_time, True)

        async def async_log_success_event(
            self,
            kwargs,
            response_obj,
            start_time,
            end_time,
        ):
            _record_litellm_event(kwargs, response_obj, start_time, end_time, True)

        def log_failure_event(self, kwargs, response_obj, start_time, end_time):
            _record_litellm_event(kwargs, response_obj, start_time, end_time, False)

        async def async_log_failure_event(
            self,
            kwargs,
            response_obj,
            start_time,
            end_time,
        ):
            _record_litellm_event(kwargs, response_obj, start_time, end_time, False)

    callbacks = [
        cb for cb in getattr(litellm, "callbacks", [])
        if getattr(cb, "_a0_metrics_callback_id", None) != CALLBACK_ID
    ]
    callbacks.append(MetricsLiteLLMLogger())
    litellm.callbacks = callbacks
    PrintStyle.standard("metrics: LiteLLM usage callback registered")


def _record_litellm_event(
    kwargs: dict[str, Any] | None,
    response_obj: Any,
    start_time: Any,
    end_time: Any,
    success: bool,
) -> None:
    kwargs = kwargs or {}
    if kwargs.get("_a0_metrics_recorded"):
        return
    metadata = correlation.current_call() or {}
    if metadata.get("recorded"):
        return
    usage = _extract_usage(response_obj)
    tokens_source = "provider_usage" if usage else "estimated"

    tokens_in = _usage_int(usage, "prompt_tokens", "input_tokens")
    tokens_out = _usage_int(usage, "completion_tokens", "output_tokens")

    if tokens_in is None:
        tokens_in = _estimate_input_tokens(kwargs)
    if tokens_out is None:
        tokens_out = _estimate_output_tokens(response_obj)

    latency_ms = _duration_ms(start_time, end_time)
    ttft_ms = None
    prompt_tps = 0
    response_tps = 0
    call_data = metadata.get("call_data")
    start = metadata.get("start")
    ttft_time = call_data.get("_metrics_ttft") if isinstance(call_data, dict) else None
    if start and ttft_time:
        ttft_ms = int((ttft_time - start) * 1000)
        ttft_s = ttft_ms / 1000.0
        prompt_tps = round(tokens_in / ttft_s, 1) if ttft_s > 0 else 0
        generation_s = (latency_ms / 1000.0) - ttft_s
        response_tps = round(tokens_out / generation_s, 1) if generation_s > 0 else 0

    from usr.plugins.metrics.helpers.metrics_collector import collector

    collector.record({
        "model": (
            metadata.get("model")
            or kwargs.get("model")
            or _get_attr(response_obj, "model", "unknown")
        ),
        "provider": metadata.get("provider") or _provider_from_kwargs(kwargs),
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "total_tokens": (
            _usage_int(usage, "total_tokens")
            or int((tokens_in or 0) + (tokens_out or 0))
        ),
        "cost": _float_or_zero(kwargs.get("response_cost")),
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "prompt_tps": prompt_tps,
        "response_tps": response_tps,
        "success": success,
        "error": "" if success else _error_message(kwargs, response_obj),
        "stream": bool(metadata.get("stream") or kwargs.get("stream")),
        "attempts": 1,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "usage_type": metadata.get("usage_type") or _usage_type_from_kwargs(kwargs),
        "agent_name": metadata.get("agent_name", ""),
        "project": metadata.get("project", ""),
        "context_id": metadata.get("context_id", ""),
        "chat_name": metadata.get("chat_name", ""),
        "source": "litellm_callback",
        "tokens_source": tokens_source,
        "raw_usage": _json_safe_usage(usage),
    })
    kwargs["_a0_metrics_recorded"] = True
    correlation.mark_recorded()


def _extract_usage(response_obj: Any) -> dict[str, Any]:
    usage = None
    if isinstance(response_obj, dict):
        usage = response_obj.get("usage")
    if usage is None:
        usage = getattr(response_obj, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "dict"):
        return usage.dict()
    return {
        key: getattr(usage, key)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "input_tokens",
            "output_tokens",
        )
        if hasattr(usage, key)
    }


def _usage_int(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _estimate_input_tokens(kwargs: dict[str, Any]) -> int:
    if "messages" in kwargs:
        return approximate_tokens(str(kwargs.get("messages") or ""))
    if "input" in kwargs:
        return approximate_tokens(str(kwargs.get("input") or ""))
    return 0


def _estimate_output_tokens(response_obj: Any) -> int:
    return approximate_tokens(_response_text(response_obj))


def _response_text(response_obj: Any) -> str:
    if response_obj is None:
        return ""
    if isinstance(response_obj, str):
        return response_obj
    if isinstance(response_obj, dict):
        choices = response_obj.get("choices") or []
    else:
        choices = getattr(response_obj, "choices", []) or []
    texts: list[str] = []
    for choice in choices:
        message = (
            choice.get("message")
            if isinstance(choice, dict)
            else getattr(choice, "message", None)
        )
        if message is None:
            continue
        if isinstance(message, dict):
            texts.append(str(message.get("content") or ""))
            texts.append(str(message.get("reasoning_content") or ""))
        else:
            texts.append(str(getattr(message, "content", "") or ""))
            texts.append(str(getattr(message, "reasoning_content", "") or ""))
    return "".join(texts)


def _duration_ms(start_time: Any, end_time: Any) -> int:
    try:
        return int((end_time - start_time).total_seconds() * 1000)
    except Exception:
        try:
            return int((float(end_time) - float(start_time)) * 1000)
        except Exception:
            return 0


def _provider_from_kwargs(kwargs: dict[str, Any]) -> str:
    params = kwargs.get("litellm_params") or {}
    if isinstance(params, dict):
        return params.get("custom_llm_provider") or params.get("provider") or ""
    return ""


def _usage_type_from_kwargs(kwargs: dict[str, Any]) -> str:
    if "input" in kwargs and "messages" not in kwargs:
        return "embedding"
    return "internal"


def _error_message(kwargs: dict[str, Any], response_obj: Any) -> str:
    exc = kwargs.get("exception")
    if exc:
        return str(exc)
    if response_obj:
        return str(response_obj)
    return "LiteLLM call failed"


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _json_safe_usage(usage: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in usage.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe
