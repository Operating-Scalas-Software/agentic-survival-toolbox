# agentic-survival-toolbox

A public marketplace of reusable **agent skills**, **agents**, and **Copilot
plugins**, published as an APM package. Each primitive is versioned,
dependency-managed by [APM](https://microsoft.github.io/apm/), and installable
with one command.

## Plugins and primitives

| Plugin | Primitives |
| --- | --- |
| [`aws`](plugins/aws/README.md) | `aws-solution-architect` · `deny-aws-mutations` |
| [`sdlc`](plugins/sdlc/README.md) | `address-pr-comments` · `adr` · `meta-evaluate-skill` |

- `aws-solution-architect` — review a blueprint, infrastructure code, or pull
  request against the AWS Well-Architected pillars and lenses.
- `deny-aws-mutations` — `preToolUse` guard that refuses `cdk deploy`/`bootstrap`/
  `destroy` and any AWS CLI call that is not read-only.
- `address-pr-comments` — work through PR review feedback: fetch threads, fix or
  justify each, push, and resolve.
- `adr` — write, amend, or supersede an Architecture Decision Record.
- `meta-evaluate-skill` — score an agent skill and emit a structured JSON report.

This table is kept in sync with `plugins/<pkg>/README.md`; contributors update
both when adding a primitive (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Install

### With APM (recommended)

```bash
apm marketplace add <owner>/agentic-survival-toolbox
apm install sdlc@agentic-survival-toolbox
apm install aws@agentic-survival-toolbox
```

Or declare it in your project's `apm.yml`:

```yaml
dependencies:
  apm:
    - name: sdlc
      marketplace: agentic-survival-toolbox
      version: "^0.2.0"
```

### As a Copilot CLI plugin

```bash
copilot plugin marketplace add <owner>/agentic-survival-toolbox
copilot plugin install sdlc@agentic-survival-toolbox
```

## License

Apache-2.0. See [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/marketplace-release-process.md](docs/marketplace-release-process.md). This
repository is public — nothing internal, private, or credential-bearing may be
committed; a CI guard blocks it.
