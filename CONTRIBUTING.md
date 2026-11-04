# Contributing

This repository is **public**. Anything merged here is world-readable, so the
first rule is: never commit private or internal content.

## What we accept

- Reusable **skills** — a `SKILL.md` plus bundled `scripts/`, `references/`,
  `assets/`, or `examples/`.
- **Copilot plugins** that group related skills.
- Self-contained, generic primitives that do not depend on a single internal
  project or infrastructure.

## What we do not accept

- Anything referencing internal projects, accounts, credentials, ARNs, private
  URLs, or email addresses. A CI guard (`scripts/check-public-safety.sh`) blocks
  these.
- Content that circumvents security or Responsible AI policies, or that weakens
  a platform's security.
- Duplicate primitives that add no value over what a frontier model already does.

## Quality guidelines

- **Specific** — lead the skill `description` with the trigger, not the skill's
  name.
- **Focused** — keep `SKILL.md` small; move long-tail detail into `references/`.
- **Tested** — run the checks below before opening a PR.

## Adding a skill

1. Create `plugins/<pkg>/.apm/skills/<name>/SKILL.md` (plus optional `scripts/`,
   `references/`, or `assets/`).
2. Keep the frontmatter `name` equal to the directory name; write the
   `description` as "Use when …".
3. Register the package in the root `apm.yml` `marketplace.packages` list.
4. Run `scripts/check-public-safety.sh`, `apm marketplace check`, and
   `apm pack --check-versions --check-clean --dry-run`.

## Versioning

Semantic versioning, with the skill **description as the API**:

- **Patch** — a body edit that does not change the activation contract.
- **Minor** — a new asset, skill, or reference; existing consumers unaffected.
- **Major** — the `description` (activation contract) changes, or a slot/asset
  name that consumers depend on is renamed.

## License

Contributions are licensed Apache-2.0, matching [LICENSE](LICENSE).
