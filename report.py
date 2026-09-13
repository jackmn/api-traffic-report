#!/usr/bin/env python3
"""Read a JSONL API log and print a traffic report as JSON to stdout."""

import sys
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

# >100 requests from one client in any trailing 60s window. See README.
RATE_LIMIT_THRESHOLD = 100
RATE_LIMIT_WINDOW_SECONDS = 60

REQUIRED_FIELDS = {"request_id", "timestamp", "client_id", "endpoint", "status_code"}


def parse_timestamp(ts):
    if not isinstance(ts, str):
        raise ValueError("timestamp is not a string")
    # fromisoformat didn't accept Z before 3.11
    normalized = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_line(line):
    record = json.loads(line)

    if not isinstance(record, dict):
        raise ValueError("line is not a JSON object")

    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")

    if not isinstance(record["request_id"], str):
        raise ValueError("request_id is not a string")
    if not isinstance(record["client_id"], str):
        raise ValueError("client_id is not a string")
    if not isinstance(record["endpoint"], str):
        raise ValueError("endpoint is not a string")
    if not isinstance(record["status_code"], int) or isinstance(record["status_code"], bool):
        raise ValueError("status_code is not an integer")

    timestamp = parse_timestamp(record["timestamp"])

    return {
        "request_id": record["request_id"],
        "timestamp": timestamp,
        "raw_timestamp": record["timestamp"],
        "client_id": record["client_id"],
        "endpoint": record["endpoint"],
        "status_code": record["status_code"],
    }


def detect_rate_limit_violations(requests_by_client):
    """Flag clients with >RATE_LIMIT_THRESHOLD requests in any 60s window."""
    violations = []

    for client_id, reqs in requests_by_client.items():
        sorted_reqs = sorted(reqs, key=lambda r: r["timestamp"])
        timestamps = [r["timestamp"] for r in sorted_reqs]

        window_start = 0
        first_violation_at = None
        violation_count = 0

        for i, current_ts in enumerate(timestamps):
            while (current_ts - timestamps[window_start]).total_seconds() > RATE_LIMIT_WINDOW_SECONDS:
                window_start += 1

            if i - window_start + 1 > RATE_LIMIT_THRESHOLD:
                violation_count += 1
                if first_violation_at is None:
                    first_violation_at = sorted_reqs[i]["raw_timestamp"]

        if violation_count > 0:
            violations.append({
                "client_id": client_id,
                "first_violation_at": first_violation_at,
                "violation_count": violation_count,
            })

    violations.sort(key=lambda v: v["client_id"])
    return violations


def build_report(path):
    total_requests = 0
    malformed_requests = 0
    per_endpoint = Counter()
    per_status_code = Counter()
    error_requests_per_endpoint = Counter()
    requests_by_client = defaultdict(list)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            total_requests += 1
            try:
                record = parse_line(line)
            except (ValueError, json.JSONDecodeError):
                malformed_requests += 1
                continue

            per_endpoint[record["endpoint"]] += 1
            per_status_code[str(record["status_code"])] += 1
            if not (200 <= record["status_code"] < 300):
                error_requests_per_endpoint[record["endpoint"]] += 1
            requests_by_client[record["client_id"]].append(record)

    return {
        "total_requests": total_requests,
        "valid_requests": total_requests - malformed_requests,
        "malformed_requests": malformed_requests,
        "per_endpoint": dict(per_endpoint),
        "per_status_code": dict(per_status_code),
        "error_requests_per_endpoint": dict(error_requests_per_endpoint),
        "rate_limit_violations": detect_rate_limit_violations(requests_by_client),
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: python report.py <path-to-jsonl-file>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]

    try:
        report = build_report(path)
    except FileNotFoundError:
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except IsADirectoryError:
        print(f"Error: expected a file, got a directory: {path}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: permission denied reading file: {path}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
