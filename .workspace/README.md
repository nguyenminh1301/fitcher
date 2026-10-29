# .workspace

Per-developer working directory for agent tasks. Working content is not tracked by Git; only this guide, the ignore policy and the five baseline directory placeholders are tracked.
Each developer maintains their own copy.

## Folder guide

| Folder | Purpose |
|--------|---------|
| `plans/` | Upcoming work not yet started — task breakdowns, implementation plans, branching strategies |
| `progress/` | Active session state — progress tracking files for ongoing or recent tasks |
| `reports/` | Completed outputs — scan results, PR descriptions, summaries, audit outputs |
| `scripts/` | One-off scripts for the current task; reusable project tooling belongs in tracked root `scripts/` |
| `tmp/` | Scratch space — disposable intermediate files; do not rely on these persisting |

## First-time guidance for an agent arriving with no context

1. Read this file.
2. Scan `progress/` for any `*_progress.md` files — these describe active or recently interrupted tasks, including which steps are complete and which remain.
3. Scan `plans/` for pending work that has not yet started.

## Notes

- Agents may create subfolders freely within any of the five top-level folders. The structure above is the baseline minimum.
- Write file names and content as if explaining to a colleague who has no prior session context — other agents in future sessions will navigate this folder to understand what has been done.
- Prefer descriptive names: `{task-name}_progress.md`, `{task-name}_plan.md`, `{topic}_report.md`.

## Tracked structure and private content

The root `.gitignore` must not exclude `.workspace/` wholesale.
The nested `.workspace/.gitignore` tracks only this README, its own policy and `plans/.gitkeep`, `progress/.gitkeep`, `reports/.gitkeep`, `scripts/.gitkeep` and `tmp/.gitkeep`.
Nested working files, including additional README files, remain ignored.
A pending plan or another task's progress file is context, not authorization to resume that work.
