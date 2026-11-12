---
trigger: always_on

description: Always active. Establishes .workspace/ as the agent working directory, with the first-action checklist and tracked-tooling boundary.
---

# Workspace Rule - fitcher

## What is `.workspace/`

`.workspace/` exists at the repository root.
It is the agent's working directory for every task: plans, reports, progress files, one-off scripts and scratch work all go here.
Working content is not tracked by Git; each developer has their own copy.
Only the README, ignore policy and baseline directory placeholders are tracked.

## First action - every session, every task

1. Read `.workspace/README.md`.
2. Check `.workspace/progress/` for any `*_progress.md` files.
   If one exists for the current task, read it to determine what is complete and what is pending before doing anything else.
3. Check `.workspace/plans/` for pending work that has not yet started.
   Pending plans and other tasks' progress files are context, not permission to resume them.

## All working output goes to `.workspace/`

Do not write plans, reports, scripts or intermediate files to the project root or to any project-owned directory unless the file genuinely belongs to the project: source code, tests, migrations or official documentation.

A script that a future session must be able to run does not belong in `.workspace/`: it is unavailable in a fresh clone and on another developer's machine.
Such a script goes in the tracked `scripts/` directory at the repository root.
`.workspace/scripts/` holds one-off scripts for the current task only.

## Default subdirectories

| Folder | Contents |
|--------|---------|
| `plans/` | Upcoming work not yet started |
| `progress/` | Active session state and resumable progress files |
| `reports/` | Completed outputs: scans, summaries and PR text |
| `scripts/` | One-off scripts for the current task |
| `tmp/` | Scratch work; do not rely on these files persisting |

Agents may create additional subfolders within any of the above as needed.

## File naming

Name a file as if explaining it to a colleague with no prior session context: `{task-name}_progress.md`, `{task-name}_plan.md`, `{topic}_report.md`.
Other agents in future sessions navigate this folder to work out what has been done.

## Multi-session continuity

Write down completed work, pending steps, verification results and the current branch in the current task's progress file before handing work over.
On resume, verify interrupted operations against actual files and Git state before repeating them.
Never treat another task's progress file as the current task's state.

## Checklist

- [ ] `.workspace/README.md`, current progress and pending plans read before acting
- [ ] Plans, progress, reports and scratch files kept in their corresponding folders
- [ ] One-off scripts kept in `.workspace/scripts/`; reusable tooling kept in tracked root `scripts/`
- [ ] Working content remains ignored; a clean clone contains the five baseline folders
- [ ] File names and handover notes are understandable without the current conversation

Load `skill-workspace` from the active agent directory for the folder guide and naming conventions.
