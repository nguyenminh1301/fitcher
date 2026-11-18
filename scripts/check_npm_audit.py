"""Audit the web app's locked Node dependencies, failing on every advisory but the listed exceptions.

``npm audit`` cannot ignore one advisory, so an advisory that has no patched release yet would block every
change until upstream ships a fix. This check runs the same ``npm audit --package-lock-only`` and fails on
every advisory except those listed in ``.github/npm-audit-exceptions.json``. Each exception names one GHSA
id and the package it affects, says why it is accepted and expires on a date: an expired exception fails the
check, and so does one that the audit no longer reports, so the list cannot outlive its reason.

Usage: python scripts/check_npm_audit.py [--audit-json FILE]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCEPTIONS = ROOT / ".github" / "npm-audit-exceptions.json"
WEB = ROOT / "apps" / "web"
GHSA = re.compile(r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}")


def run_audit() -> dict:
    # npm exits non-zero whenever it finds an advisory, so the report is read whatever the exit code.
    result = subprocess.run(
        ["npm", "audit", "--package-lock-only", "--json"], cwd=WEB, capture_output=True, text=True, check=False,
        shell=sys.platform == "win32",
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"npm audit did not return a JSON report:\n{result.stderr or result.stdout}")


def advisories(report: dict) -> dict[str, dict]:
    """Every advisory the report names, by GHSA id; a package that is only vulnerable through another adds none."""
    found: dict[str, dict] = {}
    for entry in report.get("vulnerabilities", {}).values():
        for via in entry.get("via", []):
            if isinstance(via, dict):
                # An advisory without a GHSA id keeps its url or source, so it can never match an exception.
                match = GHSA.search(via.get("url", ""))
                found[match.group(0) if match else str(via.get("url") or via.get("source"))] = via
    return found


def load_exceptions(today: dt.date) -> tuple[dict[str, dict], list[str]]:
    problems: list[str] = []
    entries = json.loads(EXCEPTIONS.read_text(encoding="utf-8")) if EXCEPTIONS.exists() else []
    accepted: dict[str, dict] = {}
    for entry in entries:
        ident, package, reason, expires = (entry.get(key) for key in ("id", "package", "reason", "expires"))
        if not (isinstance(ident, str) and GHSA.fullmatch(ident) and package and reason and expires):
            problems.append(f"exception {entry!r} needs a GHSA id, a package, a reason and an expiry date")
            continue
        if dt.date.fromisoformat(expires) < today:
            problems.append(f"the exception for {ident} ({package}) expired on {expires}; review it")
            continue
        accepted[ident] = entry
    return accepted, problems


def check(report: dict, today: dt.date) -> list[str]:
    accepted, problems = load_exceptions(today)
    found = advisories(report)
    for ident, via in sorted(found.items()):
        exception = accepted.get(ident)
        if exception is None:
            problems.append(f"{via.get('severity', '?')} {ident} in {via.get('name', '?')}: {via.get('title', '')}")
        elif exception["package"] != via.get("name"):
            problems.append(f"the exception for {ident} names {exception['package']}, but the audit reports {via.get('name')}")
    for ident, exception in sorted(accepted.items()):
        if ident not in found:
            problems.append(f"the exception for {ident} ({exception['package']}) is no longer reported; remove it")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit-json", type=Path, help="read this npm audit JSON report instead of running npm audit")
    args = parser.parse_args()
    report = json.loads(args.audit_json.read_text(encoding="utf-8")) if args.audit_json else run_audit()
    problems = check(report, dt.date.today())
    accepted = [ident for ident in advisories(report) if not any(ident in problem for problem in problems)]
    for ident in sorted(accepted):
        print(f"accepted by exception: {ident}")
    if problems:
        print("npm audit found problems:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    print("npm audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
