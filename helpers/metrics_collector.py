"""
Ring buffer for LLM usage metrics with optional file persistence.
Collects events via extension points (chat_model_call_after,
util_model_call_after) and provides aggregated snapshots for the
metrics dashboard API.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from helpers.print_style import PrintStyle


_DEFAULT_RING_SIZE = 2000
_DEFAULT_FLUSH_INTERVAL = 30.0


class MetricsCollector:
    """Thread-safe ring buffer that stores LLM usage events."""

    def __init__(self, maxlen: int = _DEFAULT_RING_SIZE):
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._started_at = time.time()
        self._persist_path: str | None = None
        self._flush_interval: float = _DEFAULT_FLUSH_INTERVAL
        self._dirty = False

    def configure(
        self,
        maxlen: int | None = None,
        flush_interval: float | None = None,
    ) -> None:
        """Apply runtime config before persistence is enabled."""
        if maxlen is not None and maxlen != self._events.maxlen:
            with self._lock:
                self._events = deque(self._events, maxlen=maxlen)
        if flush_interval is not None:
            self._flush_interval = flush_interval

    def enable_persistence(self, path: str) -> None:
        """Enable file-based persistence. Loads existing data and starts auto-save.

        Idempotent and thread-safe: concurrent calls (which happen when Agent Zero
        triggers after_plugin_change twice in a row) must not double-load events.
        """
        with self._lock:
            if self._persist_path:
                return
            self._persist_path = path
        PrintStyle.standard(f"metrics: enabling persistence at {path}")
        self._load()
        self._schedule_flush()

    def record(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)
            self._dirty = True

    def snapshot(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        bucket: str = "hour",
    ) -> dict[str, Any]:
        with self._lock:
            all_events = list(self._events)

        from_epoch, to_epoch = _resolve_time_range(from_ts, to_ts)
        bucket = bucket if bucket in {"hour", "day"} else "hour"
        events = [
            e for e in all_events
            if _event_in_range(e, from_epoch, to_epoch)
        ]

        if not events:
            return self._empty_snapshot(
                buffer_size=len(all_events),
                from_epoch=from_epoch,
                to_epoch=to_epoch,
                bucket=bucket,
            )

        success_events = [e for e in events if e.get("success")]
        failed_events = [e for e in events if not e.get("success")]
        total_tokens_in = sum(e.get("tokens_in", 0) for e in events)
        total_tokens_out = sum(e.get("tokens_out", 0) for e in events)

        latencies = [e["latency_ms"] for e in success_events if "latency_ms" in e]
        avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0

        ttfts = [e["ttft_ms"] for e in success_events if e.get("ttft_ms") is not None]
        avg_ttft = int(sum(ttfts) / len(ttfts)) if ttfts else 0
        p95_ttft = _percentile(ttfts, 95)

        prompt_tps_vals = [e.get("prompt_tps", 0) for e in success_events if e.get("prompt_tps")]
        resp_tps_vals = [e.get("response_tps", 0) for e in success_events if e.get("response_tps")]
        avg_prompt_tps = round(sum(prompt_tps_vals) / len(prompt_tps_vals), 1) if prompt_tps_vals else 0
        avg_response_tps = round(sum(resp_tps_vals) / len(resp_tps_vals), 1) if resp_tps_vals else 0

        return {
            "total_calls": len(events),
            "success_calls": len(success_events),
            "failed_calls": len(failed_events),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "avg_latency_ms": avg_latency,
            "p50_latency_ms": _percentile(latencies, 50),
            "p95_latency_ms": _percentile(latencies, 95),
            "p99_latency_ms": _percentile(latencies, 99),
            "avg_ttft_ms": avg_ttft,
            "p95_ttft_ms": p95_ttft,
            "avg_prompt_tps": avg_prompt_tps,
            "avg_response_tps": avg_response_tps,
            "by_model": _aggregate_by(events, "model"),
            "by_usage_type": _aggregate_by(events, "usage_type"),
            "by_project": _aggregate_by_project(events),
            "timeline": _build_timeline(events, bucket),
            "recent_errors": _recent_errors(failed_events),
            "recent_events": _recent_events(events),
            "uptime_seconds": int(time.time() - self._started_at),
            "buffer_size": len(all_events),
            "buffer_capacity": self._events.maxlen,
            "filtered_count": len(events),
            "range_from_ts": _epoch_to_iso(from_epoch),
            "range_to_ts": _epoch_to_iso(to_epoch),
            "bucket": bucket,
        }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._dirty = False
        if self._persist_path:
            try:
                os.remove(self._persist_path)
            except OSError:
                pass

    # -- Persistence internals --

    def _load(self) -> None:
        if not self._persist_path:
            return
        if not os.path.isfile(self._persist_path):
            PrintStyle.standard(f"metrics: persistence file not found: {self._persist_path}")
            return
        try:
            with open(self._persist_path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                with self._lock:
                    for event in data:
                        self._events.append(event)
                PrintStyle.standard(f"metrics: loaded {len(data)} events from {self._persist_path}")
            else:
                PrintStyle.warning(f"metrics: persistence file is not a JSON array (got {type(data).__name__}), skipping")
        except json.JSONDecodeError as e:
            PrintStyle.error(f"metrics: corrupted persistence file {self._persist_path}: {e}")
        except OSError as e:
            PrintStyle.error(f"metrics: cannot read persistence file {self._persist_path}: {e}")

    def _flush(self) -> None:
        if not self._persist_path or not self._dirty:
            return
        with self._lock:
            events = list(self._events)
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(events, f, separators=(",", ":"))
            os.replace(tmp, self._persist_path)
        except OSError:
            pass

    def _schedule_flush(self) -> None:
        def _tick():
            self._flush()
            self._schedule_flush()
        t = threading.Timer(self._flush_interval, _tick)
        t.daemon = True
        t.start()

    def _empty_snapshot(
        self,
        buffer_size: int | None = None,
        from_epoch: float | None = None,
        to_epoch: float | None = None,
        bucket: str = "hour",
    ) -> dict[str, Any]:
        if from_epoch is None or to_epoch is None:
            from_epoch, to_epoch = _resolve_time_range(None, None)
        return {
            "total_calls": 0, "success_calls": 0, "failed_calls": 0,
            "total_tokens_in": 0, "total_tokens_out": 0,
            "avg_latency_ms": 0, "p50_latency_ms": 0, "p95_latency_ms": 0, "p99_latency_ms": 0,
            "avg_ttft_ms": 0, "p95_ttft_ms": 0,
            "avg_prompt_tps": 0, "avg_response_tps": 0,
            "by_model": [], "by_usage_type": [], "by_project": [],
            "timeline": [], "recent_errors": [], "recent_events": [],
            "uptime_seconds": int(time.time() - self._started_at),
            "buffer_size": 0 if buffer_size is None else buffer_size,
            "buffer_capacity": self._events.maxlen,
            "filtered_count": 0,
            "range_from_ts": _epoch_to_iso(from_epoch),
            "range_to_ts": _epoch_to_iso(to_epoch),
            "bucket": bucket if bucket in {"hour", "day"} else "hour",
        }


def _aggregate_by(events: list[dict], key: str) -> list[dict]:
    """Generic aggregation by a single field."""
    groups: dict[str, dict] = {}
    for e in events:
        val = e.get(key) or "unknown"
        g = groups.setdefault(val, {
            "name": val, "calls": 0, "success": 0, "failed": 0,
            "tokens_in": 0, "tokens_out": 0, "total_latency_ms": 0, "retries": 0,
            "ttft_sum": 0, "ttft_count": 0,
        })
        g["calls"] += 1
        g["success" if e.get("success") else "failed"] += 1
        g["tokens_in"] += e.get("tokens_in", 0)
        g["tokens_out"] += e.get("tokens_out", 0)
        g["total_latency_ms"] += e.get("latency_ms", 0)
        attempts = e.get("attempts", 1)
        if attempts > 1:
            g["retries"] += attempts - 1
        ttft = e.get("ttft_ms")
        if ttft is not None:
            g["ttft_sum"] += ttft
            g["ttft_count"] += 1

    result = []
    for g in groups.values():
        g["avg_latency_ms"] = int(g["total_latency_ms"] / g["calls"]) if g["calls"] else 0
        g["avg_ttft_ms"] = int(g["ttft_sum"] / g["ttft_count"]) if g["ttft_count"] else 0
        del g["total_latency_ms"], g["ttft_sum"], g["ttft_count"]
        result.append(g)
    result.sort(key=lambda x: x["calls"], reverse=True)
    return result


def _aggregate_by_project(events: list[dict]) -> list[dict]:
    """Aggregate by project with nested per-chat breakdown."""
    projects: dict[str, dict] = {}
    for e in events:
        proj = e.get("project") or "No Project"
        chat = e.get("context_id") or "unknown"
        chat_name = e.get("chat_name") or chat

        p = projects.setdefault(proj, {
            "name": proj, "calls": 0, "tokens_in": 0, "tokens_out": 0,
            "total_latency_ms": 0, "chats": {},
        })
        p["calls"] += 1
        p["tokens_in"] += e.get("tokens_in", 0)
        p["tokens_out"] += e.get("tokens_out", 0)
        p["total_latency_ms"] += e.get("latency_ms", 0)

        c = p["chats"].setdefault(chat, {
            "context_id": chat, "name": chat_name,
            "calls": 0, "tokens_in": 0, "tokens_out": 0,
        })
        c["calls"] += 1
        c["tokens_in"] += e.get("tokens_in", 0)
        c["tokens_out"] += e.get("tokens_out", 0)

    result = []
    for p in projects.values():
        p["avg_latency_ms"] = int(p["total_latency_ms"] / p["calls"]) if p["calls"] else 0
        del p["total_latency_ms"]
        chat_list = sorted(p["chats"].values(), key=lambda x: x["calls"], reverse=True)
        p["chats"] = chat_list
        result.append(p)
    result.sort(key=lambda x: x["calls"], reverse=True)
    return result


def _build_timeline(events: list[dict], bucket: str = "hour") -> list[dict]:
    buckets: dict[int, dict] = {}
    bucket_seconds = 86400 if bucket == "day" else 3600
    for e in events:
        epoch = _parse_event_epoch(e)
        if epoch is None:
            continue
        bucket_key = int(epoch // bucket_seconds) * bucket_seconds
        b = buckets.setdefault(
            bucket_key,
            {
                "ts": bucket_key,
                "calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "errors": 0,
            },
        )
        b["calls"] += 1
        b["tokens_in"] += e.get("tokens_in", 0)
        b["tokens_out"] += e.get("tokens_out", 0)
        if not e.get("success"):
            b["errors"] += 1
    return sorted(buckets.values(), key=lambda x: x["ts"])


def _recent_errors(failed: list[dict], limit: int = 20) -> list[dict]:
    return [
        {
            "model": e.get("model", "unknown"),
            "error": e.get("error", "unknown"),
            "timestamp": e.get("timestamp", ""),
            "attempts": e.get("attempts", 1),
            "agent_name": e.get("agent_name"),
            "usage_type": e.get("usage_type"),
        }
        for e in reversed(failed[-limit:])
    ]


def _recent_events(events: list[dict], limit: int = 50) -> list[dict]:
    return [
        {
            "model": e.get("model", "unknown"),
            "provider": e.get("provider"),
            "tokens_in": e.get("tokens_in", 0),
            "tokens_out": e.get("tokens_out", 0),
            "latency_ms": e.get("latency_ms", 0),
            "ttft_ms": e.get("ttft_ms"),
            "success": e.get("success", False),
            "error": e.get("error"),
            "stream": e.get("stream", False),
            "attempts": e.get("attempts", 1),
            "timestamp": e.get("timestamp", ""),
            "usage_type": e.get("usage_type"),
            "agent_name": e.get("agent_name"),
            "project": e.get("project"),
            "chat_name": e.get("chat_name"),
        }
        for e in reversed(events[-limit:])
    ]


def _percentile(data: list, pct: int) -> int:
    if not data:
        return 0
    s = sorted(data)
    idx = min(int(len(s) * pct / 100), len(s) - 1)
    return int(s[idx])


def _resolve_time_range(
    from_ts: str | None,
    to_ts: str | None,
) -> tuple[float, float]:
    to_epoch = _parse_timestamp_epoch(to_ts)
    from_epoch = _parse_timestamp_epoch(from_ts)

    if from_epoch is None or to_epoch is None:
        to_epoch = time.time()
        from_epoch = to_epoch - 86400

    if from_epoch > to_epoch:
        from_epoch, to_epoch = to_epoch, from_epoch

    return from_epoch, to_epoch


def _event_in_range(event: dict[str, Any], from_epoch: float, to_epoch: float) -> bool:
    epoch = _parse_event_epoch(event)
    return epoch is not None and from_epoch <= epoch <= to_epoch


def _parse_event_epoch(event: dict[str, Any]) -> float | None:
    return _parse_timestamp_epoch(event.get("timestamp"))


def _parse_timestamp_epoch(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError):
        return None


def _epoch_to_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


collector = MetricsCollector()
