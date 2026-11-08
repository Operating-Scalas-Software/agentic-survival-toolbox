---
status: accepted
date: 2026-11-08
decision-makers: repository maintainers
consulted: GitHub Actions run history, issues #3 and #7, pull request #9
informed: marketplace consumers
---

# Publish tags and releases from `publish.yml`, not from a `release.yml` on `v*` tags

## Context and Problem Statement

The marketplace ships from `main`: each merge runs `publish.yml`, which packs the
marketplace output and pushes it to the `marketplace` branch. Versioned releases
need a `vX.Y.Z` tag and a notes-only GitHub Release, per
[the release process](../marketplace-release-process.md).

A tag pushed by a workflow using the built-in `GITHUB_TOKEN` does not trigger
another workflow. A `release.yml` on `push: tags: ["v*"]` therefore fires only
for hand-pushed tags — a path nothing else exercises — while the automated tags
it was meant to release get no release at all. This record decides who owns the
tag and the release. It does not change how versions are chosen.

## Decision Drivers

- A tag pushed with `GITHUB_TOKEN` does not cascade to a workflow, so a tag-triggered release workflow cannot release the automated tags.
- One owner per artifact keeps the release linear and traceable.
- No long-lived token or GitHub App credential may be added just to make the tag push cascade.
- A failed or partial run must converge on rerun instead of leaving a tag without a release.

## Considered Options

- Status quo: `publish.yml` tags, `release.yml` releases.
- One owner: `publish.yml` creates the tag and the release.
- `release.yml` owns both, invoked from `publish.yml` via `workflow_dispatch`.
- `release.yml` owns both, triggered by a PAT or GitHub App token push.

## Decision Outcome

Chosen option: "One owner: `publish.yml` creates the tag and the release",
because a `GITHUB_TOKEN` tag push cannot cascade, so the tag-triggered workflow
would only run for the path it is not needed for.

The decision has these parts:

1. **Tag creation is idempotent** — `publish.yml` derives `vX.Y.Z` from the root
   `apm.yml` `version` and skips the push when the tag already exists.
2. **Release creation is keyed on the tag** — `gh release create` runs only when
   no release exists for that tag, so a rerun after a partial failure converges.
3. **No `release.yml` exists** — no workflow triggers on `v*` tags; the release
   process doc carries the rationale for consumers.

### Consequences

- Good, because one owner (the publish run) covers tag and release, so a failed
  run is diagnosed from a single workflow log.
- Good, because release creation is keyed on the tag, so a deleted or failed
  release converges on the next publish run instead of needing manual repair.
- Bad, because tag and release can no longer be reviewed or retried separately;
  changing one means changing the other.
- Bad, because a manually pushed tag gets no release until a merge sets the
  `apm.yml` `version` to that tag, so cutting a release out of band needs an
  explicit `gh release create`.
- Bad, because tagging depends on the `GITHUB_TOKEN` write permission alone,
  with no token or App credential to fall back on if that permission is lost.

### Confirmation

- `publish.yml` fails when `apm pack --check-versions` reports a version
  mismatch, so a tag can only come from a lockstep version.
- `gh release view` gates `gh release create`, so an existing release is never
  duplicated and a missing one is created; the run fails only if `create` fails.
- `validate.yml` fails when `.github/workflows/release.yml` exists, so a second
  owner cannot be merged.

## Pros and Cons of the Options

### Status quo

- Good, because tag and release logic stay in separate files.
- Bad, because the tag-triggered workflow never runs for automated tags, so the
  released artifacts and the release records come from different paths.

### One owner

- Good, because one run owns the whole flow, with no cascading trigger needed.
- Bad, because the publish workflow carries release logic that cannot be
  exercised without merging to `main`.

### `release.yml` owns both, invoked from `publish.yml` via `workflow_dispatch`

- Good, because release logic sits next to the tag trigger it documents.
- Bad, because it needs `actions: write` on `publish.yml` and turns one run into
  two, adding an asynchronous failure surface with no local way to retry the
  second half.

### `release.yml` owns both, triggered by a PAT or GitHub App token push

- Good, because the tag trigger works exactly as written.
- Bad, because it requires a long-lived secret to rotate and protects, for a
  flow that a single run already covers.

## More Information

- Decided in #7 and implemented in #9; requested by #3.
- Related: [release process](../marketplace-release-process.md),
  [contributing guide](../../CONTRIBUTING.md).
- Reconsider when a release must be cut from a tag pushed outside `main`, or
  when release notes need review before the release is published.
