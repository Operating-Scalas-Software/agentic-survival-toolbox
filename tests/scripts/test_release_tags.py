"""Tests for scripts/release_tags.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import release_tags as rt  # noqa: E402


def manifest(version: str = "0.1.2", packages: list[dict] | None = None) -> dict:
    entries = packages or [
        {"name": "sdlc", "source": "./plugins/sdlc", "version": version},
    ]
    return {
        "name": "example-marketplace",
        "version": version,
        "marketplace": {"packages": entries},
    }


def write_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "noreply@localhost")
    git(tmp_path, "config", "user.name", "release-tags test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def release(repo: Path, version: str) -> str:
    """Commit a release that declares ``version`` and return its commit SHA."""
    write_manifest(repo / "apm.yml", manifest(version))
    write_manifest(repo / "plugins" / "sdlc" / "apm.yml", {"name": "sdlc", "version": version})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"release {version}")
    return rt.git("rev-parse", "HEAD", cwd=repo)


def tag(repo: Path, name: str, commit: str) -> None:
    git(repo, "tag", name, commit)


def test_plan_tags_returns_release_then_alias() -> None:
    assert rt.plan_tags(manifest()) == ["v0.1.2", "sdlc--v0.1.2"]


def test_plan_tags_covers_every_package_in_registration_order() -> None:
    packages = [
        {"name": "sdlc", "source": "./plugins/sdlc", "version": "0.1.2"},
        {"name": "review", "source": "./plugins/review", "version": "0.1.2"},
    ]
    assert rt.plan_tags(manifest(packages=packages)) == [
        "v0.1.2",
        "sdlc--v0.1.2",
        "review--v0.1.2",
    ]


def test_lockstep_mismatch_is_an_error() -> None:
    packages = [{"name": "sdlc", "source": "./plugins/sdlc", "version": "0.1.1"}]
    with pytest.raises(rt.ReleaseTagError, match="lockstep|0.1.1"):
        rt.plan_tags(manifest(version="0.1.2", packages=packages))


def test_non_semver_version_is_an_error() -> None:
    with pytest.raises(rt.ReleaseTagError, match="semver"):
        rt.plan_tags(manifest(version="v0.1.2"))


def test_package_name_must_be_tag_safe() -> None:
    packages = [{"name": "bad name", "source": "./plugins/bad", "version": "0.1.2"}]
    with pytest.raises(rt.ReleaseTagError, match="git tag component"):
        rt.plan_tags(manifest(packages=packages))


def test_duplicate_package_names_are_rejected() -> None:
    packages = [
        {"name": "sdlc", "source": "./plugins/sdlc", "version": "0.1.2"},
        {"name": "sdlc", "source": "./plugins/other", "version": "0.1.2"},
    ]
    with pytest.raises(rt.ReleaseTagError, match="duplicate"):
        rt.plan_tags(manifest(packages=packages))


def test_check_passes_when_both_families_share_a_commit(repo: Path) -> None:
    sha = release(repo, "0.1.2")
    tag(repo, "v0.1.2", sha)
    tag(repo, "sdlc--v0.1.2", sha)

    assert rt.check_tags(["v0.1.2", "sdlc--v0.1.2"], repo) == []


def test_check_reports_a_missing_alias_tag(repo: Path) -> None:
    sha = release(repo, "0.1.2")
    tag(repo, "v0.1.2", sha)

    errors = rt.check_tags(["v0.1.2", "sdlc--v0.1.2"], repo)

    assert errors == ["alias tag sdlc--v0.1.2 does not exist"]


def test_check_reports_a_diverged_alias_tag(repo: Path) -> None:
    first = release(repo, "0.1.1")
    second = release(repo, "0.1.2")
    tag(repo, "v0.1.2", second)
    tag(repo, "sdlc--v0.1.2", first)

    errors = rt.check_tags(["v0.1.2", "sdlc--v0.1.2"], repo)

    assert len(errors) == 1
    assert "points at" in errors[0]


def test_check_reports_a_missing_release_tag(repo: Path) -> None:
    assert rt.check_tags(["v9.9.9", "sdlc--v9.9.9"], repo) == [
        "release tag v9.9.9 does not exist"
    ]


def test_backfill_plans_every_published_release(repo: Path) -> None:
    old = release(repo, "0.1.0")
    new = release(repo, "0.1.1")
    tag(repo, "v0.1.0", old)
    tag(repo, "v0.1.1", new)
    write_manifest(repo / "apm.yml", manifest("0.1.1"))

    planned = rt.backfill_plan(rt.load_manifest(repo / "apm.yml"), repo / "apm.yml", repo)

    assert planned == [("sdlc--v0.1.0", old), ("sdlc--v0.1.1", new)]


def test_backfill_skips_tags_whose_tree_declares_another_version(repo: Path) -> None:
    sha = release(repo, "0.1.0")
    tag(repo, "v0.2.0", sha)
    write_manifest(repo / "apm.yml", manifest("0.1.0"))

    planned = rt.backfill_plan(rt.load_manifest(repo / "apm.yml"), repo / "apm.yml", repo)

    assert planned == []


def test_backfill_ignores_tags_that_already_exist(repo: Path) -> None:
    sha = release(repo, "0.1.0")
    tag(repo, "v0.1.0", sha)
    tag(repo, "sdlc--v0.1.0", sha)
    write_manifest(repo / "apm.yml", manifest("0.1.0"))

    planned = rt.backfill_plan(rt.load_manifest(repo / "apm.yml"), repo / "apm.yml", repo)

    assert planned == []


def test_apply_creates_tags_that_then_pass_check(repo: Path) -> None:
    old = release(repo, "0.1.0")
    new = release(repo, "0.1.1")
    tag(repo, "v0.1.0", old)
    tag(repo, "v0.1.1", new)

    planned = rt.backfill_plan(manifest("0.1.1"), repo / "apm.yml", repo)
    for alias, commit in planned:
        tag(repo, alias, commit)

    assert rt.check_tags(["v0.1.1", "sdlc--v0.1.1"], repo) == []
    assert rt.resolve("sdlc--v0.1.0", repo) == old


def test_backfill_rejects_remote_package_sources(repo: Path) -> None:
    sha = release(repo, "0.1.1")
    tag(repo, "v0.1.1", sha)
    packages = [
        {"name": "sdlc", "source": "example-org/example-repo/plugins/sdlc", "version": "0.1.1"}
    ]

    with pytest.raises(rt.ReleaseTagError, match="remote source"):
        rt.backfill_plan(manifest("0.1.1", packages), repo / "apm.yml", repo)


def test_cli_plan_prints_tags(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_manifest(repo / "apm.yml", manifest("0.1.2"))

    assert rt.main(["--manifest", str(repo / "apm.yml"), "--repo", str(repo), "--plan"]) == 0
    assert capsys.readouterr().out.split() == ["v0.1.2", "sdlc--v0.1.2"]


def test_cli_check_exits_nonzero_on_mismatch(repo: Path) -> None:
    sha = release(repo, "0.1.2")
    tag(repo, "v0.1.2", sha)

    assert rt.main(["--manifest", str(repo / "apm.yml"), "--repo", str(repo), "--check"]) == 1
