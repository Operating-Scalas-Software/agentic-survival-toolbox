---
name: adr
description: 'Write, amend or supersede an Architecture Decision Record in docs/adr/. Use when a decision needs to be recorded or reviewed: a new ADR, an amendment to an accepted ADR, superseding an old decision, or turning an issue into an ADR, e.g. "write an ADR for a deployment strategy", "record this decision", "amend ADR-0001", "review ADR-0002".'
argument-hint: '<issue number or decision title> [amend NNNN]'
---

# Architecture Decision Records

An ADR records **one decision** and the reasoning that outlives it: what was
decided, what else was on the table, what it costs, and how anyone can check it
is still true. It is not a design document — design detail belongs in the issue,
the PR or the runbook.

Conventions come from the repository's existing ADRs (`docs/adr/NNNN-*.md`);
match the newest one rather than inventing a format. The bundled checker
(`scripts/check_adr.py`) enforces the shape: run it to find the next number and
again after drafting.

## Progress

- [ ] Frame one decision and its scope
- [ ] Gather evidence and drivers from code, issues and earlier ADRs
- [ ] Pick the number and file name
- [ ] Draft with the template (all sections present)
- [ ] Amend vs supersede decided explicitly
- [ ] Cross-link ADR ↔ issue, and related ADRs
- [ ] Validate formatting, links and frontmatter

## Procedure

### 1. Frame the decision

Write the decision as one declarative sentence before drafting. If it needs "and"
to hold together, it is two ADRs. Record what is out of scope in the same breath.

### 2. Gather evidence

Read the code the decision touches, the ADRs it constrains, and the issue
discussion. Drivers must be facts, not preferences — quotes like "free plan has
no environment protection rules" or "forks are disabled" belong here and must
reappear in Consequences.

### 3. Number and name

Ask the checker for the highest number in use, then take the next one:

```bash
uv run <skill-dir>/scripts/check_adr.py docs/adr --json | jq .summary.latest
```

Name it `docs/adr/NNNN-kebab-case-title.md`, zero-padded to four digits, e.g.
`0002-deploy-from-a-build-once-artifact.md`. The H1 is the decision
as a statement ("Deploy from a build-once artifact, gated by a CI check"),
never a question or a topic.

### 4. Draft

Use the template below. Non-negotiable parts:

- **Decision Drivers** — the forces that decide it; each one must show up in
  Consequences or More Information.
- **Considered Options** — the real alternatives, including keeping the status
  quo. No straw men; if an option is obviously bad, say why it stayed on the
  list.
- **Decision Outcome** — "Chosen option: X, because Y", then numbered parts when
  the decision has several moving pieces.
- **Consequences** — Good and Bad, each phrased "because …". State what gets
  worse and which risk is accepted on purpose.
- **Confirmation** — the test, workflow step, drift check or review rule that
  proves the decision is honoured. If it cannot fail, it is not a confirmation.
- **More Information** — deferred work with issue links, "reconsider when"
  triggers, and links to related ADRs.

### 5. Amend or supersede

- A different decision ⇒ a **new ADR**; set the old one's `status` to
  `superseded` and point to the replacement.
- A correction or extension of an accepted ADR ⇒ add `## Amendment (YYYY-MM-DD)`
  at the end: what changed, why, what still holds. Leave the original text intact.
- Never rewrite the rationale of a decided ADR; the history is the value.

### 6. Cross-link

Caller and callee both link: ADR references its issue, the issue references the
ADR, and dependent ADRs reference each other. Follow-ups that are not decided
here become issues, listed in More Information.

### 7. Validate

```bash
uv run <skill-dir>/scripts/check_adr.py docs/adr
npx prettier --check docs/adr/NNNN-*.md
```

The checker fails on a missing or malformed frontmatter, an unknown `status`,
a non-ISO `date`, an empty `decision-makers`, a missing section, an empty
`Confirmation`, a broken relative link, a duplicate number, or a `superseded`
status with no replacement referenced. It warns about a question-style H1, a
Consequences section without a Bad entry, an option with no Pros and Cons
subsection, and a driver that no consequence mentions.

Then read the result yourself: is the decision actually stated in the title, and
could a reviewer disagree with the reasoning?

## Template

```markdown
---
status: proposed
date: YYYY-MM-DD
decision-makers: <who decides>
consulted:
informed:
---

# <Decision as a statement>

## Context and Problem Statement

<The situation and the forces at play. Link the issue.>

## Decision Drivers

- <constraint that dominates the choice>
- <second constraint>

## Considered Options

- <option A>
- <option B>
- <option C>

## Decision Outcome

Chosen option: "<option>", because <reason tied to a driver>.

The decision has these parts:

1. **<part>** — <what it means>.
2. **<part>** — <what it means>.

### Consequences

- Good, because <benefit>.
- Bad, because <accepted cost or risk>.

### Confirmation

- <test / workflow step / drift check that fails if the decision is violated>

## Pros and Cons of the Options

### <Option A>

- Good, because <reason>.
- Bad, because <reason>.

### <Option B>

- Good, because <reason>.
- Bad, because <reason>.

## More Information

- Deferred: <work not done here> — tracked in #<issue>.
- Reconsider when <trigger>.
- Related: #<issue>, <other ADR>.
```

## Worked example

- **Decision sentence** — "Keep environment-specific values in a reviewed config
  file; use CI environment variables only for deploy-time facts, with a check
  that they match."
- **Drivers** — one build must cover every stage; environment-scoped variables
  are invisible to a single build job; the file is reviewable in git.
- **Options** — status quo, hybrid with drift check, per-stage builds, values
  passed via flags.
- **Confirmation** — a build step that fails when an environment variable
  differs from the config file.
- **More Information** — an "add a stage" procedure, and a follow-up for the
  production environment.

## Gotchas

- Allowed `status` values: `proposed`, `accepted`, `rejected`,
  `deprecated`, `superseded`; `date` is ISO `YYYY-MM-DD`.
- Pasting the issue body duplicates a source of truth that will drift; link it
  and summarize only what the decision needs.
- An ADR that only lists benefits reads as advocacy. The Bad entries are what
  make it reviewable, so write them first if the Good ones come too easily.
- Keep the file short (roughly 60-120 lines). Implementation detail belongs in
  the PR that follows.
- The "driver has no matching consequence" warning is a keyword heuristic with a
  fixed stopword list: a driver rephrased with different words can warn on an
  otherwise valid ADR. Treat it as a nudge, not a failure; make the driver's key
  terms appear in a consequence if the warning is real.
- The checker's warnings are judgement calls (question-style title, missing Bad
  entry, unmatched driver). `--fail-on-warn` turns them into failures for CI;
  locally, read them and fix what is real instead of silencing them.

## Completion checks

- [ ] One decision, stated in the title
- [ ] Frontmatter has `status`, `date`, `decision-makers`
- [ ] Every driver maps to a consequence or a More Information item
- [ ] Considered options include the status quo
- [ ] Consequences name what gets worse
- [ ] Confirmation names a check that can fail
- [ ] More Information lists deferred work and a reconsider-when trigger
- [ ] ADR and issue link to each other
- [ ] `check_adr.py` reports no errors and `npx prettier --check` passes
