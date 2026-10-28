---
trigger: model_decision
description: Load when starting any task that involves writing intermediate files, plans, reports, or scripts. Defines how to use .workspace/ as the agent's working directory.
---

# Skill: Workspace Usage

## What it is

`.workspace/` is a per-developer directory at project root for agent-generated outputs — plans, reports, scripts, progress files, and scratch work. Only structure files are tracked; working content remains ignored and private to the developer. Each developer maintains their own copy.

## Folder guide

| Folder | Contents |
|--------|---------|
| `plans/` | Work not yet started — task breakdowns, implementation plans, branching strategies |
| `progress/` | Active session state — progress tracking files for ongoing or recent tasks |
| `reports/` | Completed outputs — scan results, PR descriptions, summaries, audit outputs |
| `scripts/` | One-off scripts for the current task; reusable project tools belong in tracked root `scripts/` |
| `tmp/` | Scratch space — disposable intermediate files. Do not rely on these persisting |

## First action when arriving with no context

1. Read `.workspace/README.md`.
2. Scan `progress/` for any `*_progress.md` files to find active or recently interrupted tasks.
3. Scan `plans/` for pending work that has not yet started.

## Naming conventions

Use descriptive names that identify the task and, optionally, a date:

- `{task-name}_progress.md` — progress tracking for an active task
- `{task-name}_plan.md` — implementation plan for upcoming work
- `{topic}_report.md` — completed scan, audit, or summary output

## Agent flexibility

Agents may create subfolders within any of the five top-level folders. The baseline structure is a minimum — extend it freely for the task at hand. For example, `reports/auth/` or `scripts/db/` are fine.

## Multi-session continuity

Other agents in future sessions, potentially with no prior context, can navigate this folder to understand what has been done. Write file names and content as if explaining to a colleague: clear, self-contained, no assumed context from the current session.

## Checklist

- [ ] Reading `.workspace/README.md` and `progress/` before starting if arriving without context
- [ ] Plans written to `plans/`, not to the project root or `tmp/`
- [ ] Active session state (progress files) written to `progress/`
- [ ] Completed outputs (scan results, PR text, summaries) written to `reports/`
- [ ] One-off scripts written to `.workspace/scripts/`; reusable tools written to tracked root `scripts/`
- [ ] Scratch work and throwaway files written to `tmp/`
- [ ] File names are descriptive and self-explanatory to a future agent with no context

## Durable project artifacts

Do not make committed documentation or project tooling depend on an ignored workspace file.
Source code, tests, migrations, reusable scripts and official documentation belong in tracked project directories.
On resume, verify interrupted operations against current files and Git state before repeating them; pending plans are not authorization to start unrelated work.
