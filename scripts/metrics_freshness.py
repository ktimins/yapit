"""Metrics pipeline freshness: age of the newest metrics event, cross-checked against gateway logs.

Run by report.sh after sync-data. A metrics DB that stops receiving events looks
identical to a quiet day unless compared against log activity — this makes the
distinction deterministic instead of leaving it to the analysis agent to notice.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

DB_PATH = Path("data/metrics.duckdb")
LOG_PATH = Path("data/logs/gateway.jsonl")
STALE_AFTER_H = 3.0
LOG_GAP_ALERT_H = 1.0


def main() -> None:
    now = datetime.now(UTC)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    last_event = con.execute("SELECT max(timestamp) FROM metrics_event").fetchone()[0]  # ty: ignore[possibly-unbound-implicit-call]
    assert last_event is not None, "metrics_event table is empty"
    event_age_h = (now - last_event).total_seconds() / 3600
    print(f"Last metrics event:  {last_event:%Y-%m-%d %H:%M:%S %Z} ({event_age_h:.1f}h ago)")

    last_log = _last_log_time()
    if last_log is not None:
        log_age_h = (now - last_log).total_seconds() / 3600
        print(f"Last gateway log:    {last_log:%Y-%m-%d %H:%M:%S %Z} ({log_age_h:.1f}h ago)")

    if event_age_h <= STALE_AFTER_H:
        print("✅ FRESH — metrics pipeline is live.")
        return

    log_gap_h = (last_log - last_event).total_seconds() / 3600 if last_log else None
    if log_gap_h is not None and log_gap_h > LOG_GAP_ALERT_H:
        print(
            f"🚨 STALE — gateway logged activity {log_gap_h:.1f}h past the last metrics event. "
            "The metrics pipeline is DOWN (P0). Lead the report with this; "
            "all metrics-based sections only cover the period before the gap."
        )
        return
    print(
        f"⚠️ No metrics events for {event_age_h:.1f}h, but logs are similarly quiet — "
        "possibly just low traffic. Verify against log activity before concluding either way."
    )


def _last_log_time() -> datetime | None:
    """Timestamp of the last line in the current gateway log (reads only the file tail)."""
    if not LOG_PATH.exists():
        return None
    with LOG_PATH.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 65536))
        lines = f.read().splitlines()
    for raw in reversed(lines):
        try:
            ts = json.loads(raw)["record"]["time"]["timestamp"]
            return datetime.fromtimestamp(ts, tz=UTC)
        except (json.JSONDecodeError, KeyError):
            continue  # partial first line from the seek, or malformed entry
    return None


if __name__ == "__main__":
    main()
