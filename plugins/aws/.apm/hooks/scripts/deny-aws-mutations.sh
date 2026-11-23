#!/usr/bin/env bash
# preToolUse hook wrapper: deny state-changing AWS commands.
#
# Denies `cdk deploy|bootstrap|destroy` and any AWS CLI operation that is not
# read-only (describe-/list-/get- style), plus plaintext secret reads.
#
# Ships with the `aws` package next to
# `.apm/agents/aws-solution-architect.agent.md`; APM deploys the hook JSON and
# this script together for every targeted harness.
#
# Contract: the event JSON arrives on stdin; exactly one JSON decision leaves
# on stdout. This wrapper must always exit 0 -- a non-zero exit from a
# `preToolUse` command hook is treated as a denial for every tool call.
set -u

payload="$(cat)"

python_bin=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done

if [ -z "$python_bin" ]; then
  # No interpreter: emit no decision rather than blocking every tool call.
  printf '{}\n'
  exit 0
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
guard="$script_dir/deny_aws_mutations.py"

if [ ! -f "$guard" ]; then
  printf '{}\n'
  exit 0
fi

printf '%s' "$payload" | "$python_bin" "$guard" || printf '{}\n'
exit 0
