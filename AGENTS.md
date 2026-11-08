# AGENTS.md

Guidance for AI agents contributing to this repository.

## Repository structure

```text
apm.yml                        # marketplace manifest (the published catalog)
plugins/<pkg>/                 # one package per directory
  apm.yml                      # package manifest
  plugin.json                  # Copilot Agent Plugin manifest
  .apm/skills/<name>/          # skills (SKILL.md + scripts/ + references/)
tests/                         # unit/integration tests (never packaged)
docs/                          # process docs and ADRs
scripts/check-public-safety.sh # blocking leak scan
scripts/runner_image_watch.py  # reports an outdated Ubuntu runner label
.github/workflows/             # validate.yml, publish.yml, release.yml,
                               # runner-image-watch.yml
.claude-plugin/marketplace.json # generated (committed)
.github/plugin/marketplace.json # generated (committed)
```

## Rules

- **Public safety first.** Never write internal project names, AWS account IDs,
  ARNs, access keys, private keys, or email addresses. Refer to a host or
  organization with a placeholder such as `<owner>`.
- **License.** New files are Apache-2.0. Do not add a copyright header naming an
  organization or person.
- **One source of truth.** Skills live in `plugins/<pkg>/.apm/skills/`; the
  marketplace JSONs are generated and must not be hand-edited.
- **Versioning.** Lockstep: bump the root `apm.yml` `version` and every package
  `version` together, per CONTRIBUTING.md.
- **Tests.** Python/Node scripts must have tests under `tests/`; they run in CI
  and are never packaged.

## Contributing

Follow [CONTRIBUTING.md](CONTRIBUTING.md): branch from `main`, add the skill under
`plugins/<pkg>/.apm/skills/<name>/`, add tests under `tests/`, run the checks,
regenerate the marketplace JSONs, and open a PR against `main`.

## Release process

Merging to `main` triggers `publish.yml`, which regenerates the marketplace
output, pushes the `marketplace` branch, and tags `vX.Y.Z` when the version
changed. See [docs/marketplace-release-process.md](docs/marketplace-release-process.md).

## Commands

```bash
scripts/check-public-safety.sh                              # blocking leak scan
apm marketplace check                                       # every package resolves
apm pack --check-versions --check-clean --dry-run           # release gates
apm pack                                                    # regenerate marketplace JSONs
pytest -q tests                                             # unit/integration tests
python3 scripts/runner_image_watch.py --dry-run              # would the runner image bump?
```

`runner_image_watch.py` runs weekly from `runner-image-watch.yml` and opens an
issue when a newer Ubuntu image is published or the pinned one disappears. It
does not edit the workflows, so a bump stays a reviewed change; dependabot does
not track `runs-on:` labels.

After changing `apm.yml` or any skill, run `apm pack` and commit the regenerated
marketplace JSONs.
