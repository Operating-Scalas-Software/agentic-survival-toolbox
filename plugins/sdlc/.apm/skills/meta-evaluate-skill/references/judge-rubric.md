# LLM-as-judge rubric

Score the skill you are reviewing on the eight dimensions below. This rubric is
the judgment half of the evaluation; the bundled script covers the mechanical
half. Both feed one report, so a skill must be good **and** well-formed.

## Rules

- Judge the skill as written. Do not edit it, and do not credit fixes you would
  make yourself.
- Every dimension needs `evidence`: a heading, a quoted line, or a line number.
  A score without evidence is not a judgment, it is a guess.
- Use the whole 0-100 range. A competent skill is not automatically 90.
- Length is not quality. Reward coverage of decisions, not word count.
- Judge against what the agent would get wrong *without* the skill. Explaining
  common knowledge earns no points.

## Dimensions

Each dimension is scored 0-100 with this scale:

- **90-100** — a skilled author would not change it.
- **70-89** — good, with a specific improvement left.
- **50-69** — usable, but the gap would change agent behaviour.
- **20-49** — the intent is visible but the instructions mislead or omit.
- **0-19** — absent, wrong, or actively harmful.

### 1. `clarity`

Can a fresh agent follow the procedure without guessing? Look for ordered
steps, explicit inputs and defaults, one meaning per instruction, and an
unambiguous stopping condition.

- 100: each step names its input, action and expected result; no step can be
  read two ways.
- 50: order exists but some steps bundle two decisions or omit a precondition.
- 0: prose that describes a topic instead of a procedure.

### 2. `conciseness`

Is every sentence doing work? Reward removing generic advice ("handle errors
appropriately", "follow best practices") and content the model already knows.

- 100: no filler; each paragraph changes behaviour or prevents a mistake.
- 50: correct but padded — repeated rules, restated obvious facts.
- 0: mostly generic advice; the specific guidance is buried.

### 3. `actionability`

Can the agent execute? Look for runnable commands, concrete paths, exact flags,
and expected outputs. Commands must be copy-pasteable for this repository, not
pseudocode.

- 100: every fragile step has an exact command and a stated expected result.
- 50: commands exist but some need adaptation that the skill does not explain.
- 0: instructions that cannot be turned into actions.

### 4. `grounded_specificity`

Is the content grounded in real expertise — real commands, real failure modes,
real corrections — instead of generic training knowledge? A Gotchas section
with concrete corrections scores high; "be careful with X" scores low.

- 100: non-obvious, environment-specific facts that would otherwise be guessed
  wrong.
- 50: correct but generic; applies to any project, teaches little.
- 0: platitudes or invented details that do not hold.

### 5. `discoverability`

Will the right task load this skill? Judge `name` and `description`: trigger
phrases, task vocabulary, and a scope statement that excludes neighbouring
tasks.

- 100: name is specific; description names the triggers and the boundary.
- 50: description is accurate but generic ("helps with testing").
- 0: name or description cannot be matched to a user request.

### 6. `completeness`

Are the decision points covered? Look for branching rules (accept / decline /
partial), validation gates, failure handling, and an explicit completion
criterion. Missing branches are worse than missing polish.

- 100: every fork and stop condition the task can reach is addressed.
- 50: the happy path is complete; edge cases are left to judgment.
- 0: the procedure stops before the outcome the user asked for.

### 7. `progressive_disclosure`

Is the always-loaded body small, with detail moved to references or scripts that
the skill says **when** to load? Consolidation matters more than file count.

- 100: body is core instructions; every reference has a load condition.
- 50: body carries detail that only some runs need.
- 0: everything in one file, or resources with no pointer from the body.

### 8. `maintainability`

Will this survive edits? Look for a single source of truth for repeated logic,
tests or checks that catch drift, stable anchors, and no duplication that can
diverge silently.

- 100: shared logic lives once and is verified; edits cannot diverge quietly.
- 50: some duplication, but the copies are close enough to notice.
- 0: verbatim copies of fragile logic with no check.

## Output format

Write the judgment to a file (for example `/tmp/skill-judge.json`):

```json
{
  "dimensions": {
    "clarity": { "score": 90, "evidence": "## Procedure steps 1-9", "justification": "ordered, each step names its input" },
    "conciseness": { "score": 85, "evidence": "SKILL.md:1-232", "justification": "little filler" },
    "actionability": { "score": 92, "evidence": "## Procedure: commands", "justification": "commands runnable as written" },
    "grounded_specificity": { "score": 88, "evidence": "## Gotchas", "justification": "concrete corrections" },
    "discoverability": { "score": 84, "evidence": "frontmatter description", "justification": "triggers present" },
    "completeness": { "score": 86, "evidence": "## Completion checks", "justification": "gates and decline path" },
    "progressive_disclosure": { "score": 80, "evidence": "scripts/collect-review.sh", "justification": "detail moved out of body" },
    "maintainability": { "score": 85, "evidence": "single digest script", "justification": "no duplicated logic" }
  }
}
```

`weight` is optional and defaults to 1. Use a higher weight only when a
dimension is decisive for this kind of skill (for example `actionability` for a
runbook), and say why in the justification.
