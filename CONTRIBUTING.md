# Contributing

This repository is **public**. Anything merged here is world-readable: never
commit private or internal content. A CI guard (`scripts/check-public-safety.sh`)
blocks internal names, account IDs, ARNs, access keys, private keys, and email
addresses. Note the 12-digit account-ID rule is generic: a standalone 12-digit
number in prose is treated as an account ID.

## Repository layout

```text
apm.yml                        # marketplace manifest (source of truth)
plugins/<pkg>/                 # one package per directory
  apm.yml                      # package manifest
  plugin.json                  # Copilot plugin manifest
  README.md                    # consumer-facing package docs
  .apm/skills/<name>/          # skills: SKILL.md + scripts/, references/, assets/
tests/                         # unit/integration tests (never packaged)
docs/*.md                      # process docs
docs/adr/NNNN-*.md             # Architecture Decision Records
```

## What we accept

- Reusable **skills** — a `SKILL.md` plus bundled `scripts/`, `references/`,
  `assets/`, or `examples/`.
- **Copilot plugins** that group related skills.

## What we do not accept

- Anything referencing internal projects, accounts, credentials, ARNs, access
  keys, private keys, or email addresses (blocked by the public-safety guard).
- Content that circumvents security or Responsible AI policies.
- Duplicate primitives that add no value over a frontier model.

## Adding a skill

1. Fork, then branch from `main` (never `marketplace`).
2. Create `plugins/<pkg>/.apm/skills/<name>/SKILL.md` with frontmatter `name`
   equal to the directory name and a `description` that starts "Use when …".
3. Add bundled assets under `scripts/`, `references/`, or `assets/` and
   reference them from `SKILL.md`.
4. For a new package, register it in the root `apm.yml` `marketplace.packages`
   list; otherwise add the skill to an existing package.
5. Add tests for any Python/Node script (see Tests).
6. Run the checks, then open a PR against `main`.

## Adding a plugin

1. Create `plugins/<pkg>/` with `apm.yml`, `plugin.json`, `README.md`, and its
   skills under `.apm/skills/`.
2. Keep `plugin.json` `version` and `plugins/<pkg>/apm.yml` `version` equal.
3. Register the package in the root `apm.yml` `marketplace.packages` list.

## Tests

- Any Python or Node script must have tests; add them with the script itself.
- Tests live under top-level `tests/`, outside the packaged `.apm/` tree, so
  they run in CI and are excluded from releases by construction.
- Mirror the source path: `scripts/runner_image_watch.py` is covered by
  `tests/scripts/test_runner_image_watch.py`, and
  `plugins/sdlc/.apm/skills/adr/scripts/check_adr.py` by
  `tests/skills/adr/test_check_adr.py`.
- Skill scripts import `pyyaml`, which the command below installs with the
  versions pinned in `.github/workflows/validate.yml`.
- Python: `tests/**/test_*.py` and `tests/**/*_test.py`, run with `pytest`.
  Node: `tests/**/*.test.{js,mjs}`, run with `node --test tests/`.

```bash
pip install pytest pyyaml   # pyyaml: imported by the skill scripts the tests load
pytest -q tests
node --test tests/
```

## Checks

Run before opening a PR:

```bash
bash scripts/check-public-safety.sh
apm marketplace check
apm pack --check-versions --check-clean --dry-run
find plugins -path '*/.apm/skills/*/SKILL.md' -exec apm audit --file {} \;
```

After changing `apm.yml` or any skill, run `apm pack` and commit the regenerated
marketplace JSONs.

## Versioning

Semantic versioning, with the skill **description as the API**:

- **Patch** — a body edit that does not change the activation contract.
- **Minor** — a new asset, skill, or reference; existing consumers unaffected.
- **Major** — the `description` (activation contract) changes, or a slot/asset
  name that consumers depend on is renamed.

Versions are lockstep: the root `apm.yml` `version` is the release anchor, and
`apm pack --check-versions` enforces every package `version` matches it. Bump
them together before release.

## AI agents

Same workflow as above; machine-readable rules live in [AGENTS.md](AGENTS.md).

## License

Apache-2.0, matching [LICENSE](LICENSE). Do not add a copyright header naming an
organization or person.
