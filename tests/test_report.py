"""Smoke tests for report.py — sample input, malformed lines, rate limits."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import report

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INPUT = ROOT / "sample_input"


class BuildReportTests(unittest.TestCase):
    def test_sample_input(self):
        result = report.build_report(SAMPLE_INPUT / "requests.jsonl")

        self.assertEqual(result["total_requests"], 8)
        self.assertEqual(result["valid_requests"], 8)
        self.assertEqual(result["malformed_requests"], 0)
        self.assertEqual(result["per_endpoint"], {"/v1/widgets": 6, "/v1/reports": 2})
        self.assertEqual(result["per_status_code"], {"200": 8})
        self.assertEqual(result["error_requests_per_endpoint"], {})
        self.assertEqual(result["rate_limit_violations"], [])

    def test_malformed_and_blank_lines(self):
        content = "\n".join([
            '{"request_id":"ok_1","timestamp":"2024-01-15T10:00:00Z","client_id":"acct_1","endpoint":"/v1/widgets","status_code":200}',
            "not json",
            '{"request_id":"missing_fields"}',
            '{"request_id":"bad_status","timestamp":"2024-01-15T10:00:01Z","client_id":"acct_1","endpoint":"/v1/widgets","status_code":true}',
            "",
            '{"request_id":"naive_ts","timestamp":"2024-01-15T10:00:02","client_id":"acct_1","endpoint":"/v1/widgets","status_code":500}',
        ]) + "\n"

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            path = f.name

        try:
            result = report.build_report(path)
        finally:
            Path(path).unlink()

        self.assertEqual(result["total_requests"], 5)
        self.assertEqual(result["valid_requests"], 2)
        self.assertEqual(result["malformed_requests"], 3)
        self.assertEqual(result["per_endpoint"], {"/v1/widgets": 2})
        self.assertEqual(result["per_status_code"], {"200": 1, "500": 1})
        self.assertEqual(result["error_requests_per_endpoint"], {"/v1/widgets": 1})

    def test_rate_limit_burst_sample(self):
        result = report.build_report(SAMPLE_INPUT / "rate_limit_burst.jsonl")

        self.assertEqual(result["total_requests"], 101)
        self.assertEqual(len(result["rate_limit_violations"]), 1)
        violation = result["rate_limit_violations"][0]
        self.assertEqual(violation["client_id"], "acct_burst")
        self.assertEqual(violation["first_violation_at"], "2024-01-15T10:00:50Z")
        self.assertEqual(violation["violation_count"], 1)


class ParseLineTests(unittest.TestCase):
    def test_accepts_naive_timestamp_as_utc(self):
        line = json.dumps({
            "request_id": "n1",
            "timestamp": "2024-01-15T10:00:00",
            "client_id": "acct_1",
            "endpoint": "/v1/widgets",
            "status_code": 200,
        })
        record = report.parse_line(line)
        self.assertEqual(record["timestamp"], datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc))


class RateLimitTests(unittest.TestCase):
    def test_out_of_order_timestamps(self):
        requests_by_client = {
            "acct_1": [
                {
                    "timestamp": report.parse_timestamp("2024-01-15T10:00:04Z"),
                    "raw_timestamp": "2024-01-15T10:00:04Z",
                },
                {
                    "timestamp": report.parse_timestamp("2024-01-15T10:00:00Z"),
                    "raw_timestamp": "2024-01-15T10:00:00Z",
                },
                {
                    "timestamp": report.parse_timestamp("2024-01-15T10:00:02Z"),
                    "raw_timestamp": "2024-01-15T10:00:02Z",
                },
                {
                    "timestamp": report.parse_timestamp("2024-01-15T10:00:03Z"),
                    "raw_timestamp": "2024-01-15T10:00:03Z",
                },
            ]
        }

        with patch.object(report, "RATE_LIMIT_THRESHOLD", 2):
            violations = report.detect_rate_limit_violations(requests_by_client)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["client_id"], "acct_1")
        self.assertEqual(violations[0]["first_violation_at"], "2024-01-15T10:00:03Z")
        self.assertEqual(violations[0]["violation_count"], 2)


if __name__ == "__main__":
    unittest.main()
