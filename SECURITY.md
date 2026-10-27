# Security policy

The latest `develop` and `main` receive best-effort fixes.
There is no deployed production service or response-time guarantee yet.

## Reporting

Do not place exploit details, credentials or private datasets in issues or PRs.
If GitHub provides **Security > Report a vulnerability**, use the [private reporting channel](https://github.com/nguyenminh1301/finch/security/advisories/new).
Availability depends on repository settings and visibility.
If unavailable, ask the owner to establish a private channel before sharing details.
Include the affected commit, impact and a minimal reproduction using synthetic data.

## Credentials and data

Never commit `.env`, API keys, database credentials, raw datasets or customer data.
Rotate exposed credentials with the provider; deleting them from a later commit is insufficient.
OpenAI keys belong to backend and ingestion processes only, never browser bundles or `NEXT_PUBLIC_*` variables.

## Automated checks

CI currently validates repository files, Git policy and Actions workflows.
Dependabot monitors GitHub Actions weekly and targets `develop`.
Application dependency audits and runtime security checks will be added when application manifests and services exist.
CodeRabbit review requires a separately installed and authorized App; configuration is not proof of an active review.
