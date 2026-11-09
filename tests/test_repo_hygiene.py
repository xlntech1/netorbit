"""Files that can hold secrets or personal setup must never be committable.

Claude Code saves "don't ask again" approvals word for word in .claude/settings.local.json,
and CLAUDE.local.md is where CLAUDE.md tells people to keep their own paths and hosts.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MUST_IGNORE = [
    ".claude/settings.local.json",
    ".claude/settings.json",
    "CLAUDE.local.md",
    "custom_components/netorbit/CLAUDE.local.md",
]
MUST_NOT_IGNORE = ["CLAUDE.md"]


def _ignored(path: str) -> bool:
    # --no-index checks the rules even for paths that don't exist. Turning off the global excludes
    # file and requiring the match to come from .gitignore ignores anything set up on one machine only.
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=/dev/null", "check-ignore", "--no-index", "-v", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.startswith(".gitignore:")


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
@pytest.mark.parametrize("path", MUST_IGNORE)
def test_local_claude_files_are_ignored(path: str) -> None:
    assert _ignored(path), f"{path} must be ignored by .gitignore"


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
@pytest.mark.parametrize("path", MUST_NOT_IGNORE)
def test_shared_claude_md_is_allowed(path: str) -> None:
    assert not _ignored(path), f"{path} is shared project guidance and must stay committable"
