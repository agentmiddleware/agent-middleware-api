#!/usr/bin/env python3
"""
Autonomous PR Runner
=====================
Standalone script called by CI/CD (auto-pr.yml) to:
1. Fetch critical anomalies from the Telemetry API
2. Generate code fixes via the Auto-PR endpoint
3. Write fix details for the GitHub Actions PR creation step

Exit codes:
  0 — No anomalies found or fix generated successfully
  1 — API_KEY not configured, API connection failed, or anomaly fetch rejected
  2 — Fix generation failed
"""

import json
import os
import sys
import httpx


def main():
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    # No fallback credential: a missing secret must fail the job, never send a
    # guessable placeholder key and carry on.
    api_key = os.environ.get("API_KEY", "").strip()
    output_file = os.environ.get("FIX_OUTPUT", "/tmp/fix_details.json")
    github_output = os.environ.get("GITHUB_OUTPUT")

    if not api_key:
        print("[Auto-PR] API_KEY not configured")
        sys.exit(1)

    headers = {"X-API-Key": api_key}

    print(f"[Auto-PR] Connecting to {api_url}")

    # --- Step 1: Fetch critical anomalies ---
    # Any transport failure (refused, timeout, TLS, DNS) fails the job, not
    # just a refused connection.
    try:
        resp = httpx.get(
            f"{api_url}/v1/telemetry/anomalies",
            params={"severity": "critical"},
            headers=headers,
            timeout=30,
        )
    except httpx.HTTPError as e:
        print(f"[Auto-PR] Failed to connect: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"[Auto-PR] Anomaly fetch failed: {resp.status_code}")
        sys.exit(1)

    # The anomaly feed drives code changes, so validate its shape instead of
    # trusting fields straight into URL paths and output files.
    try:
        data = resp.json()
    except ValueError as e:
        print(f"[Auto-PR] Anomaly fetch returned invalid JSON: {e}")
        sys.exit(1)
    if not isinstance(data, dict) or not isinstance(data.get("anomalies"), list):
        print("[Auto-PR] Anomaly fetch returned an unexpected shape")
        sys.exit(1)
    anomalies = data["anomalies"]

    if not anomalies:
        print("[Auto-PR] No critical anomalies found. All clear.")
        sys.exit(0)

    print(f"[Auto-PR] Found {len(anomalies)} critical anomalies")

    # --- Step 2: Generate fix for the most recent anomaly ---
    anomaly = anomalies[0]
    if not isinstance(anomaly, dict):
        print("[Auto-PR] Anomaly entry has an unexpected shape")
        sys.exit(1)
    anomaly_id = anomaly.get("anomaly_id")
    # The id becomes a URL path segment; require a plain token so a
    # compromised feed cannot smuggle path traversal into the request.
    if (
        not isinstance(anomaly_id, str)
        or not anomaly_id
        or "/" in anomaly_id
        or any(ch.isspace() for ch in anomaly_id)
    ):
        print("[Auto-PR] Anomaly entry has an unusable anomaly_id")
        sys.exit(1)
    print(f"[Auto-PR] Generating fix for: {anomaly.get('summary', anomaly_id)}")

    try:
        fix_resp = httpx.post(
            f"{api_url}/v1/telemetry/anomalies/{anomaly_id}/auto-pr",
            json={"anomaly_id": anomaly_id, "dry_run": True},
            headers=headers,
            timeout=60,
        )
    except httpx.HTTPError as e:
        print(f"[Auto-PR] Fix generation failed: {e}")
        sys.exit(2)

    if fix_resp.status_code != 200:
        print(f"[Auto-PR] Fix generation returned {fix_resp.status_code}")
        sys.exit(2)

    try:
        fix_data = fix_resp.json()
    except ValueError as e:
        print(f"[Auto-PR] Fix generation returned invalid JSON: {e}")
        sys.exit(2)
    if not isinstance(fix_data, dict):
        print("[Auto-PR] Fix generation returned an unexpected shape")
        sys.exit(2)
    files_changed = fix_data.get("files_changed", [])
    if not isinstance(files_changed, list) or not all(
        isinstance(f, str) for f in files_changed
    ):
        print("[Auto-PR] Fix generation returned an unexpected files shape")
        sys.exit(2)
    print(f"[Auto-PR] Fix generated. Files changed: {files_changed}")

    # --- Step 3: Write output ---
    result = {
        "anomaly": anomaly,
        "fix": fix_data,
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[Auto-PR] Fix details written to {output_file}")

    # Signal to GitHub Actions
    if github_output:
        with open(github_output, "a") as f:
            f.write("has_fix=true\n")
        print("[Auto-PR] GitHub Actions output set: has_fix=true")

    # Print summary
    print("\n--- Fix Summary ---")
    print(f"Anomaly: {anomaly.get('summary', anomaly_id)}")
    print(f"Severity: {anomaly.get('severity', 'unknown')}")
    print(f"Files: {', '.join(files_changed)}")
    print(f"Tests passed: {fix_data.get('tests_passed', 'unknown')}")
    print(f"Status: {fix_data.get('status', 'unknown')}")


if __name__ == "__main__":
    main()
