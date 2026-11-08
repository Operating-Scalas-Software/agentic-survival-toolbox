---
status: accepted
date: 2026-11-08
decision-makers: repository maintainers
consulted: apm-cli 0.35.0 behaviour, tag-resolution matrix run against a local HTTPS remote, issue #1, pull request #12
informed: marketplace consumers
---

# Publish a `{package}--v{version}` tag alongside every `v{version}` release tag

## Context and Problem Statement

Consumers declare the package as a marketplace dependency with a version range:

```yaml
dependencies:
  apm:
    - name: sdlc
      marketplace: agentic-survival-toolbox
      version: "^0.1.0"
```

`apm install` resolves that range against **git tags in this repository**, not
against the `marketplace` branch. The generated marketplace entry for a local
package source (`source: ./plugins/sdlc`) carries no tag pattern, because
`apm pack` in apm-cli 0.35.0 emits only `name`/`description`/`version`/`source`
for that form. The resolver therefore falls back to APM's legacy per-package
convention, `{name}--v{version}`, while this repository published only
`v{version}`. The install failed with:

```text
No tag matching version '^0.1.0' found for package 'sdlc'
(pattern='{name}--v{version}')
```

`apm marketplace check` reported the same state as healthy, so CI could not
catch it: reachability and ref checks pass, only tag resolution fails. The
question is how to publish so that the documented consumer manifest resolves.

## Decision Drivers

- The documented consumer manifest must work as written; a workaround in every
  consumer repository is not an acceptable resolution.
- `apm pack` cannot emit a tag pattern for a local package source in the
  current CLI (`0.35.0`, also the latest release), so the fix has to come from
  the tags we publish.
- One release must stay one reviewed, atomic act: no second workflow, no
  long-lived token, no manual step per release.
- A published tag must never point at a tree whose package manifest declares a
  different version.

## Considered Options

- Publish both tag families from the release run (chosen).
- Emit a tag pattern into `marketplace.json` from `apm.yml`.
- Change the package source to the remote form.
- Require consumers to pin a raw ref instead of a version range.

## Decision Outcome

Chosen option: "Publish both tag families from the release run", because it is
the only option that works with the released CLI and keeps the consumer
manifest unchanged.

The decision has these parts:

1. **Two tags per release, one commit** — `publish.yml` creates `v{version}`
   and one `{package}--v{version}` tag per entry in `marketplace.packages`,
   all pointing at the merged commit.
2. **Derivation is code, not inline shell** — `scripts/release_tags.py` owns
   the tag set (`--plan`), the published-set assertion (`--check`), and the
   one-off backfill for older releases (`--backfill`).
3. **The release anchor is unchanged** — `v{version}` still drives
   `tagPattern: "v{version}"`, the GitHub Release, and the version bump flow;
   alias tags are additive and carry no release object.
4. **The consumer path is gated** — `publish.yml` runs a scratch-repo
   `apm marketplace add` + `apm install` after tagging, so the install path
   this record exists for is exercised on every merge.

### Consequences

- Good, because the consumer manifest specified by issue #1 resolves without
  change, and a version range picks the highest satisfying release.
- Good, because the tag set is derived and verified in one place, so a partial
  push fails the run instead of publishing an unresolvable release.
- Good, because alias tags are additive: rollback is deleting them or
  reverting the workflow commit, with no effect on existing consumers.
- Bad, because two tag families must stay in step; `--check` covers the commit
  mismatch, but the convention itself is external and could change upstream.
- Bad, because the tag namespace is now shared with package names: a package
  name that cannot form a git tag fails the release gates, so supporting one
  would mean extending `release_tags.py` before the package can ship.
- Bad, because old releases only gain alias tags through a manual `--backfill`
  run followed by a hand-pushed tag; until it happens, an exact pin to `0.1.0`
  or `0.1.1` cannot resolve.

### Confirmation

- `scripts/release_tags.py --check` runs in `publish.yml` and fails when an
  alias tag is missing or points at a different commit than the release tag.
- `scripts/release_tags.py --plan` runs in `validate.yml`, so a package name
  that cannot form a tag, or a lockstep version mismatch, fails before merge.
- The consumer smoke test in `publish.yml` fails if the three skills do not land
  in `.agents/skills/`, which is the exact symptom of the missing alias tag.
- `tests/scripts/test_release_tags.py` covers derivation, lockstep mismatch,
  tag-safety, divergence, and backfill against a temporary git repository.
- A diverged alias tag fails `--check` with the two commits it compared; the
  repair is to delete the tag and re-push it at the release commit
  (`git push --delete origin <tag>`, then re-run the release), because the
  workflow only creates tags that do not exist.

## Pros and Cons of the Options

### Publish both tag families from the release run (chosen)

- Good, because it needs no consumer change and no CLI upgrade.
- Good, because it reuses the existing single-owner release run.
- Bad, because the repository publishes two tags per release and must keep them
  consistent.

### Emit a tag pattern into `marketplace.json` from `apm.yml`

- Good, because one tag family would suffice.
- Bad, because apm-cli 0.35.0 does not emit `tagPattern` or `tag_pattern` for a
  local package source; a probe with both keys set produced identical output.
  This is not something this repository can fix on its own.

### Change the package source to the remote form

- Good, because `apm pack` then emits `source: {repo, path, ref, sha}` instead
  of a bare local path.
- Bad, because it was not verified that a version range resolves from that
  object, and it makes `apm pack` depend on network access during CI.

### Require consumers to pin a raw ref instead of a version range

- Good, because it works today and is immutable.
- Bad, because it deviates from the acceptance criteria in issue #1 and the
  consumer issue, and turns every skill update into a manual version bump.

## More Information

- Verified by issue #1 and the consumer issue in the downstream repository;
  the alias-tag fix was confirmed against a local HTTPS git remote where the
  same manifest failed with only `v{version}` and passed once
  `sdlc--v0.1.1` existed.
- Related: [release process](../marketplace-release-process.md),
  [ADR-0001](0001-publish-workflow-owns-releases.md), [CONTRIBUTING.md](../../CONTRIBUTING.md).
- Reconsider when apm-cli emits a tag pattern for local package sources, or
  when the marketplace needs a package name that is not a valid git tag
  component - today that is a hard failure in the release gates, not a
  fallback.
