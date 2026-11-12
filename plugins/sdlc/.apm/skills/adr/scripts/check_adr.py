#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Check Architecture Decision Records against this repository's conventions.

Usage:
    uv run check_adr.py docs/adr
    uv run check_adr.py docs/adr/0002-some-decision.md --json

Exit codes: 0 no errors (warnings allowed), 1 errors found, 2 invalid input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from datetime import date, datetime
from os.path import normpath
from pathlib import Path
from typing import NoReturn

import yaml

STATUSES = {"proposed", "accepted", "rejected", "deprecated", "superseded"}
REQUIRED_SECTIONS = (
    "context and problem statement",
    "decision drivers",
    "considered options",
    "decision outcome",
    "consequences",
    "confirmation",
    "pros and cons of the options",
    "more information",
)
FILENAME = re.compile(r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
# A fenced code block opens with three or more backticks or tildes and closes
# with a run of the same character at least as long, on a line with nothing
# else. Fences are matched at any indent here: an indented fence belongs to a
# list item, and the indented-code test below runs first.
FENCE = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
# An indented code block is a run of lines indented four spaces or a tab. It
# cannot interrupt a paragraph (so it only starts after a blank line) and does
# not apply inside a list item, where the same indent is item content.
INDENTED = re.compile(r"^(?: {4}|\t)")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# An inline code span opens and closes with runs of exactly the same number of
# backticks and may wrap a line. A link inside one is literal text, and an
# amendment must be able to quote a decided record verbatim.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(?:(?!\1).)+?\1(?!`)", re.DOTALL)
# A quote of a link whose target a later decision moved or removed records that
# target's fate inside the amendment: `- Moved: <old> -> <new>` or
# `- Removed: <old>`. The original link then stays in place and stops failing.
HISTORICAL_FATE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])\s+(?P<fate>moved|renamed|deleted|removed)\s*:\s*"
    r"`?(?P<old>[^`\s]+)`?(?:\s*(?:->|\u2192|to)\s*`?(?P<new>[^`\s]+)`?)?",
    re.IGNORECASE,
)
MOVED_FATES = {"moved", "renamed"}
# A superseded ADR names its replacement as `ADR-0002` or as a `0002-*.md`
# filename. A bare four-digit run does not count - the mandatory ISO `date:`
# always supplies one - and neither does `#12`: the skill requires an issue
# link in every ADR, so an issue number would satisfy the rule for any draft.
# The filename form needs a letter in its stem so a date such as
# `2026-11-08.md` is not read as a record name, and may carry a relative path
# prefix (`adr/0002-next.md`) that is resolved from this ADR's directory, like
# any other relative link.
REPLACEMENT_REFERENCE = re.compile(
    r"ADR[- ]?(\d{4})\b|((?:[\w.\-]+/)*)\b(\d{4})-[a-z0-9-]*[a-z][a-z0-9-]*\.md\b",
    re.IGNORECASE,
)
# Only a sentence that claims the supersession names a replacement. A `Related:`
# cross-link must neither satisfy the rule nor be read as the replacement.
SUPERSESSION_CLAIM = re.compile(r"supersed|replac", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
NO_REPLACEMENT = (
    "status is superseded but no replacement ADR is referenced "
    "(use ADR-NNNN or NNNN-*.md)"
)
STOPWORDS = {
    "because",
    "being",
    "could",
    "deployed",
    "each",
    "every",
    "from",
    "have",
    "into",
    "must",
    "other",
    "should",
    "their",
    "there",
    "these",
    "they",
    "this",
    "using",
    "value",
    "values",
    "when",
    "where",
    "which",
    "while",
    "will",
    "with",
    "would",
}


def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def split_frontmatter(text: str) -> tuple[dict, str, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, "missing opening '---'"
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = "\n".join(lines[1:index])
            try:
                meta = yaml.safe_load(raw) or {}
            except yaml.YAMLError as error:
                return {}, "\n".join(lines[index + 1 :]), f"invalid YAML: {error}"
            if not isinstance(meta, dict):
                return {}, "\n".join(lines[index + 1 :]), "frontmatter is not a mapping"
            return meta, "\n".join(lines[index + 1 :]), None
    return {}, text, "missing closing '---'"


def mask_code(body: str) -> list[str | None]:
    """Return body lines with each line inside a code block replaced by None.

    The line count is preserved, so blanking a block cannot fuse the prose on
    either side of it into a link that nobody wrote.
    """
    masked: list[str | None] = []
    fence: str | None = None
    indented = False
    previous_blank = True
    previous_is_list = False
    for line in body.splitlines():
        if fence is not None:
            masked.append(None)
            closer = FENCE.match(line)
            if (
                closer
                and closer["marker"][0] == fence[0]
                and len(closer["marker"]) >= len(fence)
                and not closer["info"].strip()
            ):
                fence = None
            continue
        if not line.strip():
            masked.append(None if indented else "")
            previous_blank = True
            continue
        if INDENTED.match(line) and (
            indented or (previous_blank and not previous_is_list)
        ):
            indented = True
            masked.append(None)
            previous_blank = False
            continue
        indented = False
        opener = FENCE.match(line)
        if opener:
            fence = opener["marker"]
            masked.append(None)
            previous_blank = False
            previous_is_list = False
            continue
        masked.append(line)
        previous_blank = False
        previous_is_list = LIST_ITEM.match(line) is not None
    return masked


def iter_unfenced(body: str) -> Iterator[str]:
    """Yield the body lines that are outside a code block."""
    for line in mask_code(body):
        if line is not None:
            yield line


def prose(body: str) -> str:
    """Body text as it renders: code blocks and code spans blanked out."""
    return CODE_SPAN.sub(" ", "\n".join(line or "" for line in mask_code(body)))


def find_links(body: str) -> Iterator[str]:
    """Yield the destination of every link that renders as a link.

    A paragraph break ends a link, so the search runs block by block: pasting
    a fence between two fragments must not resolve them into a new link.
    """
    block: list[str] = []
    for line in prose(body).splitlines():
        if line.strip():
            block.append(line)
        elif block:
            yield from LINK.findall("\n".join(block))
            block = []
    if block:
        yield from LINK.findall("\n".join(block))


def sections(body: str) -> tuple[list[tuple[int, str]], dict[str, str]]:
    """Return all headings and the text under each (normalized) heading."""
    headings: list[tuple[int, str]] = []
    collected: dict[str, list[str]] = {}
    current: str | None = None
    for line in iter_unfenced(body):
        match = HEADING.match(line)
        if match:
            level, title = len(match.group(1)), match.group(2)
            headings.append((level, title))
            current = normalize(title)
            collected.setdefault(current, [])
            continue
        if current is not None:
            collected[current].append(line)
    return headings, {key: "\n".join(value) for key, value in collected.items()}


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("`", "").strip())


def replacement_errors(path: Path, number: int | None, body: str) -> list[str]:
    """A superseded ADR must name another existing record as its replacement.

    References are read only from sentences that claim the supersession, and a
    `NNNN-*.md` reference resolves from this ADR's directory like any other
    relative link. Mentions of one record are collapsed to a single claim.
    """
    references: dict[int, set[Path]] = {}
    for line in iter_unfenced(body):
        for sentence in SENTENCE.split(line):
            if not SUPERSESSION_CLAIM.search(sentence):
                continue
            for match in REPLACEMENT_REFERENCE.finditer(sentence):
                if match.group(1):
                    references.setdefault(int(match.group(1)), set())
                else:
                    references.setdefault(int(match.group(3)), set()).add(
                        (path.parent / match.group(0)).resolve()
                    )
    if not references:
        return [NO_REPLACEMENT]
    if any(
        reference != number
        and (
            any(path.parent.glob(f"{reference:04d}-*.md"))
            or any(target.exists() for target in targets)
        )
        for reference, targets in references.items()
    ):
        return []
    errors: list[str] = []
    for reference in references:
        if reference == number:
            errors.append(
                "status is superseded but the reference points at this ADR itself "
                f"(ADR-{reference:04d})"
            )
        else:
            errors.append(
                f"status is superseded but replacement ADR-{reference:04d} does not exist"
            )
    return errors


def historical_fates(body: str) -> dict[str, str | None]:
    """Map each path an amendment says moved or was removed to its new path.

    Only `## Amendment` sections count: a decided record's original text stays
    as written, so the record of what happened to a target belongs in the
    amendment added later. Keys are normalized so `./a.md` matches `a.md`.
    """
    _, texts = sections(body)
    fates: dict[str, str | None] = {}
    for heading, text in texts.items():
        if not heading.startswith("amendment"):
            continue
        for line in text.splitlines():
            match = HISTORICAL_FATE.match(line)
            if not match:
                continue
            moved = match["fate"].lower() in MOVED_FATES
            fates[normpath(match["old"])] = match["new"] if moved else None
    return fates


def link_errors(path: Path, body: str) -> list[str]:
    """Resolve every relative link that renders as a link.

    A link whose target no longer exists is an error unless an amendment
    records what happened to that target; deleting the link from a decided
    record would rewrite its history.
    """
    errors: list[str] = []
    fates = historical_fates(body)
    for old, replacement in fates.items():
        if not replacement:
            continue
        target = replacement.split("#", 1)[0]
        if not (path.parent / target).exists():
            errors.append(
                f"amendment records {old} -> {replacement}, "
                f"but {replacement} does not exist"
            )
    for target in find_links(body):
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        relative = target.split("#", 1)[0]
        if (path.parent / relative).resolve().exists():
            continue
        if normpath(relative) in fates:
            continue
        errors.append(f"broken relative link: {target}")
    return errors


def first_h1(headings: list[tuple[int, str]]) -> str | None:
    return next((title for level, title in headings if level == 1), None)


def check_file(path: Path, numbers: dict[int, list[str]]) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    text = path.read_text(encoding="utf-8")
    meta, body, frontmatter_error = split_frontmatter(text)

    if frontmatter_error:
        errors.append(f"frontmatter: {frontmatter_error}")

    status = meta.get("status")
    if status not in STATUSES:
        errors.append(f"frontmatter status {status!r} not in {sorted(STATUSES)}")

    raw_date = meta.get("date")
    if isinstance(raw_date, date):
        parsed_date = raw_date
    elif isinstance(raw_date, str) and ISO_DATE.match(raw_date):
        try:
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = None
    else:
        parsed_date = None
    if parsed_date is None:
        errors.append("frontmatter date missing or not ISO YYYY-MM-DD")

    if not str(meta.get("decision-makers") or "").strip():
        errors.append("frontmatter decision-makers is empty")

    if not FILENAME.match(path.name):
        errors.append(f"filename {path.name!r} is not NNNN-kebab-case.md")
    number = int(path.name[:4]) if path.name[:4].isdigit() else None
    if number is not None:
        numbers.setdefault(number, []).append(path.name)

    headings, section_text = sections(body)
    title = first_h1(headings)
    if not title:
        errors.append("no H1 title")
    else:
        if title.rstrip().endswith("?"):
            warnings.append("H1 is a question; state the decision instead")
        if normalize(title) in {"adr", "decision record", "architecture decision"}:
            errors.append("H1 must state the decision, not the document type")

    present = {normalize(item) for _, item in headings}
    for required in REQUIRED_SECTIONS:
        if not any(required in heading for heading in present):
            errors.append(f"missing section: {required}")

    consequences = section_text.get("consequences", "")
    if consequences:
        if "good, because" not in consequences.lower():
            warnings.append("Consequences has no 'Good, because' entry")
        if "bad, because" not in consequences.lower():
            warnings.append("Consequences has no 'Bad, because' entry")

    confirmation = section_text.get("confirmation", "").strip()
    if not confirmation:
        errors.append("Confirmation is empty")
    elif not re.search(r"^\s*(?:[-*]|\d+\.)\s+\S", confirmation, re.MULTILINE):
        warnings.append("Confirmation has no list item naming a check")
    elif re.search(r"\b(be careful|we will ensure)\b", confirmation, re.IGNORECASE):
        warnings.append("Confirmation reads as intent, not as a check that can fail")

    drivers = [
        line.strip("-* ").strip()
        for line in section_text.get("decision drivers", "").splitlines()
        if line.strip().startswith(("-", "*"))
    ]
    if not drivers:
        errors.append("Decision Drivers has no bullet")
    evidence = (consequences + section_text.get("more information", "")).lower()
    for driver in drivers:
        tokens = [
            token
            for token in re.findall(r"[a-z][a-z0-9-]{4,}", driver.lower())
            if token not in STOPWORDS
        ]
        if tokens and not any(token in evidence for token in tokens):
            warnings.append(f"driver has no matching consequence: {driver[:60]!r}")

    options = [
        line.strip("-* ").strip()
        for line in section_text.get("considered options", "").splitlines()
        if line.strip().startswith(("-", "*"))
    ]
    pros_headings = {
        normalize(title)
        for level, title in headings
        if level >= 3 and title
    }
    if not options:
        errors.append("Considered Options has no list item")
    for option in options:
        name = normalize(re.sub(r"[`\"']", "", option)).split(":")[0].rstrip(".").strip()
        if name not in pros_headings:
            warnings.append(f"option has no Pros and Cons subsection: {option[:60]!r}")

    if normalize(str(status)) == "superseded":
        errors.extend(replacement_errors(path, number, body))

    errors.extend(link_errors(path, body))

    if number is not None and number > 1 and (number - 1) not in numbers and not any(
        candidate < number for candidate in numbers
    ):
        warnings.append("numbering does not start at 0001")

    return {
        "file": str(path),
        "number": number,
        "title": title,
        "status": status,
        "errors": errors,
        "warnings": warnings,
    }


def collect(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        target = target.resolve()
        if target.is_dir():
            files.extend(sorted(path for path in target.glob("*.md") if FILENAME.match(path.name)))
        elif target.is_file():
            files.append(target)
        else:
            die(f"{target} does not exist")
    if not files:
        die("no ADR files found")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ADR structure and conventions.")
    parser.add_argument("paths", nargs="+", type=Path, help="ADR files or directories")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--fail-on-warn", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    files = collect(args.paths)
    numbers: dict[int, list[str]] = {}
    results = [check_file(path, numbers) for path in files]

    for number, names in numbers.items():
        if len(names) > 1:
            for result in results:
                if result["number"] == number:
                    result["errors"].append(f"duplicate ADR number {number:04d}: {', '.join(names)}")

    errors = sum(len(result["errors"]) for result in results)
    warnings = sum(len(result["warnings"]) for result in results)
    report = {
        "summary": {
            "files": len(results),
            "errors": errors,
            "warnings": warnings,
            "latest": max(numbers) if numbers else None,
        },
        "adrs": results,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for result in results:
            state = "FAIL" if result["errors"] else "OK"
            print(f"{state} {result['file']} (#{result['status']}, {len(result['errors'])} errors)")
            for error in result["errors"]:
                print(f"  error: {error}")
            for warning in result["warnings"]:
                print(f"  warn:  {warning}")
        print(
            f"\n{len(results)} file(s), {errors} error(s), {warnings} warning(s), "
            f"latest number {report['summary']['latest']}"
        )

    if errors or (args.fail_on_warn and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
