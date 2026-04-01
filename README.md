# metrics — LLM Metrics Plugin for Agent Zero

In-memory ring buffer for LLM usage metrics with a dashboard UI, file persistence, and per-model/project aggregation.

## Features

- Tracks every chat and utility LLM call (tokens, latency, TTFT, model, provider)
- Thread-safe ring buffer with configurable size (default 2000 events)
- Periodic JSON persistence to `usr/metrics.json`
- Dashboard with Overview, Performance, Usage Type, By Project, and Live Feed tabs
- Per-model latency bars, sparkline timeline, success rate, token throughput
- Project → chat drill-down with token/call counts
- Sidebar quick-action button for instant access

## Installation

### Via UI (recommended)

1. Open **Settings → Plugins → Install**.
2. Switch to the **Git URL** tab.
3. Enter the repository URL for this plugin.
4. Click **Install**. The plugin installer will clone the repo into `usr/plugins/`, run `hooks.py`, and enable the plugin automatically.

## Requirements

None — uses only Python stdlib and Agent Zero framework APIs.

## Configuration

Defaults are in `default_config.yaml`. Override via the plugin settings UI or by editing the config directly.

| Key | Default | Description |
|-----|---------|-------------|
| `ring_buffer_size` | 2000 | Max events in the ring buffer |
| `flush_interval_seconds` | 30 | Seconds between persistence flushes |
| `persistence_file` | `usr/metrics.json` | Where events are persisted |
