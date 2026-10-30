# Domain Packs

Each company is described by a Domain Pack in `packs/<company>/`: eight YAML files (business profile, datasets, glossary, metrics, relationships, examples, policies and eval) validated by JSON Schema.
Git is the source of truth for packs; the engine under `apps/` contains no pack-specific names.

See [DECISIONS §5](../docs/DECISIONS.md#5-domain-pack). The schemas and the first hand-written pack arrive in [Phase 2](../docs/plans/phase-02-domain-pack-and-compiler.md).
