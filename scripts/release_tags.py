#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Derive and verify the release tags a marketplace publishes.

Consumers resolve a marketplace dependency's version range against git tags in
this repository. A marketplace JSON entry for a local package source
(``source: ./plugins/sdlc``) carries no tag pattern, so ``apm install`` falls
back to APM's legacy ``{name}--v{version}`` convention while the release
pipeline only created ``v{version}``. Every release therefore publishes both:

    v0.1.2          # release anchor: GitHub Release, tagPattern "v{version}"
    sdlc--v0.1.2    # per-package anchor: what ``apm install`` resolves

Usage:
    python3 scripts/release_tags.py --plan        # tags for the current version
    python3 scripts/release_tags.py --check       # both families agree
    python3 scripts/release_tags.py --version     # current manifest version
    python3 scripts/release_tags.py --backfill    # alias tags for old v* tags
    python3 scripts/release_tags.py --backfill --apply

Exit codes: 0 success, 1 mismatch, 2 invalid input.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "apm.yml"

# Keep in step with `marketplace.build.tagPattern` in apm.yml.
RELEASE_PREFIX = "v"
ALIAS_TEMPLATE = "{name}--v{version}"

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
# `name` is a git tag component: APM restricts it to this set, so the alias tag
# is safe by construction. Anything else is a manifest error, not something to
# sanitize silently.
TAG_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
RELEASE_TAG = re.compile(r"^v\d")


class ReleaseTagError(RuntimeError):
    """A manifest or repository state that cannot produce a consistent tag set."""


def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def load_manifest(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as error:
        raise ReleaseTagError(f"cannot read {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ReleaseTagError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(data, dict):
        raise ReleaseTagError(f"{path} is not a YAML mapping")
    return data


def manifest_version(manifest: dict) -> str:
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.match(version):
        raise ReleaseTagError(f"version {version!r} is not a semver string")
    return version


def package_entries(manifest: dict) -> list[dict]:
    marketplace = manifest.get("marketplace")
    if not isinstance(marketplace, dict):
        raise ReleaseTagError("no marketplace block in apm.yml")
    packages = marketplace.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ReleaseTagError("marketplace.packages is empty")
    entries = []
    for entry in packages:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ReleaseTagError("every marketplace package needs a string name")
        name = entry["name"]
        if not TAG_SAFE.match(name):
            raise ReleaseTagError(f"package name {name!r} is not a valid git tag component")
        if not isinstance(entry.get("source"), str):
            raise ReleaseTagError(f"package {name!r} has no source")
        entries.append(entry)
    names = [entry["name"] for entry in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ReleaseTagError(f"duplicate package names: {', '.join(duplicates)}")
    return entries


def package_version(root_version: str, entry: dict, manifest_path: Path) -> str:
    """Return the package's declared version, enforcing lockstep versioning.

    `apm pack --check-versions` is the authority in CI; this keeps the tag
    derivation from publishing an alias for a version the package never had.
    """
    version = entry.get("version", root_version)
    if version != root_version:
        raise ReleaseTagError(
            f"package {entry['name']!r} is {version} but the marketplace is "
            f"{root_version} ({manifest_path})"
        )
    return str(version)


def release_tag(version: str) -> str:
    return f"{RELEASE_PREFIX}{version}"


def alias_tag(name: str, version: str) -> str:
    return ALIAS_TEMPLATE.format(name=name, version=version)


def plan_tags(manifest: dict, manifest_path: Path = DEFAULT_MANIFEST) -> list[str]:
    """Tags for the current version, release anchor first."""
    version = manifest_version(manifest)
    tags = [release_tag(version)]
    for entry in package_entries(manifest):
        package_version(version, entry, manifest_path)
        tags.append(alias_tag(entry["name"], version))
    return tags


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ReleaseTagError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def resolve(ref: str, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def check_tags(tags: list[str], cwd: Path) -> list[str]:
    """Report every reason the published tag set cannot resolve a range."""
    if len(tags) < 2:
        return ["expected a release tag plus one alias tag per package"]
    release = resolve(tags[0], cwd)
    if release is None:
        return [f"release tag {tags[0]} does not exist"]
    errors = []
    for tag in tags[1:]:
        commit = resolve(tag, cwd)
        if commit is None:
            errors.append(f"alias tag {tag} does not exist")
        elif commit != release:
            errors.append(
                f"alias tag {tag} points at {commit[:7]}, "
                f"but {tags[0]} points at {release[:7]}"
            )
    return errors


def release_tags(cwd: Path) -> list[str]:
    out = git("tag", "--list", f"{RELEASE_PREFIX}[0-9]*", cwd=cwd)
    return sorted(line for line in out.splitlines() if RELEASE_TAG.match(line))


def packaged_manifest_path(entry: dict, manifest_path: Path) -> str:
    """Repo-relative path of a package's apm.yml for a local source."""
    source = entry["source"]
    if not source.startswith("./"):
        raise ReleaseTagError(
            f"package {entry['name']!r} uses a remote source; backfill only "
            "covers packages published from this repository"
        )
    return f"{source[2:].rstrip('/')}/apm.yml"


def backfill_plan(manifest: dict, manifest_path: Path, cwd: Path) -> list[tuple[str, str]]:
    """Alias tags missing for already-published release tags.

    Each alias points at the release tag's own commit, but only when the
    package's manifest at that tag declares the matching version - otherwise the
    tag would advertise a version the tree does not contain.
    """
    entries = package_entries(manifest)
    planned: list[tuple[str, str]] = []
    for tag in release_tags(cwd):
        version = tag[len(RELEASE_PREFIX) :]
        if not SEMVER.match(version):
            continue
        commit = resolve(tag, cwd)
        if commit is None:
            continue
        for entry in entries:
            alias = alias_tag(entry["name"], version)
            if resolve(alias, cwd) is not None:
                continue
            path = packaged_manifest_path(entry, manifest_path)
            try:
                text = git("show", f"{tag}:{path}", cwd=cwd)
                declared = manifest_version(yaml.safe_load(text))
            except (ReleaseTagError, yaml.YAMLError) as error:
                print(f"skip {alias}: {error}", file=sys.stderr)
                continue
            if declared != version:
                print(
                    f"skip {alias}: {tag} declares {declared}, not {version}",
                    file=sys.stderr,
                )
                continue
            planned.append((alias, commit))
    return planned


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="print the tags for this version")
    mode.add_argument("--check", action="store_true", help="verify the published tag set")
    mode.add_argument("--version", action="store_true", help="print the manifest version")
    mode.add_argument(
        "--backfill", action="store_true", help="list alias tags missing for old releases"
    )
    parser.add_argument(
        "--apply", action="store_true", help="create planned backfill tags locally"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.version:
            print(manifest_version(manifest))
            return 0
        if args.plan:
            for tag in plan_tags(manifest, args.manifest):
                print(tag)
            return 0
        if args.check:
            errors = check_tags(plan_tags(manifest, args.manifest), args.repo)
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1 if errors else 0
        planned = backfill_plan(manifest, args.manifest, args.repo)
        if not planned:
            print("no missing alias tags")
            return 0
        for alias, commit in planned:
            if args.apply:
                git("tag", alias, commit, cwd=args.repo)
                print(f"created {alias} at {commit[:7]} (push with: git push origin {alias})")
            else:
                print(f"git tag {alias} {commit[:7]}")
        return 0
    except ReleaseTagError as error:
        die(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
