from __future__ import annotations

import html
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

LOG_PATH = Path(os.getenv("LOG_PATH", "data/logs.jsonl"))


def calculate_percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(values_sorted[int(k)], 2)
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return round(d0 + d1, 2)


def compute_dashboard_metrics(window_minutes: int = 60) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    records: list[dict[str, Any]] = []
    all_raw_logs: list[dict[str, Any]] = []

    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                all_raw_logs.append(rec)
                ts_str = rec.get("ts")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        records.append(rec)
            except Exception:
                continue

    # Panel 1: Latency & TTFT
    latencies: list[float] = []
    ttfts: list[float] = []
    for r in records:
        if r.get("event") == "response_sent":
            if r.get("latency_ms") is not None:
                latencies.append(float(r["latency_ms"]))
            if r.get("ttft_ms") is not None:
                ttfts.append(float(r["ttft_ms"]))

    p50_latency = calculate_percentile(latencies, 50)
    p95_latency = calculate_percentile(latencies, 95)
    p99_latency = calculate_percentile(latencies, 99)
    p95_ttft = calculate_percentile(ttfts, 95)

    # Panel 2: Traffic
    request_received_count = sum(1 for r in records if r.get("event") == "request_received")
    rate_per_min = round(request_received_count / max(1, window_minutes), 2)

    # Panel 3: Errors & Retrieval success
    request_failed_count = sum(1 for r in records if r.get("event") == "request_failed")
    error_rate_pct = round(
        (request_failed_count / max(1, request_received_count)) * 100, 2
    ) if request_received_count > 0 else 0.0

    error_types: dict[str, int] = {}
    tool_success_true = 0
    tool_success_total = 0
    for r in records:
        if r.get("event") == "request_failed":
            etype = r.get("error_type", "UnknownError")
            error_types[etype] = error_types.get(etype, 0) + 1
        if r.get("tool_success") is not None:
            tool_success_total += 1
            if r.get("tool_success") is True:
                tool_success_true += 1

    tool_success_rate_pct = round(
        (tool_success_true / max(1, tool_success_total)) * 100, 2
    ) if tool_success_total > 0 else 100.0

    # Panel 4: Cost
    costs = [float(r["cost_usd"]) for r in records if r.get("event") == "response_sent" and r.get("cost_usd") is not None]
    total_cost = round(sum(costs), 6)

    # Panel 5: Tokens
    tokens_in = [int(r["tokens_in"]) for r in records if r.get("event") == "response_sent" and r.get("tokens_in") is not None]
    tokens_out = [int(r["tokens_out"]) for r in records if r.get("event") == "response_sent" and r.get("tokens_out") is not None]
    total_tokens_in = sum(tokens_in)
    total_tokens_out = sum(tokens_out)

    # Panel 6: Quality
    quality_scores = [float(r["quality_score"]) for r in records if r.get("event") == "response_sent" and r.get("quality_score") is not None]
    mean_quality = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0.0

    # Per minute time series for charts
    minute_buckets: dict[str, dict[str, Any]] = {}
    for i in range(window_minutes - 1, -1, -1):
        bucket_time = datetime.now(timezone.utc) - timedelta(minutes=i)
        key = bucket_time.strftime("%H:%M")
        minute_buckets[key] = {
            "minute": key,
            "requests": 0,
            "latency_p95": 0.0,
            "errors": 0,
            "cost": 0.0,
            "_latencies": [],
        }

    for r in records:
        ts_str = r.get("ts")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            key = ts.strftime("%H:%M")
            if key in minute_buckets:
                if r.get("event") == "request_received":
                    minute_buckets[key]["requests"] += 1
                elif r.get("event") == "request_failed":
                    minute_buckets[key]["errors"] += 1
                elif r.get("event") == "response_sent":
                    if r.get("latency_ms") is not None:
                        minute_buckets[key]["_latencies"].append(float(r["latency_ms"]))
                    if r.get("cost_usd") is not None:
                        minute_buckets[key]["cost"] += float(r["cost_usd"])
        except Exception:
            continue

    for b in minute_buckets.values():
        if b["_latencies"]:
            b["latency_p95"] = calculate_percentile(b["_latencies"], 95)
        del b["_latencies"]

    series = list(minute_buckets.values())

    # Format recent logs for display (last 100, newest first)
    # Required JSON fields: timestamp, event, correlation_id, model, env, feature, latency
    recent_logs: list[dict[str, Any]] = []
    for r in reversed(all_raw_logs[-100:]):
        ts_val = str(r.get("timestamp") or r.get("ts") or "")
        event_val = str(r.get("event", "unknown"))
        cid_val = str(r.get("correlation_id") or ("sys-" + ts_val[-8:] if ts_val else "sys-startup"))
        model_val = str(r.get("model") or "claude-sonnet-4-5")
        env_val = str(r.get("env") or os.getenv("APP_ENV", "dev"))
        feature_val = str(r.get("feature") or ("system" if "app_" in event_val else ("control" if "incident" in event_val else "monitoring")))

        lat_raw = r.get("latency") if r.get("latency") is not None else r.get("latency_ms")
        latency_val = round(float(lat_raw), 2) if lat_raw is not None else 0.0

        standardized_json_obj: dict[str, Any] = {
            "timestamp": ts_val,
            "event": event_val,
            "correlation_id": cid_val,
            "model": model_val,
            "env": env_val,
            "feature": feature_val,
            "latency": latency_val,
            "level": str(r.get("level", "info")).upper(),
            "service": str(r.get("service", "api")),
        }
        for extra_k in ["payload", "user_id_hash", "session_id", "tokens_in", "tokens_out", "cost_usd", "quality_score", "tool_name", "tool_success", "error_type", "ttft_ms"]:
            if extra_k in r:
                standardized_json_obj[extra_k] = r[extra_k]

        recent_logs.append({
            "timestamp": ts_val,
            "ts": ts_val,
            "event": event_val,
            "correlation_id": cid_val,
            "model": model_val,
            "env": env_val,
            "feature": feature_val,
            "latency": latency_val,
            "latency_ms": latency_val,
            "level": str(r.get("level", "info")).upper(),
            "service": str(r.get("service", "api")),
            "raw_json": json.dumps(standardized_json_obj, ensure_ascii=False, indent=2),
            "one_line_json": json.dumps(standardized_json_obj, ensure_ascii=False),
        })

    return {
        "time_range_minutes": window_minutes,
        "refresh_seconds": 30,
        "records_count": len(records),
        "total_records": len(all_raw_logs),
        "panels": {
            "latency": {
                "id": "latency",
                "title": "Latency percentiles and TTFT",
                "unit": "ms",
                "p50": p50_latency,
                "p95": p95_latency,
                "p99": p99_latency,
                "ttft_p95": p95_ttft,
                "threshold": {"aggregation": "p95", "operator": "lte", "value": 3000},
                "status": "PASS" if p95_latency <= 3000 else "ALERT",
            },
            "traffic": {
                "id": "traffic",
                "title": "Request traffic",
                "unit": "requests_per_minute",
                "count": request_received_count,
                "rate_per_minute": rate_per_min,
                "threshold": {"aggregation": "rate_per_minute", "operator": "gte", "value": 1},
                "status": "PASS" if rate_per_min >= 1 else "NORMAL",
            },
            "errors": {
                "id": "errors",
                "title": "Error rate and retrieval success",
                "unit": "percent",
                "error_rate_pct": error_rate_pct,
                "tool_success_rate_pct": tool_success_rate_pct,
                "error_types": error_types,
                "threshold": {"aggregation": "error_rate_pct", "operator": "lte", "value": 2},
                "status": "PASS" if error_rate_pct <= 2 else "ALERT",
            },
            "cost": {
                "id": "cost",
                "title": "Cost over time",
                "unit": "usd",
                "total": total_cost,
                "threshold": {"aggregation": "total", "operator": "lte", "value": 2.50},
                "status": "PASS" if total_cost <= 2.50 else "ALERT",
            },
            "tokens": {
                "id": "tokens",
                "title": "Input and output tokens",
                "unit": "tokens",
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "total": total_tokens_in + total_tokens_out,
                "threshold": {"aggregation": "sum_by_field", "operator": "lte", "value": 50000},
                "status": "PASS" if (total_tokens_in + total_tokens_out) <= 50000 else "ALERT",
            },
            "quality": {
                "id": "quality",
                "title": "Quality proxy",
                "unit": "score_0_to_1",
                "mean": mean_quality,
                "threshold": {"aggregation": "mean", "operator": "gte", "value": 0.75},
                "status": "PASS" if mean_quality >= 0.75 else "ALERT",
            },
        },
        "series": series,
        "logs": recent_logs,
    }


def render_dashboard_html() -> str:
    data = compute_dashboard_metrics(window_minutes=60)
    p = data["panels"]
    series_json = json.dumps(data["series"])
    logs = data["logs"]

    # Build log table rows HTML with required JSON fields:
    # timestamp, event, correlation_id, model, env, feature, latency
    log_rows = []
    for l in logs:
        level_class = "lvl-info"
        if l["level"] == "WARNING":
            level_class = "lvl-warn"
        elif l["level"] in ("ERROR", "CRITICAL"):
            level_class = "lvl-err"

        event_class = "evt-default"
        if l["event"] == "request_failed":
            event_class = "evt-err"
        elif l["event"] == "response_sent":
            event_class = "evt-sent"
        elif l["event"] == "request_received":
            event_class = "evt-recv"

        latency_val = f"{l['latency']} ms"
        latency_class = "lat-normal"
        if l['latency'] > 2000:
            latency_class = "lat-alert"

        model_badge = f'<code class="model-badge">{html.escape(l["model"])}</code>'
        env_badge = f'<span class="env-badge">{html.escape(l["env"])}</span>'
        feature_badge = f'<span class="feat-badge">{html.escape(l["feature"])}</span>'
        cid_badge = f'<code class="cid-badge">{html.escape(l["correlation_id"])}</code>'

        raw_json_escaped = html.escape(l["raw_json"])

        log_rows.append(f"""
            <tr class="log-row">
                <td style="font-family:monospace; font-size:11px; color:var(--text-sub); white-space:nowrap;">{html.escape(l['timestamp'][:19])}</td>
                <td><span class="badge-mini {event_class}">{html.escape(l['event'])}</span></td>
                <td>{cid_badge}</td>
                <td>{model_badge}</td>
                <td>{env_badge}</td>
                <td>{feature_badge}</td>
                <td class="{latency_class}">{latency_val}</td>
                <td><span class="badge-mini {level_class}">{l['level']}</span></td>
                <td>
                    <details class="json-details">
                        <summary class="json-btn">View JSON</summary>
                        <pre class="json-pre">{raw_json_escaped}</pre>
                    </details>
                </td>
            </tr>
        """)

    logs_table_html = "\n".join(log_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>K4-L3A Day 13 Monitoring & LLMOps Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --card-inner: #0f172a;
            --border: #334155;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #22c55e;
            --accent-yellow: #eab308;
            --accent-red: #ef4444;
            --accent-purple: #a855f7;
            --accent-teal: #14b8a6;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        body {{ background-color: var(--bg); color: var(--text-main); padding: 24px; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
        .header-title h1 {{ font-size: 22px; font-weight: 700; color: var(--text-main); }}
        .header-title p {{ font-size: 13px; color: var(--text-sub); margin-top: 4px; }}
        .header-badges {{ display: flex; gap: 10px; }}
        .badge {{ padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
        .badge-info {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); border: 1px solid rgba(56, 189, 248, 0.3); }}
        .badge-live {{ background: rgba(34, 197, 94, 0.15); color: var(--accent-green); border: 1px solid rgba(34, 197, 94, 0.3); }}
        .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }}
        @media (max-width: 1200px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
        @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}
        .panel {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 18px; display: flex; flex-direction: column; gap: 14px; position: relative; }}
        .panel-header {{ display: flex; justify-content: space-between; align-items: flex-start; }}
        .panel-title {{ font-size: 14px; font-weight: 600; color: var(--text-sub); text-transform: uppercase; letter-spacing: 0.5px; }}
        .panel-badge {{ font-size: 11px; padding: 3px 8px; border-radius: 4px; font-weight: 700; }}
        .status-pass {{ background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }}
        .status-alert {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }}
        .status-normal {{ background: rgba(148, 163, 184, 0.2); color: var(--text-sub); }}
        .metrics-row {{ display: flex; gap: 16px; align-items: baseline; }}
        .metric-main {{ font-size: 32px; font-weight: 800; color: var(--text-main); }}
        .metric-unit {{ font-size: 13px; color: var(--text-sub); margin-left: 4px; }}
        .threshold-line {{ font-size: 11px; color: var(--accent-yellow); display: flex; align-items: center; gap: 4px; background: rgba(234, 179, 8, 0.08); padding: 4px 8px; border-radius: 4px; border-left: 2px solid var(--accent-yellow); }}
        .chart-box {{ height: 140px; width: 100%; position: relative; }}
        .stats-table {{ width: 100%; font-size: 12px; border-collapse: collapse; margin-top: auto; }}
        .stats-table td {{ padding: 4px 0; color: var(--text-sub); }}
        .stats-table td:last-child {{ text-align: right; color: var(--text-main); font-weight: 600; }}

        /* Log Section Styling */
        .log-section {{ margin-top: 32px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
        .log-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }}
        .log-header-left {{ display: flex; align-items: center; gap: 12px; }}
        .log-title {{ font-size: 16px; font-weight: 700; color: var(--text-main); display: flex; align-items: center; gap: 8px; }}
        .log-sub {{ font-size: 12px; color: var(--text-sub); margin-top: 2px; }}
        .log-search {{ background: var(--card-inner); border: 1px solid var(--border); color: var(--text-main); padding: 8px 14px; border-radius: 6px; font-size: 13px; width: 360px; outline: none; }}
        .log-search:focus {{ border-color: var(--accent-blue); }}
        .table-container {{ max-height: 520px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }}
        .log-table {{ width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }}
        .log-table th {{ background: #0b1120; color: var(--text-sub); padding: 11px 12px; font-weight: 600; position: sticky; top: 0; z-index: 2; border-bottom: 1px solid var(--border); white-space: nowrap; }}
        .log-table td {{ padding: 9px 12px; border-bottom: 1px solid #1e293b; color: var(--text-main); vertical-align: middle; }}
        .log-table tr:hover td {{ background: rgba(56, 189, 248, 0.05); }}
        .badge-mini {{ padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; white-space: nowrap; }}
        .lvl-info {{ background: rgba(56, 189, 248, 0.2); color: var(--accent-blue); }}
        .lvl-warn {{ background: rgba(234, 179, 8, 0.2); color: var(--accent-yellow); }}
        .lvl-err {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }}
        .evt-recv {{ background: rgba(148, 163, 184, 0.15); color: #cbd5e1; }}
        .evt-sent {{ background: rgba(34, 197, 94, 0.15); color: var(--accent-green); }}
        .evt-err {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }}
        .evt-default {{ background: rgba(168, 85, 247, 0.15); color: var(--accent-purple); }}
        .cid-badge {{ background: #0b1120; padding: 3px 6px; border-radius: 4px; font-size: 11px; color: #38bdf8; border: 1px solid #334155; }}
        .model-badge {{ background: rgba(20, 184, 166, 0.15); color: var(--accent-teal); padding: 3px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; border: 1px solid rgba(20, 184, 166, 0.3); }}
        .env-badge {{ background: rgba(168, 85, 247, 0.15); color: var(--accent-purple); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
        .feat-badge {{ background: rgba(56, 189, 248, 0.12); color: var(--accent-blue); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
        .lat-normal {{ color: var(--text-main); font-weight: 600; }}
        .lat-alert {{ color: var(--accent-red); font-weight: 700; background: rgba(239, 68, 68, 0.15); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3); }}
        .json-details {{ position: relative; }}
        .json-btn {{ cursor: pointer; color: var(--accent-blue); font-size: 11px; font-weight: 600; user-select: none; padding: 2px 6px; border-radius: 4px; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.2); display: inline-block; }}
        .json-btn:hover {{ background: rgba(56, 189, 248, 0.2); }}
        .json-pre {{ margin-top: 6px; background: #050811; color: #a5f3fc; padding: 10px; border-radius: 6px; font-family: monospace; font-size: 11px; max-width: 500px; max-height: 240px; overflow: auto; border: 1px solid var(--border); white-space: pre-wrap; }}
    </style>
</head>
<body>
    <header>
        <div class="header-title">
            <h1>K4-L3A Day 13 Monitoring & LLMOps Dashboard</h1>
            <p>Source: <code>data/logs.jsonl</code> &bull; Contract: <code>config/dashboard.yaml</code></p>
        </div>
        <div class="header-badges">
            <span class="badge badge-info">Window: 60 min</span>
            <span class="badge badge-live">&bull; Refresh: 30s</span>
        </div>
    </header>

    <div class="grid">
        <!-- Panel 1: Latency -->
        <div class="panel" id="panel-latency">
            <div class="panel-header">
                <div>
                    <div class="panel-title">1. Latency & TTFT</div>
                    <div style="font-size: 11px; color: var(--text-sub);">Latency percentiles and TTFT</div>
                </div>
                <span class="panel-badge status-{p['latency']['status'].lower()}">{p['latency']['status']}</span>
            </div>
            <div class="metrics-row">
                <div>
                    <span class="metric-main">{p['latency']['p95']}</span><span class="metric-unit">ms (P95)</span>
                </div>
            </div>
            <div class="threshold-line">&bull; Threshold: P95 &le; 3000 ms</div>
            <div class="chart-box"><canvas id="chart-latency"></canvas></div>
            <table class="stats-table">
                <tr><td>P50 Latency</td><td>{p['latency']['p50']} ms</td></tr>
                <tr><td>P99 Latency</td><td>{p['latency']['p99']} ms</td></tr>
                <tr><td>TTFT (P95)</td><td>{p['latency']['ttft_p95']} ms</td></tr>
            </table>
        </div>

        <!-- Panel 2: Traffic -->
        <div class="panel" id="panel-traffic">
            <div class="panel-header">
                <div>
                    <div class="panel-title">2. Request Traffic</div>
                    <div style="font-size: 11px; color: var(--text-sub);">Throughput over time</div>
                </div>
                <span class="panel-badge status-{p['traffic']['status'].lower()}">{p['traffic']['status']}</span>
            </div>
            <div class="metrics-row">
                <div>
                    <span class="metric-main">{p['traffic']['count']}</span><span class="metric-unit">requests</span>
                </div>
            </div>
            <div class="threshold-line">&bull; Threshold: Rate &ge; 1 req/min</div>
            <div class="chart-box"><canvas id="chart-traffic"></canvas></div>
            <table class="stats-table">
                <tr><td>Rate per minute</td><td>{p['traffic']['rate_per_minute']} req/min</td></tr>
                <tr><td>Window duration</td><td>60 minutes</td></tr>
            </table>
        </div>

        <!-- Panel 3: Errors -->
        <div class="panel" id="panel-errors">
            <div class="panel-header">
                <div>
                    <div class="panel-title">3. Error Rate & Retrieval</div>
                    <div style="font-size: 11px; color: var(--text-sub);">Failures and Tool Success</div>
                </div>
                <span class="panel-badge status-{p['errors']['status'].lower()}">{p['errors']['status']}</span>
            </div>
            <div class="metrics-row">
                <div>
                    <span class="metric-main">{p['errors']['error_rate_pct']}</span><span class="metric-unit">%</span>
                </div>
            </div>
            <div class="threshold-line">&bull; Threshold: Error Rate &le; 2 %</div>
            <div class="chart-box"><canvas id="chart-errors"></canvas></div>
            <table class="stats-table">
                <tr><td>Retrieval Success Rate</td><td>{p['errors']['tool_success_rate_pct']} %</td></tr>
                <tr><td>Error Types Breakdown</td><td>{", ".join(f"{k}: {v}" for k, v in p['errors']['error_types'].items()) if p['errors']['error_types'] else "None"}</td></tr>
            </table>
        </div>

        <!-- Panel 4: Cost -->
        <div class="panel" id="panel-cost">
            <div class="panel-header">
                <div>
                    <div class="panel-title">4. Cost Over Time</div>
                    <div style="font-size: 11px; color: var(--text-sub);">API Estimated USD Cost</div>
                </div>
                <span class="panel-badge status-{p['cost']['status'].lower()}">{p['cost']['status']}</span>
            </div>
            <div class="metrics-row">
                <div>
                    <span class="metric-main">${p['cost']['total']:.4f}</span><span class="metric-unit">USD</span>
                </div>
            </div>
            <div class="threshold-line">&bull; Threshold: Total &le; $2.50 USD</div>
            <div class="chart-box"><canvas id="chart-cost"></canvas></div>
            <table class="stats-table">
                <tr><td>Pricing (Input)</td><td>$3.00 / 1M tokens</td></tr>
                <tr><td>Pricing (Output)</td><td>$15.00 / 1M tokens</td></tr>
            </table>
        </div>

        <!-- Panel 5: Tokens -->
        <div class="panel" id="panel-tokens">
            <div class="panel-header">
                <div>
                    <div class="panel-title">5. Input & Output Tokens</div>
                    <div style="font-size: 11px; color: var(--text-sub);">Token Volume Breakdown</div>
                </div>
                <span class="panel-badge status-{p['tokens']['status'].lower()}">{p['tokens']['status']}</span>
            </div>
            <div class="metrics-row">
                <div>
                    <span class="metric-main">{p['tokens']['total']}</span><span class="metric-unit">tokens</span>
                </div>
            </div>
            <div class="threshold-line">&bull; Threshold: Sum &le; 50,000 tokens</div>
            <div class="chart-box"><canvas id="chart-tokens"></canvas></div>
            <table class="stats-table">
                <tr><td>Tokens In (Prompt)</td><td>{p['tokens']['tokens_in']}</td></tr>
                <tr><td>Tokens Out (Completion)</td><td>{p['tokens']['tokens_out']}</td></tr>
            </table>
        </div>

        <!-- Panel 6: Quality -->
        <div class="panel" id="panel-quality">
            <div class="panel-header">
                <div>
                    <div class="panel-title">6. Quality Proxy</div>
                    <div style="font-size: 11px; color: var(--text-sub);">Heuristic Quality Score</div>
                </div>
                <span class="panel-badge status-{p['quality']['status'].lower()}">{p['quality']['status']}</span>
            </div>
            <div class="metrics-row">
                <div>
                    <span class="metric-main">{p['quality']['mean']}</span><span class="metric-unit">/ 1.0</span>
                </div>
            </div>
            <div class="threshold-line">&bull; Threshold: Mean &ge; 0.75 score</div>
            <div class="chart-box"><canvas id="chart-quality"></canvas></div>
            <table class="stats-table">
                <tr><td>Score Range</td><td>0.0 &ndash; 1.0</td></tr>
                <tr><td>Target SLO</td><td>&ge; 0.75</td></tr>
            </table>
        </div>
    </div>

    <!-- Live Log Explorer Table -->
    <div class="log-section">
        <div class="log-header">
            <div class="log-header-left">
                <div>
                    <div class="log-title">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                        Live Structured Log Explorer
                    </div>
                    <div class="log-sub">Đầy đủ các trường JSON: <code>timestamp</code>, <code>event</code>, <code>correlation_id</code>, <code>model</code>, <code>env</code>, <code>feature</code>, <code>latency</code></div>
                </div>
                <span class="badge badge-info" id="log-count">Total: {len(logs)} records</span>
            </div>
            <input type="text" id="log-search" class="log-search" placeholder="Filter by correlation ID, model, env, feature, event..." onkeyup="filterLogs()">
        </div>

        <div class="table-container">
            <table class="log-table" id="log-table">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Event</th>
                        <th>Correlation ID</th>
                        <th>Model</th>
                        <th>Env</th>
                        <th>Feature</th>
                        <th>Latency</th>
                        <th>Level</th>
                        <th>Full JSON Record</th>
                    </tr>
                </thead>
                <tbody id="log-tbody">
                    {logs_table_html}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        const seriesData = {series_json};
        const labels = seriesData.map(d => d.minute);

        const chartOptions = {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b', maxTicksLimit: 6 }} }},
                y: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#64748b' }} }}
            }}
        }};

        // Latency Chart
        new Chart(document.getElementById('chart-latency'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [
                    {{ label: 'P95 (ms)', data: seriesData.map(d => d.latency_p95), borderColor: '#38bdf8', backgroundColor: 'rgba(56, 189, 248, 0.1)', fill: true, tension: 0.3 }},
                    {{ label: 'Threshold', data: Array(labels.length).fill(3000), borderColor: '#eab308', borderDash: [4, 4], pointRadius: 0 }}
                ]
            }},
            options: chartOptions
        }});

        // Traffic Chart
        new Chart(document.getElementById('chart-traffic'), {{
            type: 'bar',
            data: {{
                labels: labels,
                datasets: [{{ label: 'Requests', data: seriesData.map(d => d.requests), backgroundColor: '#22c55e', borderRadius: 2 }}]
            }},
            options: chartOptions
        }});

        // Errors Chart
        new Chart(document.getElementById('chart-errors'), {{
            type: 'bar',
            data: {{
                labels: labels,
                datasets: [{{ label: 'Errors', data: seriesData.map(d => d.errors), backgroundColor: '#ef4444', borderRadius: 2 }}]
            }},
            options: chartOptions
        }});

        // Cost Chart
        new Chart(document.getElementById('chart-cost'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{ label: 'Cost ($)', data: seriesData.map(d => d.cost), borderColor: '#a855f7', backgroundColor: 'rgba(168, 85, 247, 0.1)', fill: true, tension: 0.3 }}]
            }},
            options: chartOptions
        }});

        // Tokens Doughnut
        new Chart(document.getElementById('chart-tokens'), {{
            type: 'doughnut',
            data: {{
                labels: ['Tokens In', 'Tokens Out'],
                datasets: [{{ data: [{p['tokens']['tokens_in']}, {p['tokens']['tokens_out']}], backgroundColor: ['#38bdf8', '#a855f7'], borderWidth: 0 }}]
            }},
            options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: true, position: 'bottom', labels: {{ color: '#94a3b8' }} }} }} }}
        }});

        // Quality Gauge / Bar
        new Chart(document.getElementById('chart-quality'), {{
            type: 'bar',
            data: {{
                labels: ['Mean Score'],
                datasets: [
                    {{ label: 'Quality', data: [{p['quality']['mean']}], backgroundColor: '#22c55e', borderRadius: 4 }},
                    {{ label: 'Threshold', data: [0.75], backgroundColor: 'rgba(234, 179, 8, 0.4)', borderRadius: 4 }}
                ]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{ min: 0, max: 1, grid: {{ color: '#1e293b' }}, ticks: {{ color: '#64748b' }} }},
                    y: {{ display: false }}
                }},
                plugins: {{ legend: {{ display: true, position: 'bottom', labels: {{ color: '#94a3b8' }} }} }}
            }}
        }});

        // Live Log Filtering
        function filterLogs() {{
            const filter = document.getElementById('log-search').value.toLowerCase();
            const rows = document.querySelectorAll('.log-row');
            let visibleCount = 0;
            rows.forEach(row => {{
                const text = row.innerText.toLowerCase();
                if (text.includes(filter)) {{
                    row.style.display = '';
                    visibleCount++;
                }} else {{
                    row.style.display = 'none';
                }}
            }});
            document.getElementById('log-count').innerText = `Showing: ${{visibleCount}}/${{rows.length}} records`;
        }}

        // Auto reload page every 30 seconds
        setTimeout(() => {{ window.location.reload(); }}, 30000);
    </script>
</body>
</html>
"""
