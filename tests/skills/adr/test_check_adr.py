"""Tests for plugins/sdlc/.apm/skills/adr/scripts/check_adr.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/sdlc/.apm/skills/adr/scripts"))

import check_adr  # noqa: E402

VALID = """\
---
status: accepted
date: 2026-11-08
decision-makers: maintainers
---

# Adopt the status quo for the demo

## Context and Problem Statement

The demo needs one mechanism so the choice stays reviewable.

## Decision Drivers

- The demo must run without extra services.

## Considered Options

- Status quo: no mechanism.

## Decision Outcome

Chosen option: "Status quo: no mechanism", because it needs no extra services.

### Consequences

- Good, because nothing new must run.
- Bad, because the demo must run without extra services being added.

### Confirmation

- A workflow step that fails when an extra service is started.

## Pros and Cons of the Options

### Status quo

- Good, because nothing new runs.
- Bad, because nothing improves.

## More Information

- Reconsider when the demo grows a second consumer.
"""


def write(tmp_path: Path, text: str = VALID, name: str = "0001-demo-decision.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def check(
    tmp_path: Path,
    text: str = VALID,
    name: str = "0001-demo-decision.md",
    numbers: dict[int, list[str]] | None = None,
) -> dict:
    return check_adr.check_file(write(tmp_path, text, name), numbers if numbers else {})


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["check_adr.py", *args])
    return check_adr.main()


class TestFrontmatter:
    def test_valid_adr_has_no_findings(self, tmp_path: Path) -> None:
        result = check(tmp_path)
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["status"] == "accepted"
        assert result["title"] == "Adopt the status quo for the demo"

    def test_missing_opening_delimiter(self) -> None:
        assert check_adr.split_frontmatter("no frontmatter")[2] == "missing opening '---'"

    def test_missing_closing_delimiter(self) -> None:
        assert check_adr.split_frontmatter("---\nstatus: accepted\n")[2] == (
            "missing closing '---'"
        )

    def test_invalid_yaml(self) -> None:
        assert "invalid YAML" in check_adr.split_frontmatter("---\nstatus: [oops\n---\nx")[2]

    def test_non_mapping_frontmatter(self) -> None:
        assert check_adr.split_frontmatter("---\n- a\n---\nx")[2] == (
            "frontmatter is not a mapping"
        )

    def test_unknown_status(self, tmp_path: Path) -> None:
        result = check(tmp_path, VALID.replace("status: accepted", "status: done"))
        assert any("status 'done' not in" in error for error in result["errors"])

    def test_non_iso_date(self, tmp_path: Path) -> None:
        result = check(tmp_path, VALID.replace("date: 2026-11-08", "date: 8 Nov 2026"))
        assert "frontmatter date missing or not ISO YYYY-MM-DD" in result["errors"]

    def test_empty_decision_makers(self, tmp_path: Path) -> None:
        result = check(tmp_path, VALID.replace("decision-makers: maintainers", "decision-makers:"))
        assert "frontmatter decision-makers is empty" in result["errors"]

    def test_filename_must_be_numbered_kebab_case(self, tmp_path: Path) -> None:
        result = check(tmp_path, name="demo.md")
        assert any("is not NNNN-kebab-case.md" in error for error in result["errors"])


class TestStructure:
    def test_sections_ignores_headings_inside_code_fences(self) -> None:
        headings, collected = check_adr.sections("## Real\n\nbody\n\n```\n## Fake\n```\n")
        assert [title for _, title in headings] == ["Real"]
        assert "fake" not in collected

    def test_missing_h1(self, tmp_path: Path) -> None:
        result = check(tmp_path, VALID.replace("# Adopt the status quo for the demo", "Preamble"))
        assert "no H1 title" in result["errors"]

    def test_question_title_is_only_a_warning(self, tmp_path: Path) -> None:
        result = check(tmp_path, VALID.replace("Adopt the status quo for the demo", "Which way?"))
        assert result["errors"] == []
        assert any("H1 is a question" in warning for warning in result["warnings"])

    def test_document_type_title_is_rejected(self, tmp_path: Path) -> None:
        result = check(tmp_path, VALID.replace("Adopt the status quo for the demo", "ADR"))
        assert "H1 must state the decision, not the document type" in result["errors"]

    def test_missing_required_section(self, tmp_path: Path) -> None:
        text = VALID.split("## More Information")[0]
        result = check(tmp_path, text)
        assert "missing section: more information" in result["errors"]

    def test_consequences_without_bad_entry_warns(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- Bad, because the demo must run without extra services being added.\n",
            "",
        )
        result = check(tmp_path, text)
        assert any("no 'Bad, because' entry" in warning for warning in result["warnings"])

    def test_drivers_must_be_a_list(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- The demo must run without extra services.",
            "The demo must run without extra services.",
        )
        result = check(tmp_path, text)
        assert "Decision Drivers has no bullet" in result["errors"]

    def test_driver_without_matching_consequence_warns(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- The demo must run without extra services.",
            "- Onboarding paperwork stays untouched.",
        )
        result = check(tmp_path, text)
        assert any("driver has no matching consequence" in w for w in result["warnings"])


class TestConfirmation:
    def test_empty_confirmation(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- A workflow step that fails when an extra service is started.\n",
            "",
        )
        result = check(tmp_path, text)
        assert "Confirmation is empty" in result["errors"]

    def test_prose_without_a_list_item_warns(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- A workflow step that fails when an extra service is started.",
            "A workflow step that fails when an extra service is started.",
        )
        result = check(tmp_path, text)
        assert any("no list item naming a check" in w for w in result["warnings"])

    def test_intent_phrasing_warns(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- A workflow step that fails when an extra service is started.",
            "- We will ensure that an extra service is never started.",
        )
        result = check(tmp_path, text)
        assert any("intent, not as a check" in w for w in result["warnings"])


class TestOptions:
    def test_options_must_be_a_list(self, tmp_path: Path) -> None:
        text = VALID.replace("- Status quo: no mechanism.", "Status quo: no mechanism.")
        result = check(tmp_path, text)
        assert "Considered Options has no list item" in result["errors"]

    def test_option_without_pros_and_cons_warns(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- Status quo: no mechanism.",
            "- Status quo: no mechanism.\n- A second mechanism: more moving parts.",
        )
        result = check(tmp_path, text)
        assert any("option has no Pros and Cons" in w for w in result["warnings"])

    def test_superseded_without_replacement_is_not_detected(self, tmp_path: Path) -> None:
        # known defect: the reference check greps the whole file for a bare
        # four-digit number, and the mandatory ISO `date:` always supplies one,
        # so the "no replacement referenced" branch can never fire. Pinned here
        # so fixing the check has to update this test.
        text = VALID.replace("status: accepted", "status: superseded")
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_superseded_with_a_replacement_passes(self, tmp_path: Path) -> None:
        text = VALID.replace("status: accepted", "status: superseded").replace(
            "Reconsider when the demo grows a second consumer.",
            "Superseded by ADR-0002.",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []


class TestLinks:
    def test_broken_relative_link(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "Reconsider when the demo grows a second consumer.",
            "See [the guide](guide.md).",
        )
        result = check(tmp_path, text)
        assert any("broken relative link: guide.md" in e for e in result["errors"])

    def test_resolving_relative_link_passes(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text("# guide\n", encoding="utf-8")
        text = VALID.replace(
            "Reconsider when the demo grows a second consumer.",
            "See [the guide](guide.md) and [the wiki](https://example.invalid/wiki).",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []


class TestNumbers:
    def test_numbering_warns_when_it_does_not_start_at_0001(self, tmp_path: Path) -> None:
        result = check(tmp_path, name="0002-demo-decision.md")
        assert any("numbering does not start at 0001" in w for w in result["warnings"])

    def test_duplicate_numbers_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        write(tmp_path, name="0001-one.md")
        write(tmp_path, name="0001-two.md")
        monkeypatch.setattr(sys, "argv", ["check_adr.py", str(tmp_path)])
        assert check_adr.main() == 1


class TestMain:
    def test_valid_directory_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(tmp_path)
        assert run(monkeypatch, str(tmp_path)) == 0
        assert "0 error(s)" in capsys.readouterr().out

    def test_json_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(tmp_path)
        assert run(monkeypatch, str(tmp_path), "--json") == 0
        report = json.loads(capsys.readouterr().out)
        assert report["summary"] == {"files": 1, "errors": 0, "warnings": 0, "latest": 1}
        assert report["adrs"][0]["title"] == "Adopt the status quo for the demo"

    def test_fail_on_warn_turns_warnings_into_failures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write(tmp_path, VALID.replace("Adopt the status quo for the demo", "Which way?"))
        assert run(monkeypatch, str(tmp_path)) == 0
        assert run(monkeypatch, str(tmp_path), "--fail-on-warn") == 1

    def test_missing_path_exits_two(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exit_info:
            run(monkeypatch, str(tmp_path / "absent"))
        assert exit_info.value.code == 2

    def test_directory_without_adrs_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "notes.md").write_text("not an ADR\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exit_info:
            run(monkeypatch, str(tmp_path))
        assert exit_info.value.code == 2


class TestRepositoryAdrs:
    def test_every_shipped_adr_conforms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = ROOT / "docs" / "adr"
        if not directory.is_dir():
            pytest.skip("no ADRs in this repository")
        monkeypatch.setattr(sys, "argv", ["check_adr.py", str(directory)])
        assert check_adr.main() == 0
