"""Tests for plugins/aws/.apm/hooks/scripts/deny_aws_mutations.py."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "aws" / ".apm" / "hooks" / "scripts"
SCRIPT = SCRIPTS / "deny_aws_mutations.py"
WRAPPER = SCRIPTS / "deny-aws-mutations.sh"


def load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deny = load_script(SCRIPT)


BLOCKED_COMMANDS = [
    "npx cdk deploy --all",
    "cdk bootstrap aws://acct/eu-west-1",
    "cdk -c stage=prod deploy",
    "./node_modules/.bin/cdk destroy --all",
    "pnpm dlx aws-cdk bootstrap",
    "bash -c 'npx cdk deploy'",
    "pwsh -Command 'cdk destroy --all'",
    "eval 'cdk deploy'",
    "aws s3 rm s3://bucket/key --recursive",
    "aws s3 rb s3://bucket --force",
    "aws cloudformation deploy --template-file template.json --stack-name demo",
    "aws dynamodb delete-table --table-name links",
    "aws ssm send-command --document-name run-shell-script",
    "aws lambda invoke --function-name handler out.json",
    "aws secretsmanager get-secret-value --secret-id demo/api-key",
    "aws ssm get-parameter --name /demo/api-key --with-decryption",
]

ALLOWED_COMMANDS = [
    "cdk synth --all",
    "cdk ls",
    "npm run synth && npm test && npm run lint",
    "aws cloudformation describe-stacks --stack-name demo",
    "aws sts get-caller-identity",
    "aws s3 ls s3://bucket",
    "aws --profile work s3api list-objects-v2 --bucket bucket",
    "aws dynamodb scan --table-name links",
    "aws logs filter-log-events --log-group-name /aws/lambda/demo",
    "aws secretsmanager describe-secret --secret-id demo/api-key",
    "aws ssm get-parameter --name /demo/api-key",
    "aws --version",
    "aws help",
    "grep -n 'cdk deploy' README.md",
    "bash -c \"grep -n 'cdk deploy' README.md\"",
]


@pytest.mark.parametrize("command", BLOCKED_COMMANDS)
def test_blocks_state_changing_commands(command: str) -> None:
    assert deny.is_blocked(command), command


@pytest.mark.parametrize("command", ALLOWED_COMMANDS)
def test_allows_read_only_and_unrelated_commands(command: str) -> None:
    assert not deny.is_blocked(command), command


def read_event(monkeypatch: pytest.MonkeyPatch, payload: str) -> bool:
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    return deny.wants_denial()


def event(command: str, tool_name: str = "bash") -> str:
    return json.dumps({"toolName": tool_name, "toolArgs": {"command": command}})


def test_camel_case_event_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    assert read_event(monkeypatch, event("npx cdk deploy --all"))


def test_vscode_compatible_event_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "cdk destroy --all"}}
    )
    assert read_event(monkeypatch, payload)


def test_non_shell_tool_mentioning_a_command_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {"toolName": "edit", "toolArgs": {"newString": "run cdk deploy"}}
    )
    assert not read_event(monkeypatch, payload)


def test_empty_and_unparseable_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not read_event(monkeypatch, "")
    assert not read_event(monkeypatch, "{not json")
    assert read_event(monkeypatch, '{"toolName":"bash","toolArgs":{"command":"cdk deploy"')


def test_wrapper_denies_and_exits_zero() -> None:
    result = subprocess.run(
        ["bash", str(WRAPPER)],
        input=event("npx cdk deploy --all"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["permissionDecision"] == "deny"


def test_wrapper_allows_and_exits_zero() -> None:
    result = subprocess.run(
        ["bash", str(WRAPPER)],
        input=event("cdk synth"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
