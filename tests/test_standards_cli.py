"""CLI integration tests for standards discovery, fail-fast policy, and --standards-dir option."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ttassistant.cli import app

runner = CliRunner()


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


def test_cli_help_shows_standards_dir_option():
    """Verify ttassistant --help displays the --standards-dir option."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--standards-dir" in result.output
    assert "-s" in result.output


def test_cli_subprocess_help_shows_standards_dir_option():
    """Verify subprocess invocation of ttassistant --help displays --standards-dir."""
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "--standards-dir" in proc.stdout


def test_cli_missing_standards_dir_fails_fast(tmp_path):
    """Verify running in a directory without common_standards exits code 1 with helpful message."""
    isolated_dir = tmp_path / "empty_workspace"
    isolated_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant"],
        cwd=str(isolated_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Corporate standards directory 'common_standards/' not found" in proc.stderr
    assert "Details: Please pull corporate standards" in proc.stderr
    assert "Traceback (most recent call last)" not in proc.stderr


def test_cli_explicit_missing_standards_dir_fails_fast(tmp_path):
    """Verify pointing --standards-dir to non-existent path exits code 1 with path error."""
    bad_path = tmp_path / "non_existent_standards"
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--standards-dir", str(bad_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Specified standards directory does not exist" in proc.stderr
    assert str(bad_path) in proc.stderr.replace("\n", "")
    assert "Traceback (most recent call last)" not in proc.stderr


def test_cli_empty_standards_dir_fails_fast(tmp_path):
    """Verify pointing --standards-dir to an empty directory exits code 1."""
    empty_dir = tmp_path / "empty_standards"
    empty_dir.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--standards-dir", str(empty_dir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "is empty" in proc.stderr
    assert "Traceback (most recent call last)" not in proc.stderr


def test_cli_malformed_standards_fails_fast(tmp_path):
    """Verify malformed Markdown table exits code 1 with diagnostic error message."""
    bad_dir = tmp_path / "bad_standards"
    bad_dir.mkdir()
    (bad_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | invalid_int |\n"
    )
    (bad_dir / "tagging_baseline.md").write_text("# Tags")
    (bad_dir / "backend_mapping.md").write_text("# Backend")

    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--standards-dir", str(bad_dir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "invalid integer for 'Max Length'" in proc.stderr or "Pydantic schema validation error" in proc.stderr
    assert "Traceback (most recent call last)" not in proc.stderr


def test_cli_debug_flag_shows_traceback_on_standards_error(tmp_path):
    """Verify --debug flag prints full traceback on standards error."""
    isolated_dir = tmp_path / "isolated"
    isolated_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--debug"],
        cwd=str(isolated_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Traceback (most recent call last)" in proc.stderr
    assert "MissingStandardsError" in proc.stderr


def test_cli_envvar_tt_standards_dir_override(tmp_path):
    """Verify TT_STANDARDS_DIR environment variable is respected."""
    custom_standards = tmp_path / "custom_standards"
    custom_standards.mkdir()
    (custom_standards / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_storage_account | ^st[a-z0-9]+$ | Lowercase | 24 |\n"
    )
    (custom_standards / "tagging_baseline.md").write_text(
        "| Tag Key | Required |\n|---|---|\n| Env | Yes |\n"
    )
    (custom_standards / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| sub1 | st1 |\n"
    )

    env = dict(os.environ, TT_STANDARDS_DIR=str(custom_standards))
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0


def test_cli_dynamic_updates_reflected_without_rebuild(tmp_path):
    """Verify modifications to standards files are dynamically reflected without binary rebuilds."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()

    naming_file = standards_dir / "naming_conventions.md"
    tagging_file = standards_dir / "tagging_baseline.md"
    backend_file = standards_dir / "backend_mapping.md"

    naming_file.write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n"
    )
    tagging_file.write_text(
        "| Tag Key | Required |\n|---|---|\n| Environment | Yes |\n"
    )
    backend_file.write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )

    # First run succeeds
    proc1 = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--standards-dir", str(standards_dir)],
        capture_output=True,
        text=True,
    )
    assert proc1.returncode == 0

    # User modifies standards to introduce an error
    naming_file.write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | NOT_AN_INT |\n"
    )

    # Next CLI invocation immediately detects the error
    proc2 = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--standards-dir", str(standards_dir)],
        capture_output=True,
        text=True,
    )
    assert proc2.returncode == 1
    assert "invalid integer for 'Max Length'" in proc2.stderr


def test_cli_upward_ancestor_standards_discovery(tmp_path):
    """Verify CLI running in a nested subdirectory finds common_standards/ in an ancestor directory."""
    root_dir = tmp_path / "project_root"
    root_dir.mkdir()
    standards_dir = root_dir / "common_standards"
    standards_dir.mkdir()

    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "| Tag Key | Required |\n|---|---|\n| Environment | Yes |\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )

    nested_sub = root_dir / "terraform" / "subscriptions" / "workload"
    nested_sub.mkdir(parents=True)

    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant"],
        cwd=str(nested_sub),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Enterprise terminal CLI copilot" in proc.stdout
