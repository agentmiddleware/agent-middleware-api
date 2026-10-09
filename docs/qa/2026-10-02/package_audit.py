"""Audit installed Python versions using public PyPI package metadata only."""

from concurrent.futures import ThreadPoolExecutor
import argparse
import importlib.metadata
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def inspect_package(package):
    name, version = package
    url = "https://pypi.org/pypi/{}/{}/json".format(
        urllib.parse.quote(name, safe=""), urllib.parse.quote(version, safe="")
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
        return {
            "name": name,
            "version": version,
            "vulnerabilities": [
                {
                    "id": item.get("id"),
                    "aliases": item.get("aliases", []),
                    "fixed_in": item.get("fixed_in", []),
                    "withdrawn": item.get("withdrawn"),
                }
                for item in data.get("vulnerabilities", [])
                if not item.get("withdrawn")
            ],
        }
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return {"name": name, "version": version, "error": type(error).__name__}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--site-packages",
        help="Inspect an isolated environment without activating its network guard",
    )
    args = parser.parse_args()
    distributions = importlib.metadata.distributions(
        **({"path": [args.site_packages]} if args.site_packages else {})
    )
    packages = sorted({(item.metadata["Name"], item.version) for item in distributions})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(inspect_package, packages))
    report = {
        "source": "Public PyPI per-version JSON package metadata; no private registry or advisory API",
        "scope": "Resolved isolated Python QA environment, including development tools",
        "packages": results,
        "package_count": len(results),
        "vulnerable_package_count": sum(
            bool(item.get("vulnerabilities")) for item in results
        ),
        "unverified_package_count": sum("error" in item for item in results),
    }
    path = Path(__file__).parent / "artifacts" / "python-package-audit.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "packages"}, indent=2
        )
    )
    for item in results:
        if item.get("vulnerabilities") or item.get("error"):
            print(json.dumps(item))
