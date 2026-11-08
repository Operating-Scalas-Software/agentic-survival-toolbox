"""Tests for plugins/sdlc/.apm/skills/meta-evaluate-skill/scripts/evaluate_skill.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/sdlc/.apm/skills/meta-evaluate-skill/scripts"))

import evaluate_skill as evaluate  # noqa: E402

DESCRIPTION = (
    "Use when a test needs a well-formed skill package with every deterministic check passing."
)

GOOD_BODY = """\
# Demo skill

A skill used by the tests to exercise every deterministic check. The body is
deliberately long so it clears the two hundred character threshold that the
structure check applies before scoring the content of a skill package.

## Procedure

1. Read the bundled details.

## Validation

- [ ] The details file is present.

## Gotchas

- None worth naming.

```bash
echo demo
```

See [the details](details.md).
"""


def skill_text(
    name: str = "demo-skill", description: str = DESCRIPTION, body: str = GOOD_BODY
) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


def make_skill(
    tmp_path: Path,
    *,
    name: str = "demo-skill",
    description: str = DESCRIPTION,
    body: str = GOOD_BODY,
    files: dict[str, str] | None = None,
) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    (directory / "SKILL.md").write_text(skill_text(name, description, body), encoding="utf-8")
    bundled = files if files is not None else {"details.md": "# details\n"}
    for filename, content in bundled.items():
        path = directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return directory


def statuses(directory: Path) -> dict[str, str]:
    checks, _ = evaluate.run_checks(directory)
    return {check.id: check.status for check in checks}


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["evaluate_skill.py", *args])
    return evaluate.main()


def judge_payload(score: float = 90.0) -> dict:
    return {
        "dimensions": {
            name: {"score": score, "evidence": "checked", "justification": "consistent"}
            for name in evaluate.JUDGE_DIMENSIONS
        }
    }


class TestSkillDir:
    def test_accepts_a_directory_with_skill_md(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path)
        assert evaluate.skill_dir(directory) == directory.resolve()

    def test_accepts_a_path_to_skill_md(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path)
        assert evaluate.skill_dir(directory / "SKILL.md") == directory.resolve()

    def test_rejects_anything_else(self, tmp_path: Path) -> None:
        missing = tmp_path / "not-a-skill"
        missing.mkdir()
        with pytest.raises(SystemExit) as exit_info:
            evaluate.skill_dir(missing)
        assert exit_info.value.code == 2


class TestFrontmatter:
    def test_valid_frontmatter(self) -> None:
        meta, body, error = evaluate.split_frontmatter(skill_text())
        assert error is None
        assert meta == {"name": "demo-skill", "description": DESCRIPTION}
        assert body.lstrip().startswith("# Demo skill")

    def test_missing_opening_delimiter(self) -> None:
        assert evaluate.split_frontmatter("# body")[2] == "missing opening '---'"

    def test_missing_closing_delimiter(self) -> None:
        assert evaluate.split_frontmatter("---\nname: x\n")[2] == "missing closing '---'"

    def test_invalid_yaml(self) -> None:
        assert "invalid YAML" in evaluate.split_frontmatter("---\nname: [oops\n---\nx")[2]

    def test_non_mapping_frontmatter(self) -> None:
        assert evaluate.split_frontmatter("---\n- a\n---\nx")[2] == (
            "frontmatter is not a mapping"
        )


class TestHeadings:
    def test_ignores_headings_inside_code_fences(self) -> None:
        body = "## Real\n\n```bash\n## Fake\n```\n\n## Also real\n"
        assert [title for _, title in evaluate.headings(body)] == ["real", "also real"]


class TestRunChecks:
    def test_good_skill_has_no_failing_checks(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path)
        checks, summary = evaluate.run_checks(directory)
        assert [check.id for check in checks if check.status == "fail"] == []
        assert summary["name"] == "demo-skill"
        assert summary["files"] == ["SKILL.md", "details.md"]
        assert summary["lines"] > 20

    def test_name_must_match_the_folder(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path)
        (directory / "SKILL.md").write_text(
            skill_text(name="other-skill"), encoding="utf-8"
        )
        assert statuses(directory)["frontmatter.name_matches_folder"] == "fail"

    def test_invalid_name(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path, name="Demo_Skill")
        found = statuses(directory)
        assert found["frontmatter.name_valid"] == "fail"
        assert found["frontmatter.name_matches_folder"] == "pass"

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path)
        (directory / "SKILL.md").write_text(GOOD_BODY, encoding="utf-8")
        found = statuses(directory)
        assert found["frontmatter.valid"] == "fail"
        assert found["frontmatter.name_valid"] == "fail"
        assert found["frontmatter.description_present"] == "fail"

    def test_short_description_only_warns(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path, description="Use when testing.")
        assert statuses(directory)["frontmatter.description_present"] == "warn"

    def test_description_without_trigger_phrasing_warns(self, tmp_path: Path) -> None:
        description = "A well-formed skill package with every deterministic check passing."
        directory = make_skill(tmp_path, description=description)
        assert statuses(directory)["frontmatter.description_triggers"] == "warn"

    def test_short_body_fails(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path, body="# Demo\n\ntoo short\n")
        assert statuses(directory)["structure.body"] == "fail"

    def test_missing_h1_warns(self, tmp_path: Path) -> None:
        body = GOOD_BODY.replace("# Demo skill\n", "")
        directory = make_skill(tmp_path, body=body)
        assert statuses(directory)["structure.title"] == "warn"

    def test_unbalanced_code_fence_fails(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path, body=GOOD_BODY.replace("```\n\nSee", "\n\nSee"))
        assert statuses(directory)["structure.code_fences"] == "fail"

    def test_missing_link_target_fails(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path, files={})
        assert statuses(directory)["links.referenced_files_exist"] == "fail"

    def test_absolute_path_warns(self, tmp_path: Path) -> None:
        body = GOOD_BODY.replace("See [the details](details.md).", "Run `/home/user/tool`.")
        directory = make_skill(tmp_path, body=body)
        assert statuses(directory)["links.no_absolute_paths"] == "warn"

    def test_placeholder_warns(self, tmp_path: Path) -> None:
        body = GOOD_BODY + "\nTODO: finish this section.\n"
        directory = make_skill(tmp_path, body=body)
        assert statuses(directory)["hygiene.no_placeholders"] == "warn"

    def test_secret_in_a_bundled_file_fails(self, tmp_path: Path) -> None:
        fake_key = "AKIA" + "A" * 16
        directory = make_skill(tmp_path, files={"details.md": f"key={fake_key}\n"})
        found = statuses(directory)
        assert found["security.no_secrets"] == "fail"

    def test_ignored_directories_are_not_scanned(self, tmp_path: Path) -> None:
        directory = make_skill(tmp_path, files={"__pycache__/cached.md": "TODO: nothing\n"})
        assert statuses(directory)["hygiene.no_placeholders"] == "pass"


class TestScoring:
    def test_weighted_score_of_nothing_is_zero(self) -> None:
        assert evaluate.weighted_score([]) == 0.0

    def test_weighted_score_uses_weights(self) -> None:
        items = [{"weight": 3, "score": 100}, {"weight": 1, "score": 0}]
        assert evaluate.weighted_score(items) == 75.0

    @pytest.mark.parametrize(
        ("score", "expected"),
        [(100, "excellent"), (90, "excellent"), (89.9, "good"), (75, "good"),
         (74.9, "needs-work"), (60, "needs-work"), (59.9, "poor")],
    )
    def test_band_boundaries(self, score: float, expected: str) -> None:
        assert evaluate.band(score) == expected


class TestLoadJudge:
    def test_accepts_a_dimensions_object(self, tmp_path: Path) -> None:
        path = tmp_path / "judge.json"
        path.write_text(json.dumps(judge_payload(80)), encoding="utf-8")
        dimensions = evaluate.load_judge(path)
        assert [item["id"] for item in dimensions] == list(evaluate.JUDGE_DIMENSIONS)
        assert dimensions[0]["score"] == 80.0
        assert dimensions[0]["weight"] == 1.0

    def test_accepts_a_dimensions_list(self, tmp_path: Path) -> None:
        items = [{"id": name, "score": 70} for name in evaluate.JUDGE_DIMENSIONS]
        path = tmp_path / "judge.json"
        path.write_text(json.dumps({"dimensions": items}), encoding="utf-8")
        assert evaluate.load_judge(path)[0]["score"] == 70.0

    def test_missing_dimension_exits_two(self, tmp_path: Path) -> None:
        payload = judge_payload()
        del payload["dimensions"]["clarity"]
        path = tmp_path / "judge.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit) as exit_info:
            evaluate.load_judge(path)
        assert exit_info.value.code == 2

    def test_non_numeric_score_exits_two(self, tmp_path: Path) -> None:
        payload = judge_payload()
        payload["dimensions"]["clarity"]["score"] = "high"
        path = tmp_path / "judge.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit) as exit_info:
            evaluate.load_judge(path)
        assert exit_info.value.code == 2

    def test_out_of_range_score_exits_two(self, tmp_path: Path) -> None:
        payload = judge_payload()
        payload["dimensions"]["clarity"]["score"] = 101
        path = tmp_path / "judge.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit) as exit_info:
            evaluate.load_judge(path)
        assert exit_info.value.code == 2

    def test_non_mapping_dimensions_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "judge.json"
        path.write_text(json.dumps({"dimensions": "nope"}), encoding="utf-8")
        with pytest.raises(SystemExit) as exit_info:
            evaluate.load_judge(path)
        assert exit_info.value.code == 2


class TestMain:
    def test_deterministic_only_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = make_skill(tmp_path)
        assert run(monkeypatch, str(directory)) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["llm_judge"] is None
        assert report["total"]["weights"] == {"deterministic": 1.0}
        assert report["total"]["score"] == report["deterministic"]["score"]

    def test_judge_report_is_written_and_weighted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = make_skill(tmp_path)
        judge = tmp_path / "judge.json"
        judge.write_text(json.dumps(judge_payload(100)), encoding="utf-8")
        output = tmp_path / "report.json"

        assert run(monkeypatch, str(directory), "--judge", str(judge), "--output", str(output)) == 0

        report = json.loads(output.read_text(encoding="utf-8"))
        expected = round(report["deterministic"]["score"] * 0.4 + 100 * 0.6, 1)
        assert report["total"]["score"] == expected
        assert report["total"]["band"] == "excellent"
        assert report["llm_judge"]["score"] == 100.0

    def test_fail_under_returns_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        directory = make_skill(tmp_path, body="# Demo\n\nshort body only\n")
        assert run(monkeypatch, str(directory), "--fail-under", "99") == 1
        capsys.readouterr()

    def test_invalid_skill_path_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(SystemExit) as exit_info:
            run(monkeypatch, str(tmp_path / "absent"))
        assert exit_info.value.code == 2


class TestRepositorySkills:
    def test_every_shipped_skill_passes(self) -> None:
        skills = sorted(ROOT.glob("plugins/*/.apm/skills/*"))
        if not skills:
            pytest.skip("no skills in this repository")
        for directory in skills:
            checks, summary = evaluate.run_checks(directory)
            assert [check.id for check in checks if check.status == "fail"] == [], directory
            assert summary["name"] == directory.name, directory
