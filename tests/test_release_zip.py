"""The release zip settings and the workflow that builds the zip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.netorbit.const import CARD_FILENAME

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "netorbit"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _steps() -> list[dict]:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["zip"]["steps"]


def _index(steps: list[dict], text: str) -> int:
    """Return the position of the only step whose run command contains text."""
    found = [i for i, step in enumerate(steps) if text in step.get("run", "")]
    assert len(found) == 1, text
    return found[0]


def test_hacs_json_uses_the_release_zip() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "netorbit.zip"
    assert {"name", "homeassistant", "render_readme"} <= hacs.keys()


def test_zip_sources_are_where_the_integration_expects_them() -> None:
    assert (INTEGRATION / "manifest.json").is_file()
    assert (INTEGRATION / "__init__.py").is_file()
    assert (INTEGRATION / "frontend" / CARD_FILENAME).is_file()


def test_workflow_runs_on_published_releases() -> None:
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 reads the bare key on as True.
    assert workflow[True]["release"]["types"] == ["published"]


def test_workflow_checks_the_version_first_and_the_asset_last() -> None:
    steps = _steps()
    version = _index(steps, "GITHUB_REF_NAME}")
    build = _index(steps, "zip -r ../../netorbit.zip")
    root_check = _index(steps, "unzip -Z1 netorbit.zip")
    upload = _index(steps, "gh release upload")
    verify = _index(steps, "gh release view")
    assert version < build < root_check < upload < verify
    assert "--clobber" in steps[upload]["run"]
    assert "grep -Fxq netorbit.zip" in steps[verify]["run"]


def test_workflow_is_safe_with_tag_text() -> None:
    steps = _steps()
    assert not any("${{" in step.get("run", "") for step in steps)
    for step in steps:
        if "gh release" in step.get("run", ""):
            assert step["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
            assert '--repo "$GITHUB_REPOSITORY"' in step["run"]
