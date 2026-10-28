"""Validate project commit messages, PR titles and source branch names."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / ".github/git-policy.json").read_text(encoding="utf-8"))


def check_message(message):
    errors = []
    if len(message.splitlines()) != 1:
        return ["must be exactly one line, without a body or trailers"]
    if len(message) > POLICY["max_subject_length"]:
        errors.append("must be at most 80 characters (target 72)")
    types = "|".join(map(re.escape, POLICY["types"]))
    scopes = "|".join(map(re.escape, POLICY["scopes"]))
    if not re.fullmatch(rf"({types})\(({scopes})\): [a-z][^\r\n]+", message):
        errors.append("must use type(scope): subject with an allowed type/scope and lowercase subject")
    if message != message.strip():
        errors.append("must not have leading or trailing whitespace")
    if re.search(r"co-authored-by|generated (?:with|by)|\b(?:codex|claude|chatgpt)\b", message, re.I):
        errors.append("must not contain author trailers or agent attribution")
    return errors


def check_branch(branch, base):
    if base == "main" and branch == "develop":
        return []
    # GitHub creates these names for automated dependency updates.
    if branch.startswith("dependabot/") and base == "develop":
        return []
    types = "|".join(map(re.escape, POLICY["branch_types"]))
    scopes = "|".join(map(re.escape, POLICY["scopes"]))
    if re.fullmatch(rf"({types})/({scopes})/[a-z0-9]+(?:-[a-z0-9]+)*", branch):
        return []
    return ["must use feat|fix|chore/<allowed-scope>/<lowercase-description>"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", dest="revision_range")
    parser.add_argument("--title")
    parser.add_argument("--branch")
    parser.add_argument("--base", choices=["develop", "main"], default="develop")
    args = parser.parse_args()
    if args.revision_range is None and args.title is None and args.branch is None:
        parser.error("provide --range, --title or --branch")
    failures = []
    if args.title is not None:
        failures.extend(f"PR title: {error}" for error in check_message(args.title))
    if args.branch is not None:
        failures.extend(f"Branch: {error}" for error in check_branch(args.branch, args.base))
    if args.revision_range is not None:
        result = subprocess.run(
            ["git", "log", "--no-merges", "--format=%H%x00%B%x00", args.revision_range, "--"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return 2
        fields = result.stdout.split("\0")
        checked = 0
        for index in range(0, len(fields) - 1, 2):
            sha = fields[index].strip()
            if not sha:
                continue
            message = fields[index + 1].rstrip("\n")
            checked += 1
            failures.extend(f"{sha[:8]}: {error}" for error in check_message(message))
        print(f"Checked {checked} non-merge commit(s).")
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("Git policy checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
