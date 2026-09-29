from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.dashboard import compute_dashboard_metrics, render_dashboard_html


def main() -> None:
    data = compute_dashboard_metrics(window_minutes=60)
    p = data["panels"]

    print("=" * 60)
    print(" K4-L3A Day 13 Monitoring & LLMOps - 6 Panels Dashboard")
    print(f" Source: data/logs.jsonl | Window: {data['time_range_minutes']}m | Records: {data['records_count']}")
    print("=" * 60)

    print(f"\n1. [Latency & TTFT] ({p['latency']['status']})")
    print(f"   P50: {p['latency']['p50']}ms | P95: {p['latency']['p95']}ms | P99: {p['latency']['p99']}ms | TTFT(P95): {p['latency']['ttft_p95']}ms")
    print(f"   Threshold: P95 <= 3000ms -> {p['latency']['status']}")

    print(f"\n2. [Request Traffic] ({p['traffic']['status']})")
    print(f"   Total requests: {p['traffic']['count']} | Rate: {p['traffic']['rate_per_minute']} req/min")
    print(f"   Threshold: Rate >= 1 req/min -> {p['traffic']['status']}")

    print(f"\n3. [Errors & Retrieval] ({p['errors']['status']})")
    print(f"   Error rate: {p['errors']['error_rate_pct']}% | Retrieval success: {p['errors']['tool_success_rate_pct']}%")
    print(f"   Error breakdown: {p['errors']['error_types'] or 'None'}")
    print(f"   Threshold: Error rate <= 2% -> {p['errors']['status']}")

    print(f"\n4. [Cost Over Time] ({p['cost']['status']})")
    print(f"   Total cost: ${p['cost']['total']:.4f} USD")
    print(f"   Threshold: Total <= $2.50 USD -> {p['cost']['status']}")

    print(f"\n5. [Input & Output Tokens] ({p['tokens']['status']})")
    print(f"   Tokens in: {p['tokens']['tokens_in']} | Tokens out: {p['tokens']['tokens_out']} | Total: {p['tokens']['total']}")
    print(f"   Threshold: Total <= 50,000 tokens -> {p['tokens']['status']}")

    print(f"\n6. [Quality Proxy] ({p['quality']['status']})")
    print(f"   Mean score: {p['quality']['mean']} / 1.0")
    print(f"   Threshold: Mean >= 0.75 -> {p['quality']['status']}")
    print("=" * 60)

    print("\n--- Recent Logs Explorer (Latest 8 records) ---")
    print(f"{'Timestamp':19} | {'Event':17} | {'Correlation ID':15} | {'Model':18} | {'Env':5} | {'Feature':10} | {'Latency':10}")
    print("-" * 105)
    for log in data.get("logs", [])[:8]:
        ts = str(log.get('timestamp', log.get('ts', '-')))[:19]
        evt = str(log.get('event', '-'))[:17]
        cid = str(log.get('correlation_id', '-'))[:15]
        mdl = str(log.get('model', '-'))[:18]
        env = str(log.get('env', '-'))[:5]
        feat = str(log.get('feature', '-'))[:10]
        lat = f"{log.get('latency', 0)}ms"
        print(f"{ts:19} | {evt:17} | {cid:15} | {mdl:18} | {env:5} | {feat:10} | {lat:10}")

    sample_log = data.get("logs", [])[0] if data.get("logs") else None
    if sample_log:
        print("\n--- Sample Full JSON Record (Standard Format) ---")
        print(sample_log.get("raw_json", "{}"))

    output_path = REPO_ROOT / "data" / "dashboard.html"
    output_path.write_text(render_dashboard_html(), encoding="utf-8")
    print(f"\n[OK] Dashboard HTML saved to: {output_path}")
    print(f"     View live web dashboard at: http://127.0.0.1:8000/dashboard")


if __name__ == "__main__":
    main()
