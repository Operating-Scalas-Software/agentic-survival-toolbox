# AGENTS.md

Guidance for AI agents contributing to this repository.

## Repository structure

```text
apm.yml                        # marketplace manifest (the published catalog)
plugins/sdlc/                  # the sdlc package + Copilot plugin
  apm.yml                      # package manifest
  plugin.json                  # Copilot Agent Plugin manifest
  .apm/skills/<name>/          # skills (SKILL.md + scripts/ + references/)
scripts/check-public-safety.sh # blocking leak scan
.github/workflows/             # validate.yml
.claude-plugin/marketplace.json # generated (committed)
.github/plugin/marketplace.json # generated (committed)
```

## Rules

- **Public safety first.** Never write internal project names, AWS account IDs,
  ARNs, access keys, private URLs, or email addresses. Refer to a host or
  organization with a placeholder such as `<owner>`.
- **License.** New files are Apache-2.0. Do not add a copyright header naming an
  organization or person.
- **One source of truth.** Skills live in `plugins/<pkg>/.apm/skills/`; the
  marketplace JSONs are generated and must not be hand-edited.
- **Versioning.** Bump the package `version` per CONTRIBUTING.md before release.

## Commands

```bash
scripts/check-public-safety.sh                              # blocking leak scan
apm marketplace check                                       # every package resolves
apm pack --check-versions --check-clean --dry-run           # release gates
apm pack                                                    # regenerate marketplace JSONs
```

After changing `apm.yml` or any skill, run `apm pack` and commit the regenerated
marketplace JSONs.
