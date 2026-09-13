# API Traffic Report

Reads a JSONL API request log and prints a traffic report as JSON to stdout.

Python 3.11+, stdlib only. Tested on 3.12.3.

## Run it

```bash
python3 report.py sample_input/requests.jsonl
python3 -m unittest discover -s tests
```

Rate-limit example (101 requests from one client inside 60 seconds):

```bash
python3 report.py sample_input/rate_limit_burst.jsonl
```

## Approach

I treated this as a small batch observability tool, not a parsing exercise.
The spec says logs come from third-party upstreams, so I didn't assume lines
arrive in timestamp order. Malformed lines are counted and skipped; the run
continues. stdout is JSON only — errors go to stderr so the output can be
piped straight into other tooling.

## What it does

1. Read the file line by line.
2. Parse and validate each non-blank line (see below for what's rejected).
3. Tally counts by endpoint and status code, plus non-2xx counts per endpoint.
4. Group valid requests by client and run a sliding-window rate-limit check.
5. Print one JSON report.

Malformed lines don't appear in the tallies — only in `malformed_requests`.
In production I'd log the failure reason to stderr separately; here the spec
only asks for a count.

## Rate-limit rule

**> 100 requests from one client in any trailing 60-second window.**

Sliding window, not fixed calendar minutes — a fixed window lets a client
send ~200 requests in two seconds by straddling a boundary (100 at :59, 100
at :01). The threshold is a constant at the top of `report.py` since the
spec doesn't define an SLA.

Each client's requests are sorted by timestamp before the window runs, because
file order may not be chronological. `violation_count` is the number of
individual requests that landed in an over-limit window, not the number of
distinct burst events.

## Output

| Field | Meaning |
|---|---|
| `total_requests` | Non-blank lines read (valid + malformed) |
| `valid_requests` | Lines that parsed successfully |
| `malformed_requests` | Lines discarded |
| `per_endpoint` | Valid request count per endpoint |
| `per_status_code` | Valid request count per status code (string keys) |
| `error_requests_per_endpoint` | Non-2xx valid requests per endpoint (omitted if zero) |
| `rate_limit_violations` | `[{client_id, first_violation_at, violation_count}]` |

`first_violation_at` uses the timestamp string from the input, not a
reformatted value.

**Malformed** means: invalid JSON, not a JSON object, missing a required
field, wrong field types, or an unparseable timestamp. Timestamps with `Z`
or `+HH:MM` are accepted; bare timestamps without an offset are treated as
UTC. JSON booleans are rejected as `status_code` values (Python gotcha:
`bool` is a subclass of `int`).

Blank lines are ignored entirely — not counted as malformed.

## Assumptions

- Duplicate `request_id` values are counted as separate requests.
- Non-2xx means anything outside 200–299 (includes 3xx redirects).
- No per-client request totals in the report — rate-limit violations cover
  the clients worth flagging; a full client map gets noisy fast.

## With more time

- CLI flags for rate-limit threshold and window size.
- Malformed-line diagnostics to stderr (line number + reason).
- Optional `--verbose` cross-tab of endpoint × status code.
- Bounded out-of-order buffer instead of holding all requests per client in
  memory, if file size became a concern.

## AI tool use

I used Claude while working on this. I started by talking through the
trade-offs myself — sliding vs fixed windows, what to count as malformed,
which fields belong in the report — and used it to draft code, tests, and
this README.

I reviewed and edited all of it: ran the sample inputs, added the test suite
and burst sample file, fixed doc/spec mismatches (sample path, timestamp
rules), and kept the bits I cared about in the final version (out-of-order
sorting, the bool/status_code guard, stdout/stderr split). The design
choices are mine; AI was a drafting and sanity-check tool, not a substitute
for reading the output.
