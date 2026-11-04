---
name: meta-evaluate-skill
description: 'Evaluate an agentic skill package (a SKILL.md with its scripts and references) and produce one structured JSON report: deterministic checks from a bundled Python script plus an LLM-as-judge assessment, each dimension scored 0-100 with a weighted total. Use when asked to validate, audit, review, grade or score a skill, or to check a SKILL.md against best practices, e.g. "evaluate the skill in .github/skills/deploy-helper", "score this SKILL.md", "is this skill good enough to ship".'
argument-hint: '<skill dir or SKILL.md> [--judge judge.json] [--fail-under 75]'
---

# Evaluate an agent skill

Grade a skill package on two independent halves — mechanical structure and
judged quality — and emit one JSON report. Nothing is edited; the output is an
assessment plus fixable findings.

The evaluator lives in `scripts/` of the skill that defines this procedure;
targets are usually under `.github/skills/`, `.agents/skills/`,
`.claude/skills/` or `~/.copilot/skills/`.

## Inputs

- Target: a skill directory or its `SKILL.md`. Default: ask which skill when the
  request does not name one — never guess between unrelated skills.
- Threshold (optional): fail the run below this total, e.g. `--fail-under 75`.

## Progress

- [ ] Resolve the target skill directory and confirm `SKILL.md` exists
- [ ] Run the deterministic evaluator, capture the JSON
- [ ] Read the target as an agent would: body, scripts, references
- [ ] Score the eight judge dimensions with evidence
- [ ] Merge judge + deterministic into one report
- [ ] Report total, band, per-dimension table and the fixable gaps

## Procedure

### 1. Resolve the target

```bash
ls <target>/SKILL.md            # a directory target
ls <target-if-file-is-SKILL.md>
```

The folder name must equal the frontmatter `name` — the evaluator reports a
mismatch as a hard failure because the skill would silently never load.

### 2. Deterministic pass

Run the script with `uv`; the PEP 723 header installs PyYAML on the fly:

```bash
uv run <meta-skill-dir>/scripts/evaluate_skill.py <target> \
  --output /tmp/skill-eval.json
```

It prints `deterministic=<score> total=<score>` to stderr and writes the report.
Exit codes: `0` ok, `1` below `--fail-under`, `2` invalid input. Never hand-edit
its JSON — rerun it.

### 3. Read the target as an agent would

Read `SKILL.md` in full, then every file it points at (scripts, references,
assets). Judge what the agent will actually receive, not what the author meant.

### 4. LLM-as-judge

Follow [the rubric](./references/judge-rubric.md) and write the judgment to a
separate file:

```bash
$EDITOR /tmp/skill-judge.json      # 8 dimensions, each with score + evidence
```

Every dimension needs `score` (0-100), `evidence` and `justification`. Evidence
is a heading, a quoted line or a line number — not an opinion.

### 5. Merge and score

```bash
uv run <meta-skill-dir>/scripts/evaluate_skill.py <target> \
  --judge /tmp/skill-judge.json --output /tmp/skill-report.json \
  --fail-under 75
```

The script validates the judge file (all eight dimensions, scores in range) and
computes the weighted total. A malformed judge file exits `2` rather than
producing a partial score.

### 6. Report

Give the total and band first, then the per-dimension table, then only the
changes that would move the score. Do not restate every passing check.

## Scoring model

- Deterministic score: weighted mean of the script's checks (frontmatter and
  size weigh most; a failure is 0, a warning 50).
- Judge score: unweighted mean of the eight dimensions unless the judge sets a
  `weight`.
- Total: deterministic 40% + judge 60%. Both weights are constants in
  `scripts/evaluate_skill.py`.
- Bands: `excellent` ≥ 90, `good` ≥ 75, `needs-work` ≥ 60, `poor` below.

A skill at 100 deterministic and 55 judged is well-formed and unclear — report
it that way instead of averaging the tension away.

## Report template

```text
<name>: 87.4 / 100 (good) — deterministic 100.0, judged 79.1
lines=232  sections=8  failures=0  warnings=1

| Dimension              | Score | Evidence                     |
| ---------------------- | ----- | ---------------------------- |
| clarity                | 90    | ## Procedure steps 1-9        |
| concise...             | ...   | ...                          |

Fix first:
1. <dimension>: <what to change> (<file>:<line>)
2. ...
```

Keep the JSON file as the artifact; the text above is the summary.

## Gotchas

- Deterministic 100 does not mean good. Structural checks cannot see vague
  guidance; always run the judge step.
- The high-value deterministic failures are the silent ones: `name` ≠ folder,
  description over 1024 chars, unbalanced code fences, relative links to files
  that do not exist.
- Description length is measured in characters, not words; 1024 is the hard
  limit and 40 is the vagueness floor.
- Relative links with anchors (`./references/x.md#section`) resolve after the
  anchor is stripped.
- PyYAML parses bare `on`/`off`/`yes`/`no` as booleans. If that shows up in
  frontmatter parsing, the frontmatter is malformed — quote the value.
- `uv run` needs network access the first time to install PyYAML; if the
  environment is offline, run the script with a Python that already has PyYAML.
- Threshold failures exit `1`, not `0`. `set -e` in a caller will stop the
  pipeline; capture the code if you want to report the score anyway.
- Judge dimensions are fixed by the script's `JUDGE_DIMENSIONS`; adding a
  dimension means editing both the script and [the rubric](./references/judge-rubric.md).

## Completion checks

- [ ] Report JSON exists, parses, and has `deterministic`, `llm_judge`, `total`.
- [ ] Every judge dimension has evidence; no score was invented without reading.
- [ ] Total equals 0.4 × deterministic + 0.6 × judge (allow rounding).
- [ ] Band matches the total.
- [ ] The summary lists only fixable gaps, each with a file reference.
- [ ] The target skill was not modified.
