"""Tests for plugins/sdlc/.apm/skills/adr/scripts/check_adr.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "sdlc" / ".apm" / "skills" / "adr" / "scripts" / "check_adr.py"


def load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_adr = load_script(SCRIPT)
NO_REPLACEMENT = check_adr.NO_REPLACEMENT

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


def superseded_text(reference: str) -> str:
    return VALID.replace("status: accepted", "status: superseded").replace(
        "Reconsider when the demo grows a second consumer.", reference
    )


# The record from issue #13: the decided body links a file that a later
# decision deleted, and an amendment quotes the original line.
FROZEN_LINK = "config/environments.json"
DECIDED = VALID.replace(
    "- Reconsider when the demo grows a second consumer.",
    "- Account and region values stay in\n"
    f"  [`{FROZEN_LINK}`]({FROZEN_LINK}).\n"
    "- Reconsider when the demo grows a second consumer.",
)
AMENDMENT = """
## Amendment (2026-11-12)

Account and region values moved to `lib/stages.ts`.

```text
- Account and region values stay in
  [`config/environments.json`](config/environments.json).
```
"""


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
        assert "Fake" not in collected["real"]

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

    def test_superseded_requires_a_replacement(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Reconsider the demo later."))
        assert NO_REPLACEMENT in result["errors"]

    def test_a_body_date_is_not_a_replacement_reference(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Decided on 2026-11-08, after a long debate."))
        assert NO_REPLACEMENT in result["errors"]

    def test_template_issue_link_is_not_a_replacement(self, tmp_path: Path) -> None:
        # The skill requires an issue link in every ADR, so `#12` cannot stand in
        # for a replacement record.
        reference = "Deferred: follow-up - tracked in #12.\n- Related: #12."
        result = check(tmp_path, superseded_text(reference))
        assert NO_REPLACEMENT in result["errors"]

    def test_fenced_example_is_not_a_replacement(self, tmp_path: Path) -> None:
        text = VALID.replace("status: accepted", "status: superseded").replace(
            "- Reconsider when the demo grows a second consumer.",
            "```markdown\nSuperseded by ADR-0002.\n```",
        )
        result = check(tmp_path, text)
        assert NO_REPLACEMENT in result["errors"]

    def test_date_shaped_filename_is_not_a_replacement(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Archived as 2026-11-08.md."))
        assert NO_REPLACEMENT in result["errors"]

    def test_five_digit_reference_does_not_satisfy_the_rule(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Superseded by ADR-00021."))
        assert NO_REPLACEMENT in result["errors"]

    def test_self_reference_is_rejected(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Superseded by ADR-0001."))
        assert any("points at this ADR itself" in e for e in result["errors"])

    def test_missing_replacement_is_rejected(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Superseded by ADR-0099."))
        assert any("replacement ADR-0099 does not exist" in e for e in result["errors"])

    def test_duplicate_mentions_report_one_error(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Superseded by ADR-0099 (see ADR-0099)."))
        errors = [e for e in result["errors"] if "replacement ADR-0099" in e]
        assert len(errors) == 1

    @pytest.mark.parametrize("reference", ["- Related: ADR-0002.", "- Related: 0002-next.md."])
    def test_cross_link_alone_is_not_a_replacement(
        self, tmp_path: Path, reference: str
    ) -> None:
        # The template allows `Related: <other ADR>` in every ADR, so a cross-link
        # must not satisfy the supersession rule.
        write(tmp_path, name="0002-next.md")
        result = check(tmp_path, superseded_text(reference))
        assert NO_REPLACEMENT in result["errors"]

    def test_cross_link_is_not_reported_as_the_replacement(self, tmp_path: Path) -> None:
        write(tmp_path, name="0002-next.md")
        text = superseded_text("- Superseded by ADR-0002.\n- Related: ADR-0009.")
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_path_qualified_reference_is_resolved(self, tmp_path: Path) -> None:
        (tmp_path / "adr").mkdir()
        write(tmp_path, name="adr/0002-next.md")
        result = check(tmp_path, superseded_text("Superseded by adr/0002-next.md."))
        assert result["errors"] == []

    def test_missing_path_qualified_reference_is_rejected(self, tmp_path: Path) -> None:
        result = check(tmp_path, superseded_text("Superseded by adr/0002-next.md."))
        assert any("replacement ADR-0002 does not exist" in e for e in result["errors"])

    @pytest.mark.parametrize(
        "reference",
        [
            "Superseded by ADR-0002.",
            "Superseded by ADR 0002.",
            "Superseded by adr-0002.",
            "Superseded by 0002-next.md.",
        ],
    )
    def test_replacement_reference_forms_are_accepted(
        self, tmp_path: Path, reference: str
    ) -> None:
        write(tmp_path, name="0002-next.md")
        result = check(tmp_path, superseded_text(reference))
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

    def test_fenced_historical_link_is_not_checked(self, tmp_path: Path) -> None:
        # A later decision may delete a file a decided ADR links to; §5 says to
        # leave the decided text intact, so quoting it must not fail the check.
        text = VALID.replace(
            "Reconsider when the demo grows a second consumer.",
            "Amended by ADR-0002.\n\n```text\nSee [the guide](guide.md).\n```",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_inline_code_link_is_not_checked(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "Reconsider when the demo grows a second consumer.",
            "Amended by ADR-0002. Original text: `See [the guide](guide.md).`",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_prose_link_next_to_a_fence_is_still_checked(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- Reconsider when the demo grows a second consumer.",
            "```text\n[old](gone.md)\n```\n\nSee [the guide](guide.md).",
        )
        result = check(tmp_path, text)
        assert any("broken relative link: guide.md" in e for e in result["errors"])

    def test_indented_historical_link_is_not_checked(self, tmp_path: Path) -> None:
        # Quoting history with an indented block is as valid as a fence.
        text = VALID.replace(
            "- Reconsider when the demo grows a second consumer.",
            "Amended by ADR-0002.\n\n    See [the guide](guide.md).",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_indented_list_continuation_still_checks_its_links(
        self, tmp_path: Path
    ) -> None:
        # A four-space indent under a bullet is item content, not code.
        text = VALID.replace(
            "- Reconsider when the demo grows a second consumer.",
            "- See [the guide](guide.md):\n\n    The guide is short.",
        )
        result = check(tmp_path, text)
        assert any("broken relative link: guide.md" in e for e in result["errors"])

    def test_multiline_inline_code_link_is_not_checked(self, tmp_path: Path) -> None:
        text = VALID.replace(
            "- Reconsider when the demo grows a second consumer.",
            "Amended by ADR-0002. Original: `See [the guide](guide.md)\nin full.`",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_code_span_with_embedded_backticks_is_not_checked(
        self, tmp_path: Path
    ) -> None:
        text = VALID.replace(
            "- Reconsider when the demo grows a second consumer.",
            "Amended by ADR-0002. Original: ``a `tick`, [the guide](guide.md)``",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_a_fence_cannot_join_two_prose_fragments_into_a_link(
        self, tmp_path: Path
    ) -> None:
        # The blank line a fence leaves behind ends the paragraph, so the two
        # fragments never render as one link.
        text = VALID.replace(
            "- Reconsider when the demo grows a second consumer.",
            "See [the guide\n```text\n```\n](guide.md).",
        )
        result = check(tmp_path, text)
        assert result["errors"] == []

    def test_frozen_link_to_a_deleted_target_still_fails(self, tmp_path: Path) -> None:
        # Issue #13: quoting the original line fixes the double report but not
        # the frozen link, so the record needs a recorded fate as well.
        result = check(tmp_path, DECIDED + AMENDMENT)
        assert result["errors"] == [f"broken relative link: {FROZEN_LINK}"]

    def test_amendment_recording_where_the_target_moved_passes(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "stages.ts").write_text("export {}\n", encoding="utf-8")
        fate = f"\n- Moved: {FROZEN_LINK} -> lib/stages.ts\n"
        result = check(tmp_path, DECIDED + AMENDMENT + fate)
        assert result["errors"] == []

    def test_amendment_recording_a_removal_passes(self, tmp_path: Path) -> None:
        fate = f"\n- Removed: {FROZEN_LINK}\n"
        result = check(tmp_path, DECIDED + AMENDMENT + fate)
        assert result["errors"] == []

    def test_recorded_fate_must_name_an_existing_target(self, tmp_path: Path) -> None:
        fate = f"\n- Renamed: {FROZEN_LINK} \u2192 lib/gone.ts\n"
        result = check(tmp_path, DECIDED + AMENDMENT + fate)
        assert any("does not exist" in e and "lib/gone.ts" in e for e in result["errors"])

    def test_recorded_fate_outside_an_amendment_does_not_apply(
        self, tmp_path: Path
    ) -> None:
        # Only an amendment can explain a stale link; the decided text is frozen.
        text = DECIDED.replace(
            "- Reconsider when the demo grows a second consumer.",
            f"- Moved: {FROZEN_LINK} -> lib/stages.ts",
        )
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "stages.ts").write_text("export {}\n", encoding="utf-8")
        result = check(tmp_path, text)
        assert result["errors"] == [f"broken relative link: {FROZEN_LINK}"]

    def test_recorded_fate_only_covers_the_target_it_names(self, tmp_path: Path) -> None:
        fate = f"\n- Removed: {FROZEN_LINK}\n"
        result = check(tmp_path, DECIDED + AMENDMENT + fate + "\nAlso see [gs](gone.md).\n")
        assert result["errors"] == ["broken relative link: gone.md"]


class TestCodeMask:
    def test_masking_preserves_the_line_count(self) -> None:
        body = "Sentence.\n\n```text\n[a](b.md)\n```\n\nAfter.\n"
        assert len(check_adr.prose(body).splitlines()) == len(body.splitlines())

    def test_mask_blanks_fenced_and_indented_lines(self) -> None:
        body = "Prose.\n\n```\nfenced\n```\n\n    indented\n"
        masked = check_adr.mask_code(body)
        assert masked[0] == "Prose."
        assert masked[2] is None
        assert masked[6] is None

    def test_heading_inside_an_indented_block_is_not_a_section(self) -> None:
        body = "Prose.\n\n    ## Decision Drivers\n"
        headings, _ = check_adr.sections(body)
        assert headings == []


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
    def test_every_shipped_adr_conforms(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = ROOT / "docs" / "adr"
        if not directory.is_dir():
            pytest.skip("no ADRs in this repository")
        monkeypatch.setattr(sys, "argv", ["check_adr.py", str(directory)])
        assert check_adr.main() == 0
        capsys.readouterr()
