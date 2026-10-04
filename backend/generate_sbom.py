"""Write a small SPDX-like JSON inventory from installed Python distributions."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from importlib import metadata
from pathlib import Path


def build_sbom() -> dict:
    packages = []
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        packages.append(
            {
                "name": name,
                "version": distribution.version,
                "license": distribution.metadata.get("License") or None,
            }
        )
    packages.sort(key=lambda item: (item["name"].lower(), item["version"]))
    return {
        "bomFormat": "quick-sciplot-python-inventory",
        "specVersion": "1",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "components": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a JSON inventory of installed Python packages")
    parser.add_argument("--output", type=Path, default=Path("dist") / "quick-sciplot-backend.sbom.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_sbom(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
