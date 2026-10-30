# Security policy

The latest `develop` and `main` receive best-effort fixes.
There is no deployed production service or response-time guarantee yet.

## Reporting

Do not place exploit details, credentials or private datasets in issues or PRs.
If GitHub provides **Security > Report a vulnerability**, use the [private reporting channel](https://github.com/nguyenminh1301/fitcher/security/advisories/new).
Availability depends on repository settings and visibility.
If unavailable, ask the owner to establish a private channel before sharing details.
Include the affected commit, impact and a minimal reproduction using synthetic data.

## Credentials and data

Never commit `.env`, API keys, database credentials, raw datasets or customer data.
Rotate exposed credentials with the provider; deleting them from a later commit is insufficient.
The OpenAI key belongs to the LiteLLM gateway only; database and gateway credentials belong to backend and job processes, never browser bundles, `NEXT_PUBLIC_*` variables or LLM prompts.

## Automated checks

CI validates repository files, Git policy and Actions workflows, runs the API/CLI suite on Linux, and checks/builds the web application.
Dependabot is configured for GitHub Actions and targets `develop`, but automatic version-update PRs are paused because generated commit bodies violate the one-line commit policy.
Security-update behavior is controlled separately by GitHub repository settings; this bootstrap does not enable it.
The Security workflow audits locked npm and Python dependencies, scans Git history with Gitleaks, rebuilds and scans the `api` and `web` images, and scans the ClickHouse, OpenSearch, LiteLLM and Keycloak images by their pinned tags, all with checksum-verified Trivy. It runs for PRs, pushes to integration/production branches, manual dispatch and weekly on the default branch. Tool failures fail their jobs; a scanner outage is not a clean result. Images fail for High/Critical advisories with available fixes. Complete reports, including unfixed findings, are retained as workflow artifacts for 14 days.

Runtime images apply OS updates during uncached builds. API/web runtimes omit language package managers. Rebuild with `docker compose build --pull --no-cache` to refresh packages, then recreate services while preserving named volumes. Versions in application lockfiles do not cover all OS packages or bundled tooling.

Review advisory reachability before treating scanner counts as exploitable application defects. For example, Debian documents that [CVE-2023-45853 affects MiniZip code not built into Bookworm's zlib binary](https://security-tracker.debian.org/tracker/CVE-2023-45853). Do not introduce blanket suppressions. Any future exception must identify the advisory, affected artifact, evidence, owner and review/expiry date. A fixable High/Critical finding in a third-party image that only an upstream release can fix is recorded under Image exceptions below and suppressed only for that advisory and image; the gate itself is never weakened. Unfixed findings remain a release-review responsibility; the fix-available gate is not a claim that every image is vulnerability-free.

Run the relevant local checks documented in README.md. Required status checks and other GitHub security settings must be configured separately; workflow files alone do not enforce branch protection.
CodeRabbit review requires a separately installed and authorized App; configuration is not proof of an active review.

## Image exceptions

None recorded. Each entry lists the advisory, image and tag, evidence, owner and expiry date.
