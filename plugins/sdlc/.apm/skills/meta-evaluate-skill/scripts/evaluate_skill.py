#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Deterministic evaluator for agentic skills (SKILL.md packages).

Runs structural, frontmatter, size, link and hygiene checks, then optionally
merges an LLM-as-judge result into one scored JSON report.

Usage:
    uv run evaluate_skill.py <skill-dir-or-SKILL.md> [--judge judge.json]
                             [--output report.json] [--fail-under 75]

The judge file is a JSON object with a "dimensions" object, one entry per
rubric dimension, each with "score" (0-100), "evidence" and "justification".
Exit codes: 0 report written, 1 score below --fail-under, 2 invalid input.
Scoring: total = 0.4 * deterministic + 0.6 * judge (see DIMENSION_WEIGHTS);
bands are >=90 excellent, >=75 good, >=60 needs-work, else poor.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import NoReturn

import yaml

MAX_LINES = 500
WARN_LINES = 300
MAX_TOKENS = 5000
WARN_TOKENS = 3500
MAX_DESCRIPTION = 1024
MIN_DESCRIPTION = 40
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

DIMENSION_WEIGHTS = {"deterministic": 0.4, "llm_judge": 0.6}
JUDGE_DIMENSIONS = (
    "clarity",
    "conciseness",
    "actionability",
    "grounded_specificity",
    "discoverability",
    "completeness",
    "progressive_disclosure",
    "maintainability",
)

SECRET_PATTERNS = {
    "aws access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "generic bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{30,}\b"),
}

IGNORED_PARTS = {".git", ".ruff_cache", "__pycache__", ".venv", "node_modules", ".mypy_cache"}

LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
PROCEDURE_HEADINGS = ("procedure", "steps", "workflow", "process", "how to")
VALIDATION_HEADINGS = ("completion check", "validation", "checklist", "success criteria")
GOTCHA_HEADINGS = ("gotcha", "pitfall", "edge case", "anti-pattern", "troubleshoot")
PLACEHOLDERS = re.compile(
    r"\b(TODO|TBD|FIXME|XXX)\b|lorem ipsum|<insert[^>]*>", re.IGNORECASE
)


@dataclass
class Check:
    id: str
    category: str
    weight: float
    status: str
    score: int
    detail: str


def fail(check_id: str, category: str, weight: float, detail: str) -> Check:
    return Check(check_id, category, weight, "fail", 0, detail)


def warn(check_id: str, category: str, weight: float, detail: str) -> Check:
    return Check(check_id, category, weight, "warn", 50, detail)


def ok(check_id: str, category: str, weight: float, detail: str) -> Check:
    return Check(check_id, category, weight, "pass", 100, detail)


def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


_FENCE_INFO = re.compile(r"[A-Za-z0-9_+.-]{1,32}")


def _is_fence(line: str) -> bool:
    """True when `line` is a markdown fence delimiter, optionally with an info string."""
    s = line.strip()
    if not (s.startswith("```") or s.startswith("~~~")):
        return False
    marker = s[0]
    run = len(s) - len(s.lstrip(marker))
    if run < 3:
        return False
    rest = s[run:].strip()
    return rest == "" or bool(_FENCE_INFO.fullmatch(rest))


def skill_dir(path: Path) -> Path:
    path = path.resolve()
    if path.is_file() and path.name == "SKILL.md":
        return path.parent
    if path.is_dir() and (path / "SKILL.md").is_file():
        return path
    die(f"{path} is not a skill directory or SKILL.md file")


def split_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, "missing opening '---'"
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = "\n".join(lines[1:index])
            try:
                meta = yaml.safe_load(raw)
            except yaml.YAMLError as error:
                return None, "\n".join(lines[index + 1 :]), f"invalid YAML: {error}"
            if not isinstance(meta, dict):
                return None, "\n".join(lines[index + 1 :]), "frontmatter is not a mapping"
            return meta, "\n".join(lines[index + 1 :]), None
    return None, text, "missing closing '---'"


def headings(body: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if match:
            found.append((len(match.group(1)), match.group(2).lower()))
    return found


def has_heading(found: list[tuple[int, str]], needles: tuple[str, ...]) -> bool:
    return any(needle in title for _, title in found for needle in needles)


def resolve_links(body: str, base: Path) -> list[tuple[str, Path]]:
    links: list[tuple[str, Path]] = []
    for target in LINK_PATTERN.findall(body):
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        clean = target.split("#", 1)[0]
        if not clean:
            continue
        links.append((target, (base / clean).resolve()))
    return links


def iter_files(base: Path) -> list[Path]:
    return [
        path
        for path in sorted(base.rglob("*"))
        if path.is_file() and not IGNORED_PARTS.intersection(path.relative_to(base).parts)
    ]


def scan_text_files(base: Path) -> list[Path]:
    extensions = {".md", ".py", ".sh", ".js", ".ts", ".yaml", ".yml", ".json"}
    return [path for path in iter_files(base) if path.suffix in extensions]


def run_checks(base: Path) -> tuple[list[Check], dict]:
    skill_file = base / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    meta, body, frontmatter_error = split_frontmatter(text)
    meta = meta or {}
    checks: list[Check] = []

    value = meta.get("name")
    name = value if isinstance(value, str) else ""
    description = meta.get("description")
    description = description if isinstance(description, str) else ""

    # Frontmatter
    if frontmatter_error:
        checks.append(fail("frontmatter.valid", "frontmatter", 3, frontmatter_error))
    else:
        checks.append(ok("frontmatter.valid", "frontmatter", 3, "delimiters and YAML parse"))

    if name and NAME_PATTERN.match(name) and len(name) <= 64:
        checks.append(ok("frontmatter.name_valid", "frontmatter", 3, f"name='{name}'"))
    else:
        checks.append(
            fail(
                "frontmatter.name_valid",
                "frontmatter",
                3,
                "name must be 1-64 chars of lowercase alphanumerics and hyphens",
            )
        )

    if name == base.name:
        checks.append(ok("frontmatter.name_matches_folder", "frontmatter", 2, f"'{name}'"))
    else:
        checks.append(
            fail(
                "frontmatter.name_matches_folder",
                "frontmatter",
                2,
                f"name='{name}' but folder='{base.name}' (silent discovery failure)",
            )
        )

    if not description:
        checks.append(fail("frontmatter.description_present", "discoverability", 3, "empty"))
    elif len(description) > MAX_DESCRIPTION:
        checks.append(
            fail(
                "frontmatter.description_present",
                "discoverability",
                3,
                f"{len(description)} chars > {MAX_DESCRIPTION}",
            )
        )
    elif len(description) < MIN_DESCRIPTION:
        checks.append(
            warn(
                "frontmatter.description_present",
                "discoverability",
                3,
                f"only {len(description)} chars; too vague to trigger reliably",
            )
        )
    else:
        checks.append(
            ok("frontmatter.description_present", "discoverability", 3, f"{len(description)} chars")
        )

    lowered_description = description.lower()
    if any(token in lowered_description for token in ("use when", "use for", "trigger", "when asked")):
        checks.append(ok("frontmatter.description_triggers", "discoverability", 2, "trigger phrasing"))
    else:
        checks.append(
            warn(
                "frontmatter.description_triggers",
                "discoverability",
                2,
                "no 'use when'/'use for' trigger phrasing",
            )
        )

    if "argument-hint" in meta:
        checks.append(ok("frontmatter.argument_hint", "frontmatter", 1, "present"))
    else:
        checks.append(ok("frontmatter.argument_hint", "frontmatter", 1, "optional, not set"))

    # Size
    lines = len(text.splitlines())
    if lines > MAX_LINES:
        checks.append(fail("size.lines", "size", 3, f"{lines} lines > {MAX_LINES}"))
    elif lines > WARN_LINES:
        checks.append(warn("size.lines", "size", 3, f"{lines} lines > {WARN_LINES}"))
    else:
        checks.append(ok("size.lines", "size", 3, f"{lines} lines"))

    tokens = len(text) // 4
    if tokens > MAX_TOKENS:
        checks.append(fail("size.tokens_estimate", "size", 2, f"~{tokens} tokens > {MAX_TOKENS}"))
    elif tokens > WARN_TOKENS:
        checks.append(warn("size.tokens_estimate", "size", 2, f"~{tokens} tokens"))
    else:
        checks.append(ok("size.tokens_estimate", "size", 2, f"~{tokens} tokens"))

    # Structure
    found = headings(body)
    if len(body.strip()) < 200:
        checks.append(fail("structure.body", "structure", 3, "body shorter than 200 chars"))
    else:
        checks.append(ok("structure.body", "structure", 3, f"{len(body.strip())} chars"))

    if any(level == 1 for level, _ in found):
        checks.append(ok("structure.title", "structure", 2, "H1 present"))
    else:
        checks.append(warn("structure.title", "structure", 2, "no H1 title"))

    h2 = [title for level, title in found if level == 2]
    if len(h2) >= 2:
        checks.append(ok("structure.sections", "structure", 2, f"{len(h2)} H2 sections"))
    elif h2:
        checks.append(warn("structure.sections", "structure", 2, "only one H2 section"))
    else:
        checks.append(warn("structure.sections", "structure", 2, "no H2 sections"))

    if has_heading(found, PROCEDURE_HEADINGS):
        checks.append(ok("structure.procedure", "structure", 2, "procedure-like heading"))
    else:
        checks.append(warn("structure.procedure", "structure", 2, "no procedure/steps heading"))

    if has_heading(found, VALIDATION_HEADINGS):
        checks.append(ok("structure.validation", "structure", 2, "validation/completion section"))
    else:
        checks.append(warn("structure.validation", "structure", 2, "no completion/validation section"))

    if has_heading(found, GOTCHA_HEADINGS):
        checks.append(ok("structure.gotchas", "structure", 1, "gotchas/anti-patterns section"))
    else:
        checks.append(warn("structure.gotchas", "structure", 1, "no gotchas/edge-case section"))

    jumps = [
        f"{previous[0]}->{level}"
        for previous, (level, _) in pairwise(found)
        if level > previous[0] + 1
    ]
    if jumps:
        checks.append(warn("structure.heading_hierarchy", "structure", 1, f"jumps: {', '.join(jumps)}"))
    else:
        checks.append(ok("structure.heading_hierarchy", "structure", 1, "no skipped levels"))

    if len(set(h2)) == len(h2):
        checks.append(ok("structure.duplicate_headings", "structure", 1, "no duplicates"))
    else:
        checks.append(warn("structure.duplicate_headings", "structure", 1, "duplicate H2 headings"))

    fences = sum(1 for line in body.splitlines() if _is_fence(line))
    if fences % 2 == 0:
        checks.append(ok("structure.code_fences", "structure", 2, f"{fences} fences"))
    else:
        checks.append(fail("structure.code_fences", "structure", 2, f"{fences} fences (unbalanced)"))

    if fences > 0:
        checks.append(ok("structure.examples", "structure", 1, "includes a code block"))
    else:
        checks.append(warn("structure.examples", "structure", 1, "no code example"))

    # Links and assets
    links = resolve_links(body, base)
    missing = [target for target, resolved in links if not resolved.exists()]
    if missing:
        checks.append(
            fail("links.referenced_files_exist", "links", 3, f"missing: {', '.join(missing[:5])}")
        )
    elif links:
        checks.append(
            ok("links.referenced_files_exist", "links", 3, f"{len(links)} relative links resolve")
        )
    else:
        checks.append(ok("links.referenced_files_exist", "links", 3, "no relative links"))

    absolute = re.findall(r"`(/home/[^`]+|/Users/[^`]+|[A-Za-z]:\\[^`]+)`", body)
    if absolute:
        checks.append(
            warn("links.no_absolute_paths", "links", 1, f"absolute paths: {', '.join(absolute[:3])}")
        )
    else:
        checks.append(ok("links.no_absolute_paths", "links", 1, "no absolute local paths"))

    # Hygiene and security
    if PLACEHOLDERS.search(body):
        checks.append(warn("hygiene.no_placeholders", "hygiene", 2, "TODO/TBD/placeholder text"))
    else:
        checks.append(ok("hygiene.no_placeholders", "hygiene", 2, "no placeholder text"))

    findings: list[str] = []
    for path in scan_text_files(base):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{label} in {path.relative_to(base)}")
    if findings:
        checks.append(fail("security.no_secrets", "security", 4, "; ".join(findings)))
    else:
        checks.append(ok("security.no_secrets", "security", 4, "no credential patterns"))

    summary = {
        "path": str(base),
        "name": name,
        "description_chars": len(description),
        "lines": lines,
        "sections": [title for level, title in found if level == 2],
        "files": sorted(str(path.relative_to(base)) for path in iter_files(base)),
    }
    return checks, summary


def weighted_score(items: list[dict], key: str = "score") -> float:
    total_weight = sum(float(item["weight"]) for item in items)
    if not total_weight:
        return 0.0
    return round(sum(float(item[key]) * float(item["weight"]) for item in items) / total_weight, 1)


def load_judge(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dimensions = payload.get("dimensions", payload)
    if isinstance(dimensions, list):
        dimensions = {item["id"]: item for item in dimensions}
    if not isinstance(dimensions, dict):
        die("judge JSON needs a 'dimensions' object")
    missing = [name for name in JUDGE_DIMENSIONS if name not in dimensions]
    if missing:
        die(f"judge JSON is missing dimensions: {', '.join(missing)}")
    result = []
    for name in JUDGE_DIMENSIONS:
        item = dimensions[name]
        try:
            score = float(item["score"])
        except (TypeError, ValueError):
            die(f"dimension '{name}' score must be a number")
        if not 0 <= score <= 100:
            die(f"dimension '{name}' score must be 0-100")
        result.append(
            {
                "id": name,
                "score": score,
                "weight": float(item.get("weight", 1)),
                "evidence": str(item.get("evidence", "")),
                "justification": str(item.get("justification", "")),
            }
        )
    return result


def band(score: float) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 60:
        return "needs-work"
    return "poor"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate an agentic skill package.")
    parser.add_argument("skill", type=Path, help="skill directory or path to SKILL.md")
    parser.add_argument("--judge", type=Path, help="LLM-as-judge JSON to merge")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument("--fail-under", type=float, default=None, help="exit 1 below this total")
    args = parser.parse_args()

    base = skill_dir(args.skill)
    checks, summary = run_checks(base)
    deterministic = {
        "score": weighted_score([asdict(check) for check in checks]),
        "dimensions": [asdict(check) for check in checks],
    }

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "skill": summary,
        "deterministic": deterministic,
        "llm_judge": None,
        "total": None,
    }

    if args.judge:
        judge_dimensions = load_judge(args.judge)
        llm_judge = {
            "score": weighted_score(judge_dimensions),
            "dimensions": judge_dimensions,
        }
        total = round(
            deterministic["score"] * DIMENSION_WEIGHTS["deterministic"]
            + llm_judge["score"] * DIMENSION_WEIGHTS["llm_judge"],
            1,
        )
        report["llm_judge"] = llm_judge
        report["total"] = {
            "score": total,
            "band": band(total),
            "weights": DIMENSION_WEIGHTS,
        }
    else:
        report["total"] = {
            "score": deterministic["score"],
            "band": band(deterministic["score"]),
            "weights": {"deterministic": 1.0},
            "note": "deterministic only; pass --judge to include the LLM assessment",
        }

    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    failures = [check["id"] for check in deterministic["dimensions"] if check["status"] == "fail"]
    print(
        f"deterministic={deterministic['score']} total={report['total']['score']} "
        f"band={report['total']['band']} failures={len(failures)}",
        file=sys.stderr,
    )

    if args.fail_under is not None and report["total"]["score"] < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
