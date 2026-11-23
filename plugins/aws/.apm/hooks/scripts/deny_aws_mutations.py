"""preToolUse guard: deny state-changing AWS commands.

Reads a Copilot `preToolUse` event on stdin -- camelCase (`toolName`,
`toolArgs`) or the VS Code compatible snake_case form (`tool_name`,
`tool_input`) -- and prints exactly one JSON decision on stdout.

Denies shell tool calls that:

* invoke `cdk deploy`, `cdk bootstrap` or `cdk destroy`, including prefixed
  forms such as `npx cdk deploy` or `./node_modules/.bin/cdk destroy`;
* invoke any AWS CLI operation that is not on the read-only allowlist
  (describe-/list-/get- style calls), so `aws s3 rm`, `aws cloudformation
  deploy`, `aws dynamodb delete-table` and friends are refused.

Never raises and always exits 0 from the caller's perspective: a crash in a
`preToolUse` command hook would fail closed and deny every tool call,
including reads and searches.
"""

import json
import re
import shlex
import sys

BLOCKED_SUBCOMMANDS = {"deploy", "bootstrap", "destroy"}
CDK_EXECUTABLES = {"cdk", "cdk.js", "aws-cdk"}
# Shell interpreters whose `-c` argument is itself a command line.
INTERPRETERS = {"bash", "sh", "zsh", "dash", "ksh", "powershell", "pwsh"}
INTERPRETER_COMMAND_FLAGS = {"-c", "-command", "/c"}

AWS_EXECUTABLES = {"aws", "aws.cmd", "aws.exe"}
# AWS CLI operations that only read provider state.
READ_ONLY_PREFIXES = (
    "batch-get-",
    "decode-",
    "describe-",
    "estimate-",
    "filter-",
    "generate-",
    "get-",
    "head-",
    "list-",
    "lookup-",
    "preview-",
    "search-",
    "simulate-",
    "validate-",
)
READ_ONLY_OPERATIONS = {
    "help",
    "ls",
    "presign",
    "query",
    "scan",
    "tail",
    "wait",
}
READ_ONLY_SERVICES = {"help"}
# Read-only calls that still return plaintext secrets.
PLAINTEXT_SECRET_OPERATIONS = {("secretsmanager", "get-secret-value")}
PLAINTEXT_SECRET_FLAGS = {"--with-decryption"}
# Global AWS CLI options that consume the following token as their value.
AWS_VALUE_OPTIONS = {
    "--ca-bundle",
    "--cli-connect-timeout",
    "--cli-read-timeout",
    "--color",
    "--endpoint-url",
    "--output",
    "--profile",
    "--query",
    "--region",
}
# Global CDK options that consume the following token as their value.
VALUE_OPTIONS = {
    "-a",
    "--app",
    "-c",
    "--context",
    "-e",
    "--env",
    "-o",
    "--output",
    "-p",
    "--profile",
    "-r",
    "--role-arn",
    "--ca-bundle-path",
    "--plugin",
    "--proxy",
}
SHELL_TOOL_NAME = re.compile(
    r"bash|powershell|shell|terminal|command|exec", re.IGNORECASE
)
# Used only when the payload is not parseable JSON: match the invocation
# directly instead of relying on shell tokenization of JSON punctuation.
RAW_FALLBACK = re.compile(
    r"\bcdk(?:\.js)?\s+(?:deploy|bootstrap|destroy)\b", re.IGNORECASE
)
REASON = (
    "Blocked by the AWS Solution Architect hook: state-changing AWS commands "
    "are denied. Only read-only AWS CLI operations (describe/list/get-style) "
    "are allowed; plaintext secret reads (`get-secret-value`, "
    "`--with-decryption`) and `cdk deploy`, `cdk bootstrap`, `cdk destroy` "
    "are always refused. Propose the command in the review and ask the human "
    "to run it."
)


def iter_strings(value):
    """Yield every string inside a tool-argument payload."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_strings(item)


def iter_simple_commands(command):
    """Split a shell command into simple commands on shell operators.

    Quoted text stays in one token, so a quoted mention such as
    `grep 'cdk deploy' README.md` does not look like an invocation.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|(){}`\n")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes: degrade to a plain split
        tokens = re.split(r"[\s;&|(){}`]+", command)

    operators = set(";&|(){}`\n")
    current = []
    for token in tokens:
        if token and set(token) <= operators:
            if current:
                yield current
            current = []
        else:
            current.append(token)
    if current:
        yield current


def subcommand_after(tokens, index):
    """First non-option token after tokens[index], skipping option values."""
    position = index + 1
    while position < len(tokens):
        token = tokens[position]
        if token.startswith("-"):
            takes_value = token in VALUE_OPTIONS and "=" not in token
            position += 2 if takes_value else 1
            continue
        return token
    return ""


def aws_operation(tokens, index):
    """Return (service, operation) for an `aws` invocation, skipping options."""
    position = index + 1
    service = ""
    while position < len(tokens):
        token = tokens[position]
        if token.startswith("-"):
            takes_value = token in AWS_VALUE_OPTIONS and "=" not in token
            position += 2 if takes_value else 1
            continue
        service = token
        position += 1
        break

    if not service:
        return "", ""

    while position < len(tokens):
        token = tokens[position]
        if token.startswith("-"):
            takes_value = token in AWS_VALUE_OPTIONS and "=" not in token
            position += 2 if takes_value else 1
            continue
        return service, token
    return service, ""


def is_read_only_aws(service, operation):
    if service in READ_ONLY_SERVICES:
        return True
    if not operation:
        return False
    if operation in READ_ONLY_OPERATIONS:
        return True
    return operation.startswith(READ_ONLY_PREFIXES)


def returns_plaintext_secret(service, operation, tokens):
    if (service, operation) in PLAINTEXT_SECRET_OPERATIONS:
        return True
    if service == "ssm" and operation.startswith("get-parameter"):
        return any(
            token in PLAINTEXT_SECRET_FLAGS
            or token.startswith(tuple(flag + "=" for flag in PLAINTEXT_SECRET_FLAGS))
            for token in tokens
        )
    return False


def is_blocked(command, depth=0):
    if depth > 3:
        return False
    for tokens in iter_simple_commands(command):
        if not tokens:
            continue
        head = tokens[0].rsplit("/", 1)[-1].lower()
        # `sh -c "cdk deploy"` and friends: inspect the wrapped command line.
        if head in INTERPRETERS:
            for position, token in enumerate(tokens[1:], start=1):
                if token.lower() in INTERPRETER_COMMAND_FLAGS:
                    if is_blocked(" ".join(tokens[position + 1 :]), depth + 1):
                        return True
                    break
        elif head == "eval":
            if is_blocked(" ".join(tokens[1:]), depth + 1):
                return True
        for index, token in enumerate(tokens):
            name = token.rsplit("/", 1)[-1]
            if name in CDK_EXECUTABLES:
                if subcommand_after(tokens, index) in BLOCKED_SUBCOMMANDS:
                    return True
            elif name in AWS_EXECUTABLES:
                service, operation = aws_operation(tokens, index)
                if not service:
                    continue
                if not is_read_only_aws(service, operation):
                    return True
                if returns_plaintext_secret(service, operation, tokens):
                    return True
    return False


def wants_denial():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except Exception:
        # Unparseable payload: still scan the raw text so a mutated command
        # cannot slip through because of malformed JSON.
        return bool(RAW_FALLBACK.search(raw))

    if not isinstance(event, dict):
        return bool(RAW_FALLBACK.search(raw))

    tool_name = event.get("toolName") or event.get("tool_name") or ""
    if not isinstance(tool_name, str):
        tool_name = ""
    tool_args = event.get("toolArgs")
    if tool_args is None:
        tool_args = event.get("tool_input")

    if tool_args is None:
        return False
    # Only shell-like tools can run a command; editing a file that merely
    # mentions `cdk deploy` must stay allowed.
    if tool_name and not SHELL_TOOL_NAME.search(tool_name):
        return False
    return any(is_blocked(text) for text in iter_strings(tool_args))


def main():
    try:
        deny = wants_denial()
    except Exception:  # never fail closed on an internal error
        deny = False

    if deny:
        print(
            json.dumps(
                {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON,
                }
            )
        )
    else:
        print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
