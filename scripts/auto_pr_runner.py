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
  1 — API connection failed
  2 — Fix generation failed
"""

import json
import os
import sys
import httpx


def main():
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    api_key = os.environ.get("API_KEY", "dev-key")
    output_file = os.environ.get("FIX_OUTPUT", "/tmp/fix_details.json")
    github_output = os.environ.get("GITHUB_OUTPUT")

    headers = {"X-API-Key": api_key}

    print(f"[Auto-PR] Connecting to {api_url}")

    # --- Step 1: Fetch critical anomalies ---
    try:
        resp = httpx.get(
            f"{api_url}/v1/telemetry/anomalies",
            params={"severity": "critical"},
            headers=headers,
            timeout=30,
        )
    except httpx.ConnectError as e:
        print(f"[Auto-PR] Failed to connect: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"[Auto-PR] Anomaly fetch failed: {resp.status_code}")
        sys.exit(1)

    data = resp.json()
    anomalies = data.get("anomalies", [])

    if not anomalies:
        print("[Auto-PR] No critical anomalies found. All clear.")
        sys.exit(0)

    print(f"[Auto-PR] Found {len(anomalies)} critical anomalies")

    # --- Step 2: Generate fix for the most recent anomaly ---
    anomaly = anomalies[0]
    anomaly_id = anomaly["anomaly_id"]
    print(f"[Auto-PR] Generating fix for: {anomaly['summary']}")

    try:
        fix_resp = httpx.post(
            f"{api_url}/v1/telemetry/anomalies/{anomaly_id}/auto-pr",
            json={"anomaly_id": anomaly_id, "dry_run": True},
            headers=headers,
            timeout=60,
        )
    except httpx.ConnectError as e:
        print(f"[Auto-PR] Fix generation failed: {e}")
        sys.exit(2)

    if fix_resp.status_code != 200:
        print(f"[Auto-PR] Fix generation returned {fix_resp.status_code}")
        sys.exit(2)

    fix_data = fix_resp.json()
    print(f"[Auto-PR] Fix generated. Files changed: {fix_data.get('files_changed', [])}")

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
    print(f"Anomaly: {anomaly['summary']}")
    print(f"Severity: {anomaly['severity']}")
    print(f"Files: {', '.join(fix_data.get('files_changed', []))}")
    print(f"Tests passed: {fix_data.get('tests_passed', 'unknown')}")
    print(f"Status: {fix_data.get('status', 'unknown')}")


if __name__ == "__main__":
    main()
