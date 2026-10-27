"""Check repository structure, text hygiene, JSON and local Markdown links."""

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "AGENTS.md",
    ".coderabbit.yaml", ".editorconfig", ".gitattributes", ".gitignore", ".env.example",
    ".agents/rules/git_workflow.md", ".github/CODEOWNERS", ".github/git-policy.json",
    ".github/pull_request_template.md", ".github/dependabot.yml",
    ".github/workflows/ci.yml", ".github/workflows/pr-lint.yml",
    ".github/workflows/pr-size.yml",
]


def main():
    errors = [f"Missing required file: {name}" for name in REQUIRED if not (ROOT / name).is_file()]
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    )
    names = sorted(set(name for name in result.stdout.decode("utf-8").split("\0") if name))
    for name in names:
        path = ROOT / name
        if not path.is_file():
            errors.append(f"Tracked file missing: {name}")
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".ico", ".pdf", ".woff", ".woff2"}:
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"Expected UTF-8: {name}")
            continue
        if b"\r" in raw or not raw.endswith(b"\n"):
            errors.append(f"Use LF line endings and a final newline: {name}")
        if path.suffix != ".md" and any(line.rstrip() != line for line in text.splitlines()):
            errors.append(f"Trailing whitespace: {name}")
        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                errors.append(f"Invalid JSON: {name}: {error}")
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=name)
            except SyntaxError as error:
                errors.append(f"Invalid Python: {name}: {error}")
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^\s)]+)\)", text):
                if re.match(r"(?:https?://|mailto:|#)", target):
                    continue
                local = target.split("#", 1)[0]
                if local and not (path.parent / local).exists():
                    errors.append(f"Broken local link in {name}: {target}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"Repository checks passed ({len(names)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
