# Security

This document is the threat model of a fitcher instance: what each mode protects, the threats reviewed and what stops each one, the hardening checklist for an operator, and the review's findings with their resolution. [SECURITY.md](../SECURITY.md) says how to report a vulnerability.

## What each mode protects

| | Individual mode | Team mode |
| --- | --- | --- |
| Who is signed in | Nobody signs in: every request acts as the owner with every role | Local accounts or one OpenID Connect provider; a session cookie (`HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS) |
| Who may reach the port | The local machine only: the api answers loopback host names and `FITCHER_ALLOWED_HOSTS`, and a change needs the same `Origin` | Anyone the network lets through; every request needs a session |
| Conversation delete | Removes the conversation, its messages and its feedback for good | Hides it from its owner; an admin can still read it |
| Data a user reaches | Everything | What the user's pack role grants, enforced by ClickHouse row policies and grants |

## Threats

| Threat | What stops it | What remains |
| --- | --- | --- |
| Someone else reaches an individual-mode instance | The image publishes the port on `127.0.0.1` in every documented command; the api refuses other host names (DNS rebinding) and cross-site changes without the same `Origin` | Anyone with a shell on the same machine is the owner. Exposing the instance needs team mode. |
| A malicious web page the user visits | `SameSite=Strict` session cookie; `Origin` check on changes; a Content-Security-Policy with per-request nonces and `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` | Styles allow `'unsafe-inline'` (the chart library sets style attributes); a style cannot run code. |
| A malicious document or column value (prompt injection) | Screening of questions and document text (DECISIONS §9); the model writes one read-only query that the guard parses and limits; the query runs as the user's role user, which reads only granted views | Injected text can still change the wording of an answer or summary; it cannot widen what the role reads. |
| A hostile source database | Connections run as `source_loader` through encrypted named collections; copies land in `raw` and are read through generated views; errors are reduced to fixed reasons, so a server's message never reaches a page, a log line or a row | A source can send a very large table; the per-query memory and time limits of the copy stop it, and the admin chooses the tables. |
| A stolen data volume | Provider keys and source passwords are encrypted with the instance key | With the default generated `secret.key` the key is on the same volume. Supply `FITCHER_SECRET_KEY` from outside the volume to keep stored secrets unreadable when the volume alone is taken. Conversations, data copies and ClickHouse passwords are readable from the volume. |
| A compromised dependency | Base images pinned by digest; binaries added with checksums; Python and Node installed from lock files with hashes (`uv sync --frozen`, `npm ci`); every GitHub Action pinned by commit; the release image carries an SBOM and a provenance attestation; dependency updates are manual and reviewed; the Security workflow scans images and audits locked dependencies | A malicious version that passes review and the scanners. |

Secrets in logs: tests fail when a provider key, a source password, a session id or the instance secret key appears in an API response, a log line, an admin action or an `llm_calls` row, including when a provider or source error quotes it.

## Hardening checklist

- Keep the published port on `127.0.0.1` in individual mode; switch to team mode before anyone else reaches the instance.
- In team mode serve it over HTTPS behind a reverse proxy and list its public names in `FITCHER_ALLOWED_HOSTS`.
- Supply `FITCHER_SECRET_KEY` from a secret store instead of the generated `secret.key`.
- Back up with `fitcher backup` (see [operations.md](operations.md)); keep archives made with `--include-secret-key` as safe as the volume.
- Give each source connection a read-only database account.
- Upgrade one minor version at a time after a backup.

## Review findings

The review covered the surfaces added since Phase 12: setup, model providers, data sources, sign-in, the instant pack, search in ClickHouse, and this phase's retention, limits, backup and restore. Each finding is fixed or recorded with its reason.

| Finding | Resolution |
| --- | --- |
| Conversations expired with the 90-day log TTL, so history disappeared | Fixed: the conversation tables have no expiry; individual mode deletes for good |
| The questions answered at once were bounded only by a thread pool sized from the CPU count | Fixed: `limits.concurrent_questions`, an ordered queue, and a dedicated thread pool |
| A sync, a compile and an eval could run at the same time and compete for memory | Fixed: they and `fitcher backup` wait for each other |
| No Content-Security-Policy or framing protection on pages | Fixed: nonce policy and headers above |
| Development Dockerfiles and the Compose ClickHouse image were pinned by tag only | Fixed: pinned by digest. The source fixtures of the `sources` Compose profile (PostgreSQL, MySQL, SQL Server, MongoDB, SeaweedFS) stay pinned by tag: they run only on a developer's machine with synthetic data |
| Team mode answers any `Host` header | Recorded: every team-mode request needs a session cookie that is `SameSite=Strict` and bound to the instance's own origin, so a rebound name gets no data; a reverse proxy sets the public name |
| `style-src` keeps `'unsafe-inline'` | Recorded: the chart library and React set style attributes; scripts, which can run code, need the nonce |
| The generated `secret.key` sits on the volume it protects | Recorded: documented above; `FITCHER_SECRET_KEY` moves it off the volume |
| A backup without the secret key still holds conversations, data and ClickHouse passwords | Recorded: an archive is as sensitive as the volume; it is written with mode 0600 and documented so |
| A restore without the secret key cannot read the stored secrets | Recorded: the restore removes them and says that provider keys and source passwords are entered again |
| A ClickHouse backup of the databases alone left out the pack role users, so a restored instance could not run a question | Fixed: the backup also holds `system.users`, `system.roles`, `system.settings_profiles`, `system.row_policies` and `system.quotas` |
| The load was measured with a fake graph only, not against a development dataset in ClickHouse | Recorded in [operations.md](operations.md#load-measurement) with the limits that stand in until it is measured |
