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
  .apm/agents/<name>.agent.md  # agents: one persona per file
  .apm/hooks/                  # hooks: JSON plus the scripts they run
tests/                         # unit/integration tests (never packaged)
docs/*.md                      # process docs
docs/adr/NNNN-*.md             # Architecture Decision Records
```

## What we accept

- Reusable **skills** — a `SKILL.md` plus bundled `scripts/`, `references/`,
  `assets/`, or `examples/`.
- **Agents** — one `.apm/agents/<name>.agent.md` persona per file, with a
  trigger-oriented description and explicit boundaries.
- **Hooks** — one `.apm/hooks/<name>.json` per lifecycle policy, plus the
  scripts it runs.
- **Copilot plugins** that group related primitives.

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
   primitives under `.apm/` (`skills/`, `agents/`, `hooks/`).
2. Keep `plugin.json` `version` and `plugins/<pkg>/apm.yml` `version` equal.
3. Register the package in the root `apm.yml` `marketplace.packages` list.

## Adding an agent

1. Add `plugins/<pkg>/.apm/agents/<name>.agent.md` with a `description` that
   starts "Use when …" so the agent picker and subagent delegation can find it.
2. Keep the body focused on one role: what it does, what it must not do, and the
   shape of its output.
3. Optional frontmatter (tools, model, argument hints) does not translate to
   every harness; expect install warnings and keep essential behavior in the body.

## Adding a hook

1. Add `plugins/<pkg>/.apm/hooks/<name>.json`. Event names are renamed per
   harness (for example `PreToolUse` becomes `preToolUse` for Copilot).
2. Put the scripts the hook runs beside it and reference them with paths
   relative to the hook file, as APM documents.
3. Hooks gate tools in every consuming repository, so keep them small and
   auditable, and make failure behavior deliberate: a `preToolUse` command that
   exits non-zero fails closed and denies every tool call.

## Tests

- Any Python or Node script must have tests; add them with the script itself.
- Tests live under top-level `tests/`, outside the packaged `.apm/` tree, so
  they run in CI and are excluded from releases by construction.
- Mirror the source path: `scripts/runner_image_watch.py` is covered by
  `tests/scripts/test_runner_image_watch.py`, `plugins/sdlc/.apm/skills/adr/scripts/check_adr.py`
  by `tests/skills/adr/test_check_adr.py`, and
  `plugins/aws/.apm/hooks/scripts/deny_aws_mutations.py` by
  `tests/hooks/aws/test_deny_aws_mutations.py`.
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
python3 scripts/release_tags.py --plan
find plugins -path '*/.apm/skills/*/SKILL.md' -exec apm audit --file {} \;
```

After changing `apm.yml` or any skill, run `apm pack` and commit the regenerated
marketplace JSONs.

## Versioning

Semantic versioning, with a primitive's `description` (its activation contract)
as the API:

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
