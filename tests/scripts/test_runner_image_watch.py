"""Tests for scripts/runner_image_watch.py."""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import runner_image_watch as watch  # noqa: E402

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def release(
    tag: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    published_at: str | None = None,
) -> dict:
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "published_at": published_at,
    }


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


def write_workflows(tmp_path: Path, text: str = WORKFLOW) -> Path:
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "validate.yml").write_text(text, encoding="utf-8")
    return directory


def batch(count: int, *, tag: str, published_at: str) -> list[dict]:
    """A full page of releases for one image, all sharing a publication date."""
    return [
        release(f"{tag}/20261101.{index}", published_at=published_at)
        for index in range(count)
    ]


class FakeUrlopen:
    """Stands in for ``urllib.request.urlopen`` and records every request."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        payload = self.responses.pop(0) if self.responses else {}
        return io.BytesIO(json.dumps(payload).encode("utf-8"))


class TestPinnedVersions:
    def test_reads_versioned_ubuntu_labels(self) -> None:
        assert watch.pinned_versions([WORKFLOW]) == {(26, 4)}

    def test_ignores_latest_and_non_ubuntu_runners(self) -> None:
        text = "runs-on: ubuntu-latest\nruns-on: macos-15\nruns-on: win25\n"
        assert watch.pinned_versions([text]) == set()

    def test_collects_multiple_workflows(self) -> None:
        texts = ["runs-on: ubuntu-24.04", "runs-on: 'ubuntu-26.04'"]
        assert watch.pinned_versions(texts) == {(24, 4), (26, 4)}

    def test_ignores_commented_out_labels(self) -> None:
        text = "# runs-on: ubuntu-24.04\nruns-on: ubuntu-26.04\n"
        assert watch.pinned_versions([text]) == {(26, 4)}

    def test_ignores_non_lts_ubuntu_labels(self) -> None:
        assert watch.pinned_versions(["runs-on: ubuntu-26.10"]) == set()


class TestAvailableVersions:
    def test_maps_stable_tags_to_lts_versions(self) -> None:
        releases = [release("ubuntu26/20261101.186"), release("ubuntu24/20261101.360")]
        assert watch.available_versions(releases) == {(26, 4), (24, 4)}

    def test_ignores_prereleases_and_drafts(self) -> None:
        releases = [
            release("ubuntu27/20270101.1", prerelease=True),
            release("ubuntu27/20270101.2", draft=True),
        ]
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

    def test_upgrade_compares_against_the_newest_pin(self) -> None:
        finding = watch.find_change({(22, 4), (24, 4)}, {(26, 4)})
        assert finding is not None
        assert finding.kind == "upgrade"
        assert finding.current == (24, 4)

    def test_mixed_pins_do_not_target_a_label_already_in_use(self) -> None:
        available = {(22, 4), (24, 4), (26, 4)}
        assert watch.find_change({(22, 4), (26, 4)}, available) is None

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

    def test_unknown_kind_raises_instead_of_rendering_retired(self) -> None:
        finding = watch.Finding(kind="upgrad", current=(26, 4), target=None)
        with pytest.raises(ValueError):
            watch.render(finding, {(26, 4)})


class TestHttp:
    def test_request_sends_a_json_content_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeUrlopen({"ok": True})
        monkeypatch.setattr(urllib.request, "urlopen", fake)

        watch._request("https://api.test/x", "t", method="POST", payload={"a": 1})

        request = fake.requests[0]
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data) == {"a": 1}

    def test_request_omits_the_content_type_without_a_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeUrlopen({"ok": True})
        monkeypatch.setattr(urllib.request, "urlopen", fake)

        watch._request("https://api.test/x", "t")

        assert fake.requests[0].get_header("Content-type") is None

    def test_create_issue_posts_and_returns_the_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeUrlopen({"html_url": "https://example.invalid/issues/1"})
        monkeypatch.setattr(urllib.request, "urlopen", fake)

        url = watch.create_issue("owner/repo", "title", "body", "https://api.test", "t")

        assert url == "https://example.invalid/issues/1"
        assert fake.requests[0].full_url == "https://api.test/repos/owner/repo/issues"
        assert json.loads(fake.requests[0].data)["title"] == "title"

    def test_create_issue_rejects_an_unexpected_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", FakeUrlopen(["not", "an", "issue"]))

        with pytest.raises(RuntimeError):
            watch.create_issue("owner/repo", "title", "body", "https://api.test", "t")

    def test_fetch_releases_stops_when_the_feed_is_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        page = [release("ubuntu26/20261101.186", published_at="2026-11-01T00:00:00Z")]
        fake = FakeUrlopen(page)
        monkeypatch.setattr(urllib.request, "urlopen", fake)

        assert len(watch.fetch_releases("https://api.test", None, now=NOW)) == 1
        assert len(fake.requests) == 1

    def test_fetch_releases_pages_until_the_window_is_covered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recent = batch(100, tag="ubuntu26", published_at="2026-10-01T00:00:00Z")
        old = batch(100, tag="ubuntu24", published_at="2024-10-01T00:00:00Z")
        fake = FakeUrlopen(recent, old)
        monkeypatch.setattr(urllib.request, "urlopen", fake)

        releases = watch.fetch_releases("https://api.test", None, now=NOW)

        assert len(releases) == 200
        assert len(fake.requests) == 2

    def test_find_open_issue_requires_an_exact_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeUrlopen({"total_count": 1, "items": [{"title": "something else"}]})
        monkeypatch.setattr(urllib.request, "urlopen", fake)

        assert watch.find_open_issue("owner/repo", "exact title", "https://api.test", "t") is False
        assert "/search/issues" in fake.requests[0].full_url


class TestMain:
    def test_up_to_date_exits_quietly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        directory = write_workflows(tmp_path)
        monkeypatch.setattr(
            watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")]
        )
        monkeypatch.setattr(watch, "create_issue", lambda *args: pytest.fail("no issue expected"))

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert "up to date" in capsys.readouterr().out

    def test_dry_run_prints_without_creating(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        directory = write_workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        monkeypatch.setattr(
            watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")]
        )
        monkeypatch.setattr(watch, "create_issue", lambda *args: pytest.fail("no issue expected"))

        assert watch.main(["--workflows-dir", str(directory), "--dry-run"]) == 0
        output = capsys.readouterr().out
        assert "ubuntu-26.04" in output
        assert "ubuntu-24.04" in output

    def test_skips_when_an_issue_already_tracks_the_change(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        directory = write_workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "token")
        monkeypatch.setattr(
            watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")]
        )
        monkeypatch.setattr(watch, "find_open_issue", lambda *args: True)
        monkeypatch.setattr(watch, "create_issue", lambda *args: pytest.fail("no issue expected"))

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert "already tracks" in capsys.readouterr().out

    def test_creates_the_issue_once_when_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        directory = write_workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        created: list[tuple[str, str]] = []

        def fake_create(repo: str, title: str, body: str, api_url: str, token: str) -> str:
            created.append((title, body))
            return "https://example.invalid/issues/1"

        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "token")
        monkeypatch.setattr(
            watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")]
        )
        monkeypatch.setattr(watch, "find_open_issue", lambda *args: False)
        monkeypatch.setattr(watch, "create_issue", fake_create)

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert len(created) == 1
        assert "ubuntu-26.04" in created[0][0]

    def test_no_pinned_labels_is_not_an_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        directory = write_workflows(tmp_path, "runs-on: ubuntu-latest\n")
        monkeypatch.setattr(watch, "fetch_releases", lambda api, token: [])

        assert watch.main(["--workflows-dir", str(directory)]) == 0
        assert "no pinned ubuntu runner labels" in capsys.readouterr().out

    def test_misconfigured_run_prints_no_headline(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        directory = write_workflows(tmp_path, "runs-on: ubuntu-24.04\n")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(
            watch, "fetch_releases", lambda api, token: [release("ubuntu26/20261101.186")]
        )

        with pytest.raises(SystemExit):
            watch.main(["--workflows-dir", str(directory)])
        assert capsys.readouterr().out == ""


class TestRepoWorkflows:
    def test_repo_workflows_pin_a_single_versioned_label(self) -> None:
        pinned = watch.load_pinned(ROOT / ".github" / "workflows")
        assert len(pinned) == 1, f"workflows disagree on the runner image: {sorted(pinned)}"
