"""Tests for scripts/runner_image_watch.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import runner_image_watch as watch  # noqa: E402


def release(tag: str, *, prerelease: bool = False, draft: bool = False) -> dict:
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft}


WORKFLOW = """\
name: Validate

jobs:
  validate:
    runs-on: ubuntu-26.04
    steps:
      - run: echo hi

  tests:
    runs-on: ubuntu-26.04
    steps:
      - run: echo hi

  other:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


class TestPinnedVersions:
    def test_reads_versioned_ubuntu_labels(self) -> None:
        assert watch.pinned_versions([WORKFLOW]) == {(26, 4)}

    def test_ignores_latest_and_non_ubuntu_runners(self) -> None:
        text = "runs-on: ubuntu-latest\nruns-on: macos-15\nruns-on: win25\n"
        assert watch.pinned_versions([text]) == set()

    def test_collects_multiple_workflows(self) -> None:
        texts = ["runs-on: ubuntu-24.04", "runs-on: 'ubuntu-26.04'"]
        assert watch.pinned_versions(texts) == {(24, 4), (26, 4)}


class TestAvailableVersions:
    def test_maps_stable_tags_to_lts_versions(self) -> None:
        releases = [release("ubuntu26/20261101.186"), release("ubuntu24/20261101.360")]
        assert watch.available_versions(releases) == {(26, 4), (24, 4)}

    def test_ignores_prereleases_and_drafts(self) -> None:
        releases = [release("ubuntu27/20270101.1", prerelease=True), release("ubuntu27/20270101.2", draft=True)]
        assert watch.available_versions(releases) == set()

    def test_ignores_arm64_slim_and_other_images(self) -> None:
        releases = [
            release("ubuntu26-arm64/20261101.174"),
            release("ubuntu-slim/20261101.43"),
            release("macos-15-arm64/20261104.0514"),
        ]
        assert watch.available_versions(releases) == {(26, 4)}


class TestFindChange:
    def test_no_change_when_pin_is_newest(self) -> None:
        assert watch.find_change({(26, 4)}, {(22, 4), (24, 4), (26, 4)}) is None

    def test_upgrade_when_newer_image_is_published(self) -> None:
        finding = watch.find_change({(24, 4)}, {(24, 4), (26, 4)})
        assert finding == watch.Finding(kind="upgrade", current=(24, 4), target=(26, 4))

    def test_upgrade_beats_retirement_of_a_different_pin(self) -> None:
        finding = watch.find_change({(22, 4), (24, 4)}, {(26, 4)})
        assert finding is not None
        assert finding.kind == "upgrade"
        assert finding.target == (26, 4)

    def test_retired_when_pin_disappears(self) -> None:
        finding = watch.find_change({(26, 4)}, {(22, 4), (24, 4)})
        assert finding == watch.Finding(kind="retired", current=(26, 4), target=None)

    def test_ignores_empty_pin_set(self) -> None:
        assert watch.find_change(set(), {(26, 4)}) is None


class TestRender:
    def test_upgrade_issue_names_both_labels(self) -> None:
        finding = watch.Finding(kind="upgrade", current=(26, 4), target=(27, 4))
        title, body = watch.render(finding, {(26, 4)})
        assert "ubuntu-27.04" in title
        assert "ubuntu-26.04" in body
        assert "ubuntu-27.04" in body

    def test_retired_issue_flags_the_pin(self) -> None:
        finding = watch.Finding(kind="retired", current=(26, 4), target=None)
        title, body = watch.render(finding, {(26, 4)})
        assert "ubuntu-26.04" in title
        assert "ubuntu-26.04" in body


class TestMain:
    def _workflows(self, tmp_path: Path, text: str = WORKFLOW) -> Path:
        directory = tmp_path / ".github" / "workflows"
        directory.mkdir(parents=True)
        (directory / "validate.yml").write_text(text, encoding="utf-8")
        return directory

    def test_up_to_date_exits_quietly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        directory = self._workflows(tmp_path)
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")])
        monkeypatch.setattr(watch, "create_issue", lambda *args: pytest.fail("should not open an issue"))

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert "up to date" in capsys.readouterr().out

    def test_dry_run_prints_without_creating(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        directory = self._workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")])
        monkeypatch.setattr(watch, "create_issue", lambda *args: pytest.fail("should not open an issue"))

        assert watch.main(["--workflows-dir", str(directory), "--dry-run"]) == 0
        output = capsys.readouterr().out
        assert "ubuntu-26.04" in output
        assert "ubuntu-24.04" in output

    def test_skips_when_issue_already_open(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        directory = self._workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "token")
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")])
        monkeypatch.setattr(watch, "find_open_issue", lambda *args: True)
        monkeypatch.setattr(watch, "create_issue", lambda *args: pytest.fail("should not open an issue"))

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert "already tracks" in capsys.readouterr().out

    def test_creates_issue_once_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        directory = self._workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        created: list[tuple[str, str]] = []

        def fake_create(repo: str, title: str, body: str, api_url: str, token: str) -> str:
            created.append((title, body))
            return "https://example.invalid/issues/1"

        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "token")
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")])
        monkeypatch.setattr(watch, "find_open_issue", lambda *args: False)
        monkeypatch.setattr(watch, "create_issue", fake_create)

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert len(created) == 1
        assert "ubuntu-26.04" in created[0][0]

    def test_no_pinned_labels_is_not_an_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = self._workflows(tmp_path, "runs-on: ubuntu-latest\n")
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [])

        assert watch.main(["--workflows-dir", str(directory)]) == 0

    def test_requires_token_outside_dry_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = self._workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")])

        with pytest.raises(SystemExit):
            watch.main(["--workflows-dir", str(directory)])


class TestRepoWorkflows:
    def test_repo_workflows_pin_a_versioned_label(self) -> None:
        pinned = watch.load_pinned(ROOT / ".github" / "workflows")
        assert pinned, "workflows should pin an explicit ubuntu-XX.YY label"
