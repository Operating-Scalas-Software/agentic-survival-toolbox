#!/usr/bin/env python3
"""Report when a newer Ubuntu runner image is published.

Dependabot tracks the action pins in ``.github/workflows`` but not the
``runs-on:`` labels, so the runner image a job executes on can drift out of
date with no pull request to review. This script compares the Ubuntu versions
pinned in the workflows with the stable Ubuntu images published by
``actions/runner-images`` and opens a single tracking issue when a newer image
exists (or when the pinned one stops being published).

Standard library only: the workflow runs it straight from a checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_API = "https://api.github.com"
RELEASES_PATH = "/repos/actions/runner-images/releases"
API_VERSION = "2022-11-28"
MAX_PAGES = 5

# `runs-on: ubuntu-26.04` (optionally quoted). Runner labels are always LTS,
# hence the `.04` suffix; the monthly number is kept for readability only.
LABEL_PATTERN = re.compile(r"runs-on:\s*['\"]?ubuntu-(\d{2})\.(\d{2})")

# Stable image releases are tagged `ubuntu26/20261101.186` (plus `-arm64` and
# `ubuntu-slim` variants). Only the Ubuntu release number matters here.
TAG_PATTERN = re.compile(r"^ubuntu(\d{2})(?:-arm64)?/")


@dataclass(frozen=True)
class Finding:
    """A runner-image change worth reporting."""

    kind: str  # "upgrade" | "retired"
    current: tuple[int, int] | None
    target: tuple[int, int] | None


def ubuntu_label(version: tuple[int, int]) -> str:
    """Render ``(26, 4)`` as the runner label ``ubuntu-26.04``."""
    return f"ubuntu-{version[0]}.{version[1]:02d}"


def pinned_versions(texts: Iterable[str]) -> set[tuple[int, int]]:
    """Extract every pinned Ubuntu runner version from workflow sources."""
    versions = set()
    for text in texts:
        for major, minor in LABEL_PATTERN.findall(text):
            versions.add((int(major), int(minor)))
    return versions


def available_versions(releases: Iterable[dict]) -> set[tuple[int, int]]:
    """Ubuntu versions with at least one published stable image."""
    versions = set()
    for release in releases:
        if release.get("prerelease") or release.get("draft"):
            continue
        match = TAG_PATTERN.match(release.get("tag_name") or "")
        if match:
            versions.add((int(match.group(1)), 4))
    return versions


def find_change(
    pinned: set[tuple[int, int]], available: set[tuple[int, int]]
) -> Finding | None:
    """Decide what, if anything, deserves an issue.

    A newer published image wins over a retired pin: both are fixed by the same
    bump, and the bump is the actionable one.
    """
    if not pinned:
        return None

    newest_pin = min(pinned)
    newer = sorted(version for version in available if version > newest_pin)
    if newer:
        return Finding(kind="upgrade", current=newest_pin, target=newer[-1])

    missing = sorted(version for version in pinned if version not in available)
    if missing:
        return Finding(kind="retired", current=missing[0], target=None)

    return None


def render(finding: Finding, pinned: set[tuple[int, int]]) -> tuple[str, str]:
    """Build the issue title and body for a finding."""
    pins = ", ".join(f"`{ubuntu_label(version)}`" for version in sorted(pinned))

    if finding.kind == "upgrade":
        assert finding.target is not None and finding.current is not None
        title = f"ci: newer Ubuntu runner image available ({ubuntu_label(finding.target)})"
        body = f"""## Summary

`actions/runner-images` publishes a stable Ubuntu image newer than the one the
workflows pin. Dependabot does not track `runs-on:`, so this needs a manual bump.

| | Label |
| --- | --- |
| pinned | {pins} |
| available | `{ubuntu_label(finding.target)}` |

## Checklist

- [ ] Bump `runs-on:` in `.github/workflows/*.yml` to `{ubuntu_label(finding.target)}`
- [ ] Confirm the `validate` workflow is green on the branch
- [ ] Note any image deltas that touch the jobs (removed SDKs, changed defaults)
- [ ] Close this issue once the bump is merged
"""
        return title, body

    assert finding.current is not None
    label = ubuntu_label(finding.current)
    title = f"ci: {label} runner image is no longer published"
    body = f"""## Summary

`actions/runner-images` publishes no stable image for `{label}`, which the
workflows still pin. Jobs may fail once the image is retired, so this is
time-sensitive.

Current pins: {pins}

## Checklist

- [ ] Check the retirement notice for `{label}`
- [ ] Bump `runs-on:` in `.github/workflows/*.yml` to a published label
- [ ] Confirm the `validate` workflow is green on the branch
- [ ] Close this issue once the bump is merged
"""
    return title, body


def load_pinned(workflows_dir: Path) -> set[tuple[int, int]]:
    """Read every workflow in ``workflows_dir`` and collect pinned versions."""
    return pinned_versions(
        path.read_text(encoding="utf-8") for path in sorted(workflows_dir.glob("*.yml"))
    )


def _request(
    url: str,
    token: str | None,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", API_VERSION)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_releases(api_url: str, token: str | None) -> list[dict]:
    """Page through the runner-images release feed."""
    releases: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        batch = _request(f"{api_url}{RELEASES_PATH}?per_page=100&page={page}", token)
        if not isinstance(batch, list):
            break
        releases.extend(batch)
        if len(batch) < 100:
            break
    return releases


def find_open_issue(repo: str, title: str, api_url: str, token: str | None) -> bool:
    """True when an open issue already carries this exact title."""
    issues = _request(f"{api_url}/repos/{repo}/issues?state=open&per_page=100", token)
    if not isinstance(issues, list):
        return False
    return any(issue.get("title") == title for issue in issues)


def create_issue(repo: str, title: str, body: str, api_url: str, token: str) -> str:
    """Open the tracking issue and return its URL."""
    issue = _request(
        f"{api_url}/repos/{repo}/issues",
        token,
        method="POST",
        payload={"title": title, "body": body},
    )
    if not isinstance(issue, dict):
        raise RuntimeError("unexpected response while creating the issue")
    return issue["html_url"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=Path(".github/workflows"),
        help="directory holding the workflow files (default: .github/workflows)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the finding instead of opening an issue",
    )
    args = parser.parse_args(argv)

    api_url = os.environ.get("GITHUB_API_URL") or DEFAULT_API
    repo = os.environ.get("GITHUB_REPOSITORY") or ""
    token = os.environ.get("GITHUB_TOKEN") or None

    pinned = load_pinned(args.workflows_dir)
    if not pinned:
        print(f"no pinned ubuntu runner labels under {args.workflows_dir}")
        return 0

    available = available_versions(fetch_releases(api_url, token))
    finding = find_change(pinned, available)
    if finding is None:
        current = ", ".join(ubuntu_label(version) for version in sorted(pinned))
        print(f"up to date: {current}")
        return 0

    title, body = render(finding, pinned)
    print(title)
    if args.dry_run:
        print(body)
        return 0

    if not repo or not token:
        raise SystemExit("GITHUB_REPOSITORY and GITHUB_TOKEN are required without --dry-run")
    if find_open_issue(repo, title, api_url, token):
        print("an open issue already tracks this change")
        return 0

    print(f"opened {create_issue(repo, title, body, api_url, token)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
