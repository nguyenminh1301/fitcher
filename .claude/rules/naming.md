---
trigger: always_on

description: Always active. Requires durable, purpose-based names and self-contained explanations for tracked code, files, tests, documentation, branches and commits.
---

# Durable Names and Explanations

**Rule**: A developer must be able to understand every committed source comment,
test name, file name, document, and commit message from the repository itself.
This applies equally to text written by a person or generated with an AI tool,
in this repository.

- Name files, branches, tests, and commits for the behavior, component, or operational
  purpose they represent. A commit subject must say what changed; the PR description explains why
  when the reason is not clear from the diff. Commit messages remain exactly one line,
  with no body or trailers, as required by `git_workflow.md`.
- Do not use prompt numbers, task numbers, chat turns, agent names, or private
  work-session labels as permanent identifiers (for example, `task 2`, `L15 sweep`,
  or `R1 sync`). Replace them with the actual feature, fix, or procedure.
- Write comments and documentation as explanations for future maintainers. Remove
  assistant-directed prose, handoff language, unsupported completion claims, and
  references to conversations or plans that are not available in the repository.
- Do not make committed artifacts depend on `.workspace/` or another untracked,
  local-only path for their meaning or evidence. Put lasting decisions, commands,
  measurements, and links to supporting material in tracked documentation or cite
  a stable external source. Agent-only scratch instructions may still use
  `.workspace/` for temporary work.
- Keep established domain identifiers, issue numbers, migration versions, and
  release phases when they have a real external or tracked meaning. Explain that
  meaning where a reader would otherwise need private context.

Before committing, review the staged file names, diff, and commit message against
these rules. Resolve any opaque label or private-context reference in the artifact
itself; a separate chat explanation is insufficient.

Source: [GLOBAL_RULES.md, section 10](https://github.com/luvax-social/social-media-platforms/blob/main/.agents/rules/GLOBAL_RULES.md#10-durable-names-and-explanations).
The shared naming rule is applied to this standalone repository; rationale belongs in the PR description to preserve its one-line commit policy.
