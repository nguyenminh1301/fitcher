# Security policy

## Supported versions

The latest released minor version receives security fixes as a new patch release; older versions do not. The latest `develop` receives best-effort fixes. There is no hosted service or response-time guarantee.

The threat model, what each mode protects and the hardening checklist are in [docs/security.md](docs/security.md).

## Reporting

Do not place exploit details, credentials or private datasets in issues or PRs.
If GitHub provides **Security > Report a vulnerability**, use the [private reporting channel](https://github.com/nguyenminh1301/fitcher/security/advisories/new).
Availability depends on repository settings and visibility.
If unavailable, ask the owner to establish a private channel before sharing details.
Include the affected commit, impact and a minimal reproduction using synthetic data.

## Credentials and data

Never commit `.env`, API keys, database credentials, raw datasets or customer data.
Rotate exposed credentials with the provider; deleting them from a later commit is insufficient.
Model provider keys are entered in the application and stored encrypted in the app state; only the api's model gateway decrypts them, and no endpoint returns them. Database credentials belong to backend and job processes, never browser bundles, `NEXT_PUBLIC_*` variables or LLM prompts.

## Automated checks

CI validates repository files, Git policy and Actions workflows, runs the API/CLI suite on Linux, and checks/builds the web application.
Dependency updates are manual and reviewed. Dependabot is configured for GitHub Actions and targets `develop`, but automatic version-update PRs are paused because generated commit bodies violate the one-line commit policy.
Security-update behavior is controlled separately by GitHub repository settings; this bootstrap does not enable it.
The Security workflow audits locked npm and Python dependencies, scans Git history with Gitleaks, rebuilds and scans the `api` and `web` images and the release image of the root `Dockerfile`, and scans the ClickHouse image by its pinned tag, all with checksum-verified Trivy through `scripts/scan_image.sh`. The Release workflow runs the same gate on the release image before it publishes a version tag; its report is kept for 90 days. It runs for PRs, pushes to integration/production branches, manual dispatch and weekly on the default branch. Tool failures fail their jobs; a scanner outage is not a clean result. Images fail for High/Critical advisories with available fixes. Complete reports, including unfixed findings, are retained as workflow artifacts for 14 days.

Runtime images apply OS updates during uncached builds. API/web runtimes omit language package managers. Rebuild with `docker compose build --pull --no-cache` to refresh packages, then recreate services while preserving named volumes. Versions in application lockfiles do not cover all OS packages or bundled tooling.

Review advisory reachability before treating scanner counts as exploitable application defects. For example, Debian documents that [CVE-2023-45853 affects MiniZip code not built into Bookworm's zlib binary](https://security-tracker.debian.org/tracker/CVE-2023-45853). Do not introduce blanket suppressions. Any future exception must identify the advisory, affected artifact, evidence, owner and review/expiry date. A fixable High/Critical finding in a third-party image that only an upstream release can fix is recorded under Image exceptions below and suppressed only for that advisory and image; the gate itself is never weakened. Unfixed findings remain a release-review responsibility; the fix-available gate is not a claim that every image is vulnerability-free.

Run the relevant local checks documented in README.md. Required status checks and other GitHub security settings must be configured separately; workflow files alone do not enforce branch protection.
CodeRabbit review requires a separately installed and authorized App; configuration is not proof of an active review.

## Image exceptions

Each image's suppressed advisories are listed with their evidence in `.github/trivy/<service>.trivyignore.yaml`; Trivy applies a file only to its own image and stops suppressing an entry after its expiry date.
On or before expiry, rescan the newest upstream tag, update the pin if it fixes the findings, and remove or renew each entry with fresh evidence.

| Image | Advisories | Evidence | Owner | Expires |
| --- | --- | --- | --- | --- |
| `clickhouse/clickhouse-server:26.8.36.3` | CVE-2026-109518 in the base image's apt ([list](.github/trivy/clickhouse.trivyignore.yaml)) | Newest 26.8 release on 2026-11-05; apt ships in the upstream Ubuntu base and the server never runs it | @nguyenminh1301 | 2026-12-31 |

## Unfixed image advisories

High advisories in the Debian 13 packages of the release image that Debian has not fixed yet. The image gate blocks fixable findings only, so these do not fail it; they are reviewed by hand. The release image removes the packages it never uses (the package manager, the util-linux tools, `login`, `mount` and Perl), which took the count from 47 to 13 on 2026-11-20. Rebuild the image as soon as Debian publishes a fixed version, and review this list again by the review date.

| Package | Advisories | Why it is accepted until a fix | Owner | Review by |
| --- | --- | --- | --- | --- |
| `libsqlite3-0` 3.46.1 | CVE-2026-119373, CVE-2026-119374 (FTS5), CVE-2026-119379 (session changesets) | The api's app state is SQLite, so the library stays; the app never creates an FTS5 table or applies a changeset, and only the api writes `app.db` | @nguyenminh1301 | 2026-12-31 |
| `libncursesw6`, `libtinfo6`, `ncurses-base`, `ncurses-bin` 6.5 | CVE-2025-69720 | Needed by the shell and Python; no service draws a terminal interface or reads terminal descriptions from untrusted input | @nguyenminh1301 | 2026-12-31 |
| `libuuid1` 2.41.5 | CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | The advisories are in util-linux's mount and nsenter tools, removed from the image; only the shared library Python's `uuid` module loads remains | @nguyenminh1301 | 2026-12-31 |
| `libsystemd0` 257.13 | CVE-2026-16742 | The advisory is in systemd-homed, which the image does not contain; the library stays for coreutils | @nguyenminh1301 | 2026-12-31 |
| `libacl1` 2.3.2 | CVE-2026-54369 | Needed by coreutils; the services run as unprivileged users and change no access control lists | @nguyenminh1301 | 2026-12-31 |
