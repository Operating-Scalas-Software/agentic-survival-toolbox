# sdlc

Reusable skills for the software development lifecycle.

| Skill                 | Purpose                                                                              |
| --------------------- | ------------------------------------------------------------------------------------ |
| `address-pr-comments` | Turn pull-request review feedback into validated, pushed changes, closing or reporting every thread. |
| `meta-evaluate-skill` | Score an agent skill (deterministic checks + LLM judge) and emit a structured JSON report. |
| `adr`                 | Write, amend, or supersede an Architecture Decision Record with a machine-checkable shape. |

Each skill ships with its own bundled scripts; `meta-evaluate-skill` and `adr`
run their Python helpers via `uv`.

## License

Apache-2.0.
