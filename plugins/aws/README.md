# aws

AWS architecture review primitives: a Well-Architected solution architect agent
and a `preToolUse` guard that refuses state-changing AWS commands.

| Primitive                | Kind              | Purpose                                                                                                         |
| ------------------------ | ----------------- | --------------------------------------------------------------------------------------------------------------- |
| `aws-solution-architect` | agent             | Reviews blueprints, infrastructure code, application code and pull requests across the Well-Architected pillars and lenses. |
| `deny-aws-mutations`     | hook (`preToolUse`) | Denies `cdk deploy`/`bootstrap`/`destroy`, AWS CLI calls that are not read-only, and plaintext secret reads.     |

The agent reads the repository's own guidance first (`AGENTS.md`, Copilot
instructions, architecture docs, ADRs) and reports by default: a verdict, a
per-pillar findings table with file-and-line evidence, and a prioritized
remediation plan. It changes code only when the request asks for fixes.

## What lands where

For Copilot, `apm install` deploys:

- `.github/agents/aws-solution-architect.agent.md`
- `.github/hooks/aws-deny-aws-mutations.json` plus its scripts under
  `.github/hooks/scripts/aws/`

The hook is a workspace hook, not an agent-scoped one. Once installed it runs for
every agent session in the repository, which is deliberate: the guard protects
the account whichever agent runs a command. That is also why the agent carries no
inline `hooks` block.

## Requirements

- The hook needs `bash` and `python3` (or `python`) on the machine running the
  agent. If no interpreter is available it emits no decision, rather than failing
  closed and blocking every tool call.
- Hook commands run with the repository root as the working directory; the
  wrapper resolves its Python guard relative to its own path, so the deployed copy
  is self-contained.

## Install

With APM:

```bash
apm marketplace add <owner>/agentic-survival-toolbox
apm install aws@agentic-survival-toolbox
```

Or declare it in a project's `apm.yml`:

```yaml
dependencies:
  apm:
    - name: aws
      marketplace: agentic-survival-toolbox
      version: "^0.2.0"
```

As a Copilot CLI plugin:

```bash
copilot plugin marketplace add <owner>/agentic-survival-toolbox
copilot plugin install aws@agentic-survival-toolbox
```

## License

Apache-2.0.
