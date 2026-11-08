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


def test_prerelease_version_is_rejected() -> None:
    # APM's range matcher has not been shown to resolve a prerelease alias, so a
    # version outside plain X.Y.Z must fail rather than publish an uninstallable tag.
    with pytest.raises(rt.ReleaseTagError, match="plain X.Y.Z"):
        rt.plan_tags(manifest(version="0.1.2-rc1"))


def test_tag_pattern_mismatch_is_an_error() -> None:
    data = manifest()
    data["marketplace"]["build"] = {"tagPattern": "release-{version}"}

    with pytest.raises(rt.ReleaseTagError, match="tagPattern"):
        rt.plan_tags(data)


def test_missing_tag_pattern_uses_the_apm_default() -> None:
    assert rt.plan_tags(manifest()) == ["v0.1.2", "sdlc--v0.1.2"]


def test_manifest_version_rejects_a_non_mapping() -> None:
    with pytest.raises(rt.ReleaseTagError, match="not a YAML mapping"):
        rt.manifest_version(["not", "a", "mapping"])  # type: ignore[arg-type]


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


def test_cli_backfill_apply_creates_the_tags(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = release(repo, "0.1.0")
    new = release(repo, "0.1.1")
    tag(repo, "v0.1.0", old)
    tag(repo, "v0.1.1", new)

    argv = ["--manifest", str(repo / "apm.yml"), "--repo", str(repo), "--backfill", "--apply"]

    assert rt.main(argv) == 0
    assert rt.resolve("sdlc--v0.1.0", repo) == old
    assert rt.resolve("sdlc--v0.1.1", repo) == new
    assert rt.check_tags(["v0.1.1", "sdlc--v0.1.1"], repo) == []
    assert "git push origin sdlc--v0.1.0" in capsys.readouterr().out


def test_cli_version_prints_the_manifest_version(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_manifest(repo / "apm.yml", manifest("0.1.2"))

    assert rt.main(["--manifest", str(repo / "apm.yml"), "--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.2"


def test_cli_sources_prints_name_and_path(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_manifest(repo / "apm.yml", manifest("0.1.2"))

    assert rt.main(["--manifest", str(repo / "apm.yml"), "--sources"]) == 0
    assert capsys.readouterr().out.strip() == "sdlc\tplugins/sdlc"


def test_cli_check_uses_the_manifest_directory_by_default(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = release(repo, "0.1.2")
    tag(repo, "v0.1.2", sha)
    tag(repo, "sdlc--v0.1.2", sha)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert rt.main(["--manifest", str(repo / "apm.yml"), "--check"]) == 0


def test_cli_rejects_apply_without_backfill(repo: Path) -> None:
    write_manifest(repo / "apm.yml", manifest("0.1.2"))

    with pytest.raises(SystemExit) as exit_info:
        rt.main(["--manifest", str(repo / "apm.yml"), "--plan", "--apply"])

    assert exit_info.value.code == 2


def test_cli_invalid_manifest_exits_two(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text("- not a mapping\n")

    with pytest.raises(SystemExit) as exit_info:
        rt.main(["--manifest", str(bad), "--plan"])

    assert exit_info.value.code == 2


def test_backfill_skips_a_tag_whose_package_manifest_is_unreadable(repo: Path) -> None:
    write_manifest(repo / "apm.yml", manifest("0.1.0"))
    (repo / "plugins" / "sdlc").mkdir(parents=True, exist_ok=True)
    (repo / "plugins" / "sdlc" / "apm.yml").write_text("- not-a-mapping\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "unreadable package manifest")
    tag(repo, "v0.1.0", rt.git("rev-parse", "HEAD", cwd=repo))

    planned = rt.backfill_plan(rt.load_manifest(repo / "apm.yml"), repo / "apm.yml", repo)

    assert planned == []


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
