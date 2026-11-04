# agentic-survival-toolbox

A public marketplace of reusable **agent skills** and **Copilot plugins**,
published as an APM package. Each primitive is versioned, dependency-managed by
[APM](https://microsoft.github.io/apm/), and installable with one command.

## Packages

| Package   | What it provides                                                                                                                                          |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`sdlc`](plugins/sdlc/README.md) | Skills for the software development lifecycle: pull-request review follow-up, Architecture Decision Records, and skill self-evaluation. |

## Install

### With APM (recommended)

```bash
apm marketplace add <owner>/agentic-survival-toolbox
apm install sdlc@agentic-survival-toolbox
```

Or declare it in your project's `apm.yml`:

```yaml
dependencies:
  apm:
    - name: sdlc
      marketplace: agentic-survival-toolbox
      version: "^0.1.0"
```

### As a Copilot CLI plugin

```bash
gh copilot marketplace add <owner>/agentic-survival-toolbox
gh copilot plugin install sdlc
```

## License

Apache-2.0. See [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). This repository is public — nothing
internal, private, or credential-bearing may be committed; a CI guard blocks it.
