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
from datetime import date, datetime
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
# A superseded ADR names its replacement as `ADR-0002` or as a `0002-*.md`
# filename. A bare four-digit run does not count - the mandatory ISO `date:`
# always supplies one - and neither does `#12`: the skill requires an issue
# link in every ADR, so an issue number would satisfy the rule for any draft.
# The filename form needs a letter in its stem so a date such as
# `2026-11-08.md` is not read as a record name.
REPLACEMENT_REFERENCE = re.compile(
    r"ADR[- ]?(\d{4})\b|\b(\d{4})-[a-z0-9-]*[a-z][a-z0-9-]*\.md\b",
    re.IGNORECASE,
)
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


def sections(body: str) -> tuple[list[tuple[int, str]], dict[str, str]]:
    """Return all headings and the text under each (normalized) heading."""
    headings: list[tuple[int, str]] = []
    collected: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            collected.setdefault(current or "", []).append(line)
            continue
        if not in_fence:
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


def unfenced(body: str) -> str:
    """Drop fenced code blocks, so a quoted example cannot satisfy a prose rule."""
    kept: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def replacement_errors(path: Path, number: int | None, body: str) -> list[str]:
    """A superseded ADR must name another record that exists next to it."""
    references = [
        int(candidate)
        for match in REPLACEMENT_REFERENCE.finditer(unfenced(body))
        for candidate in match.groups()
        if candidate
    ]
    if not references:
        return [NO_REPLACEMENT]
    errors: list[str] = []
    for reference in references:
        if reference == number:
            errors.append(
                "status is superseded but the reference points at this ADR itself "
                f"(ADR-{reference:04d})"
            )
        elif not any(path.parent.glob(f"{reference:04d}-*.md")):
            errors.append(
                f"status is superseded but replacement ADR-{reference:04d} does not "
                "exist next to this ADR"
            )
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

    for target in LINK.findall(body):
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            errors.append(f"broken relative link: {target}")

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
