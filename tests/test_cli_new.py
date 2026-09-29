"""CLI integration tests for ttassistant new command."""

import os
import re
import subprocess
import sys
from pathlib import Path
import pytest
from typer.testing import CliRunner

from ttassistant.cli import app

runner = CliRunner()
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


@pytest.fixture(autouse=True)
def cleanup_generated_dirs():
    """Ensure no test artifacts remain in workspace before or after test execution."""
    import shutil

    shutil.rmtree("azurerm_storage_account", ignore_errors=True)
    yield
    shutil.rmtree("azurerm_storage_account", ignore_errors=True)


def test_cli_new_help_shows_all_options():
    """Verify ttassistant new --help displays all parameter options."""
    result = runner.invoke(app, ["new", "--help"])
    assert result.exit_code == 0
    assert "--subscription" in result.output
    assert "-sub" in result.output
    assert "--resource-type" in result.output
    assert "-r" in result.output
    assert "--workload" in result.output
    assert "-w" in result.output
    assert "--env" in result.output
    assert "-e" in result.output
    assert "--public-network-access" in result.output
    assert "--yes" in result.output
    assert "-y" in result.output


def test_cli_new_subprocess_help():
    """Verify subprocess invocation of ttassistant new --help succeeds."""
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "new", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "--subscription" in proc.stdout
    assert "--resource-type" in proc.stdout
    assert "--workload" in proc.stdout
    assert "--public-network-access" in proc.stdout
    assert "--yes" in proc.stdout


def test_cli_new_pre_populated_flags_runner():
    """Verify CliRunner with pre-populated valid flags succeeds and outputs diff preview and confirmation."""
    result = runner.invoke(
        app,
        [
            "new",
            "--subscription",
            "sub-prod",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "appdata",
        ],
        input="3\ny\n",
    )
    assert result.exit_code == 0
    assert "Provisioning parameters collected successfully" in result.output
    assert "sub-prod" in result.output
    assert "azurerm_storage_account" in result.output
    assert "stappdataprod" in result.output
    assert "Environment=prod" in result.output
    assert "Staged workspace generated in memory: azurerm_storage_account/sub-prod/" in result.output
    assert "main.tf" in result.output
    assert "data.tf" in result.output
    assert "backend.tf" in result.output
    assert "--- /dev/null" in result.output
    assert "azurerm_storage_account/sub-prod/main.tf" in result.output
    assert "Commit changes to disk?" in result.output
    assert "Committed 3 files atomically to disk" in result.output


def test_cli_new_subprocess_happy_path():
    """Verify external invocation of ttassistant new with --yes flag succeeds and writes files to disk."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "sub-prod",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "validname",
            "--yes",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Provisioning parameters collected successfully." in proc.stdout
    assert "stvalidnameprod" in proc.stdout
    assert "sub-prod" in proc.stdout
    assert "Staged workspace generated in memory: azurerm_storage_account/sub-prod/" in proc.stdout
    assert "main.tf" in proc.stdout
    assert "data.tf" in proc.stdout
    assert "backend.tf" in proc.stdout
    assert "--- /dev/null" in proc.stdout
    assert "azurerm_storage_account/sub-prod/main.tf" in proc.stdout
    assert "Committed 3 files atomically to disk" in proc.stdout
    assert Path("azurerm_storage_account/sub-prod/main.tf").is_file()
    assert Path("azurerm_storage_account/sub-prod/data.tf").is_file()
    assert Path("azurerm_storage_account/sub-prod/backend.tf").is_file()



def test_cli_new_invalid_workload_flag_exits_code_2():
    """Verify providing invalid workload flag exits with code 2 and validation error."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "sub-prod",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "App-Data!",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Invalid name: must match ^[a-z0-9]+$" in proc.stderr or "Invalid name: must match ^[a-z0-9]+$" in proc.stdout


def test_cli_new_workload_length_flag_exits_code_2():
    """Verify providing workload exceeding max length exits with code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "sub-prod",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "abcdefghijklmnopqrstuvwxyz1234",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Name exceeds maximum length of 24 characters" in proc.stderr or "Name exceeds maximum length of 24 characters" in proc.stdout


def test_cli_new_unknown_resource_type_flag_exits_code_2():
    """Verify providing unknown resource type flag exits with code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "sub-prod",
            "--resource-type",
            "nonexistent_resource",
            "--workload",
            "validname",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Unknown resource type" in proc.stderr or "Unknown resource type" in proc.stdout


def test_cli_new_piped_non_tty_dialogue():
    """Verify interactive prompts work with piped non-interactive stdin including [Y] confirmation."""
    # Choice 5: Other (Enter custom...)
    # Enter custom sub: sub-prod
    # Choice 2: azurerm_storage_account
    # Enter workload: appdata
    # Choice 3: Skip network configuration
    # Confirmation: y
    input_stream = "5\nsub-prod\n2\nappdata\n3\ny\n"
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "new"],
        input=input_stream,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Provisioning parameters collected successfully." in proc.stdout
    assert "stappdataprod" in proc.stdout
    assert "--- /dev/null" in proc.stdout
    assert "Commit changes to disk?" in proc.stdout
    assert "Committed 3 files atomically to disk" in proc.stdout


def test_cli_new_piped_non_tty_validation_recovery():
    """Verify non-TTY prompt reprompts and recovers after invalid input line."""
    # Invalid workload App-Data! followed by valid appdata, then skip network (3), then y confirmation
    input_stream = "5\nsub-prod\n2\nApp-Data!\nappdata\n3\ny\n"
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "new"],
        input=input_stream,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Invalid name: must match ^[a-z0-9]+$" in proc.stderr or "Invalid name: must match ^[a-z0-9]+$" in proc.stdout
    assert "Provisioning parameters collected successfully." in proc.stdout
    assert "stappdataprod" in proc.stdout
    assert "Committed 3 files atomically to disk" in proc.stdout


def test_cli_new_piped_non_tty_cancel_does_not_write_to_disk():
    """Verify selecting [N] during confirmation gate exits 0 and does not write files to disk."""
    input_stream = "5\nsub-prod\n2\nappdata\n3\nn\n"
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "new"],
        input=input_stream,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Scaffolding cancelled. No files written to disk." in proc.stdout
    assert not Path("azurerm_storage_account").exists()


def test_cli_new_confirmation_eof_aborts_130_without_files():
    """Verify EOF or abort during confirmation prompt exits 130 and leaves directory untouched."""
    # Sub, resource type, workload entered, skip network entered, but EOF on confirmation prompt
    input_stream = "5\nsub-prod\n2\nappdata\n3\n"
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "new"],
        input=input_stream,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 130
    assert "Aborted." in proc.stdout or "Aborted." in proc.stderr
    assert not Path("azurerm_storage_account").exists()


def test_cli_new_piped_non_tty_eof_aborts_130():
    """Verify non-TTY unexpected EOF exits with code 130 and 'Aborted.'."""
    input_stream = "5\nsub-prod\n2\n"  # EOF before entering workload
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "new"],
        input=input_stream,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 130
    assert "Aborted." in proc.stdout or "Aborted." in proc.stderr


def test_cli_new_explicit_env_flag_override():
    """Verify explicit --env / -e flag overrides environment derived from subscription."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "workload-dev",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "appdata",
            "-e",
            "prod",
            "--yes",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "stappdataprod" in proc.stdout
    assert "Environment=prod" in proc.stdout


def test_cli_new_invalid_env_flag_exits_code_2():
    """Verify supplying invalid --env flag exits with code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "workload-dev",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "appdata",
            "--env",
            "invalid_env",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Invalid environment" in proc.stderr or "Invalid environment" in proc.stdout


def test_cli_new_invalid_subscription_flag_exits_code_2():
    """Verify supplying invalid characters in --subscription flag exits with code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "--subscription",
            "bad sub!@#",
            "--resource-type",
            "azurerm_storage_account",
            "--workload",
            "appdata",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Subscription name" in proc.stderr or "Subscription name" in proc.stdout


def test_cli_new_filesystem_error_exits_code_1():
    """Verify disk write or I/O failure during commit raises FileSystemError and exits with code 1."""
    cmd = [
        sys.executable,
        "-c",
        (
            "from unittest.mock import patch\n"
            "from ttassistant.domain.exceptions import FileSystemError\n"
            "from ttassistant.cli import app\n"
            "with patch('ttassistant.adapters.fs_adapter.DiskFileSystemAdapter.commit_workspace') as mock_commit:\n"
            "    mock_commit.side_effect = FileSystemError('Disk write failure: permission denied')\n"
            "    app()\n"
        ),
        "new",
        "--subscription",
        "sub-prod",
        "--resource-type",
        "azurerm_storage_account",
        "--workload",
        "appdata",
        "--yes",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 1
    assert "Disk write failure: permission denied" in proc.stderr


def test_cli_new_never_invokes_terraform_apply_or_external_binaries():
    """Verify ttassistant new never invokes external terraform apply or terraform binary."""
    from unittest.mock import patch

    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen, patch("os.system") as mock_system:
        result = runner.invoke(
            app,
            [
                "new",
                "--subscription",
                "sub-prod",
                "--resource-type",
                "azurerm_storage_account",
                "--workload",
                "appdata",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert mock_run.call_count == 0
        assert mock_popen.call_count == 0
        assert mock_system.call_count == 0


def test_cli_new_interactive_tweak_refinement_committed_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify selecting [T] at the confirmation gate in non-TTY mode applies the tweak and commits it."""
    standards_dir = str(Path(__file__).parent.parent / "common_standards")
    monkeypatch.chdir(tmp_path)
    # Choices:
    # 5 -> Other (Enter custom sub)
    # sub-prod
    # 2 -> azurerm_storage_account
    # appdata
    # 3 -> Skip network configuration
    # t -> Tweak
    # Change replication to GRS
    # y -> Commit
    input_stream = "5\nsub-prod\n2\nappdata\n3\nt\nChange replication to GRS\ny\n"
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--standards-dir", standards_dir, "new"],
        input=input_stream,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Applied refinement: Set 'account_replication_type' = GRS" in proc.stdout
    assert "Committed 3 files atomically to disk" in proc.stdout
    main_tf = tmp_path / "azurerm_storage_account" / "sub-prod" / "main.tf"
    assert main_tf.is_file()
    assert re.search(r'account_replication_type\s*=\s*"GRS"', main_tf.read_text())

