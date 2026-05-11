import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";

const metricsStore = {
  loading: false,
  error: null,
  activeTab: "overview",

  // KPIs
  totalCalls: 0,
  successCalls: 0,
  failedCalls: 0,
  totalTokensIn: 0,
  totalTokensOut: 0,
  avgLatency: 0,
  p50Latency: 0,
  p95Latency: 0,
  p99Latency: 0,
  avgTtft: 0,
  p95Ttft: 0,
  avgPromptTps: 0,
  avgResponseTps: 0,

  // Aggregations
  byModel: [],
  byUsageType: [],
  byProject: [],
  timeline: [],
  recentErrors: [],
  recentEvents: [],

  // Meta
  uptimeSeconds: 0,
  bufferSize: 0,
  bufferCapacity: 0,
  filteredCount: 0,
  rangeFromTs: null,
  rangeToTs: null,

  // Time filters
  fromDateTime: "",
  toDateTime: "",
  bucket: "hour",
  rangeMode: "last24h",
  rangePickerOpen: false,

  // Polling
  _pollTimer: null,

  // Project expansion state
  _expandedProjects: {},

  switchTab(tab) {
    this.activeTab = tab;
  },

  async fetchMetrics() {
    try {
      this.loading = true;
      const r = await API.callJsonApi("/plugins/metrics/metrics_dashboard", this._snapshotPayload());
      if (!r.success) return;

      this.totalCalls = r.total_calls;
      this.successCalls = r.success_calls;
      this.failedCalls = r.failed_calls;
      this.totalTokensIn = r.total_tokens_in;
      this.totalTokensOut = r.total_tokens_out;
      this.avgLatency = r.avg_latency_ms;
      this.p50Latency = r.p50_latency_ms;
      this.p95Latency = r.p95_latency_ms;
      this.p99Latency = r.p99_latency_ms;
      this.avgTtft = r.avg_ttft_ms;
      this.p95Ttft = r.p95_ttft_ms;
      this.avgPromptTps = r.avg_prompt_tps;
      this.avgResponseTps = r.avg_response_tps;
      this.byModel = r.by_model || [];
      this.byUsageType = r.by_usage_type || [];
      this.byProject = r.by_project || [];
      this.timeline = r.timeline || [];
      this.recentErrors = r.recent_errors || [];
      this.recentEvents = r.recent_events || [];
      this.uptimeSeconds = r.uptime_seconds;
      this.bufferSize = r.buffer_size;
      this.bufferCapacity = r.buffer_capacity;
      this.filteredCount = r.filtered_count;
      this.rangeFromTs = r.range_from_ts;
      this.rangeToTs = r.range_to_ts;
      this.error = null;
    } catch (e) {
      this.error = e.message;
    } finally {
      this.loading = false;
    }
  },

  onOpen() {
    if (!this.fromDateTime || !this.toDateTime) {
      this.setLast24Hours();
    }
    this.fetchMetrics();
    this._pollTimer = setInterval(() => this.fetchMetrics(), 5000);
  },

  cleanup() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },

  toggleProject(name) {
    this._expandedProjects[name] = !this._expandedProjects[name];
  },

  isProjectExpanded(name) {
    return !!this._expandedProjects[name];
  },

  setLast24Hours() {
    const to = new Date();
    const from = new Date(to.getTime() - 24 * 60 * 60 * 1000);
    this.fromDateTime = this._toLocalDateTimeInput(from);
    this.toDateTime = this._toLocalDateTimeInput(to);
    this.bucket = "hour";
    this.rangeMode = "last24h";
  },

  resetRange() {
    this.setLast24Hours();
    this.rangePickerOpen = false;
    this.fetchMetrics();
  },

  applyFilters() {
    this.rangeMode = "custom";
    this.rangePickerOpen = false;
    this.fetchMetrics();
  },

  toggleRangePicker() {
    this.rangePickerOpen = !this.rangePickerOpen;
  },

  _snapshotPayload() {
    const range = this._currentRange();
    return {
      action: "snapshot",
      from_ts: range.from.toISOString(),
      to_ts: range.to.toISOString(),
      bucket: this.bucket || "hour",
    };
  },

  _currentRange() {
    if (this.rangeMode === "last24h") {
      const to = new Date();
      const from = new Date(to.getTime() - 24 * 60 * 60 * 1000);
      this.fromDateTime = this._toLocalDateTimeInput(from);
      this.toDateTime = this._toLocalDateTimeInput(to);
      return { from, to };
    }

    const from = this._dateFromInput(this.fromDateTime);
    const to = this._dateFromInput(this.toDateTime);
    if (from && to) return { from, to };

    const fallbackTo = new Date();
    return {
      from: new Date(fallbackTo.getTime() - 24 * 60 * 60 * 1000),
      to: fallbackTo,
    };
  },

  _toIsoFromInput(value) {
    const d = this._dateFromInput(value);
    return d ? d.toISOString() : null;
  },

  _dateFromInput(value) {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  },

  _toLocalDateTimeInput(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return [
      date.getFullYear(),
      pad(date.getMonth() + 1),
      pad(date.getDate()),
    ].join("-") + "T" + [pad(date.getHours()), pad(date.getMinutes())].join(":");
  },

  // Formatting
  fmtNum(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return String(n);
  },

  fmtLatency(ms) {
    if (ms >= 60_000) return (ms / 60_000).toFixed(1) + "m";
    if (ms >= 1000) return (ms / 1000).toFixed(2) + "s";
    return ms + "ms";
  },

  fmtUptime(s) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h > 0 ? h + "h " + m + "m" : m + "m";
  },

  fmtTps(v) {
    return typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "—";
  },

  successRate() {
    if (this.totalCalls === 0) return "—";
    return ((this.successCalls / this.totalCalls) * 100).toFixed(1) + "%";
  },

  avgTokensInPerCall() {
    return this.totalCalls ? this.fmtNum(Math.round(this.totalTokensIn / this.totalCalls)) : "0";
  },

  avgTokensOutPerCall() {
    return this.totalCalls ? this.fmtNum(Math.round(this.totalTokensOut / this.totalCalls)) : "0";
  },

  activityTitle() {
    return this.bucket === "day" ? "Activity by day" : "Activity by hour";
  },

  rangeLabel() {
    if (this.rangeMode === "last24h") return "Last 24h";
    return `${this._shortDateTime(this.fromDateTime)} - ${this._shortDateTime(this.toDateTime)}`;
  },

  _shortDateTime(value) {
    const d = this._dateFromInput(value);
    if (!d) return "Invalid";
    return d.toLocaleString([], {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  },

  fmtTime(ts) {
    if (!ts) return "";
    try {
      const hasOffset = /[+-]\d{2}:\d{2}$/.test(ts) || ts.endsWith("Z");
      const d = new Date(hasOffset ? ts : ts + "Z");
      if (isNaN(d.getTime())) return ts;
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch { return ts; }
  },

  sparklinePath(data, key, w, h) {
    if (!data || data.length < 2) return "";
    const vals = data.map(d => d[key] || 0);
    const max = Math.max(...vals, 1);
    const step = w / (vals.length - 1);
    return vals.map((v, i) => {
      const x = i * step, y = h - (v / max) * h;
      return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
    }).join("");
  },

  maxOf(arr, key) {
    if (!arr || !arr.length) return 1;
    return Math.max(...arr.map(x => x[key] || 0), 1);
  },

  maxTokenSplit(arr) {
    if (!arr || !arr.length) return 1;
    return Math.max(...arr.flatMap(x => [x.tokens_in || 0, x.tokens_out || 0]), 1);
  },
};

export const store = createStore("metricsDashboard", metricsStore);
