"""CLI integration tests for ttassistant."""

import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from ttassistant import __version__
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.cli import app
from ttassistant.domain.exceptions import TTAssistantError
from ttassistant.ports.terminal import TerminalUIPort

runner = CliRunner()
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def test_cli_version_flag_runner():
    """Verify --version with CliRunner outputs version string and exits 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"ttassistant {__version__}" in result.output.strip()


def test_cli_version_short_flag_runner():
    """Verify -v with CliRunner outputs version string and exits 0."""
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"ttassistant {__version__}" in result.output.strip()


def test_cli_help_flag_runner():
    """Verify --help with CliRunner renders options and exits 0."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in result.output
    assert "--help" in result.output


def test_cli_unknown_option_runner():
    """Verify --unknown with CliRunner exits with code 2."""
    result = runner.invoke(app, ["--unknown"])
    assert result.exit_code == 2
    assert "No such option" in result.output or "Error" in result.output


def test_cli_subprocess_version():
    """Verify external invocation of ttassistant --version returns 0 and correct string."""
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--version"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"ttassistant {__version__}"


def test_cli_subprocess_help():
    """Verify external invocation of ttassistant --help returns 0 and help text."""
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "ttassistant" in proc.stdout
    assert "--version" in proc.stdout


def test_cli_subprocess_unknown():
    """Verify external invocation with invalid flag returns code 2."""
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--unknown"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "No such option" in proc.stderr or "No such option" in proc.stdout


def test_cli_non_tty_execution_no_ansi_corruption():
    """Verify piped execution (non-TTY) does not contain ANSI escape corruption."""
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--help"],
        stdin=subprocess.PIPE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert not ANSI_ESCAPE_PATTERN.search(proc.stdout)


def test_cli_term_dumb_execution():
    """Verify TERM=dumb execution outputs plain text without ANSI escape codes."""
    env = dict(os.environ, TERM="dumb")
    proc = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--help"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert not ANSI_ESCAPE_PATTERN.search(proc.stdout)


def test_cli_runs_without_terraform_or_az():
    """Verify CLI functions in an environment where terraform and az are absent from PATH."""
    venv_bin = str(Path(sys.executable).parent)
    isolated_path = f"{venv_bin}:/usr/bin:/bin"

    clean_paths = []
    for p in isolated_path.split(":"):
        if not (Path(p) / "az").exists() and not (Path(p) / "terraform").exists():
            clean_paths.append(p)
    if venv_bin not in clean_paths:
        clean_paths.insert(0, venv_bin)

    env = dict(os.environ, PATH=":".join(clean_paths))
    proc_version = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc_version.returncode == 0
    assert f"ttassistant {__version__}" in proc_version.stdout

    proc_help = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--help"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc_help.returncode == 0


def test_cli_cold_boot_performance():
    """Verify CLI cold boot time is <= 1.5s for --help and --version."""
    start = time.perf_counter()
    proc_ver = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--version"],
        capture_output=True,
        text=True,
    )
    ver_time = time.perf_counter() - start
    assert proc_ver.returncode == 0
    assert ver_time <= 1.5, f"--version took {ver_time:.2f}s (budget <= 1.5s)"

    start = time.perf_counter()
    proc_help = subprocess.run(
        [sys.executable, "-m", "ttassistant", "--help"],
        capture_output=True,
        text=True,
    )
    help_time = time.perf_counter() - start
    assert proc_help.returncode == 0
    assert help_time <= 1.5, f"--help took {help_time:.2f}s (budget <= 1.5s)"


def test_cli_top_level_error_handling_ttassistant_error():
    """Verify TTAssistantError formats user-friendly error banners on stderr without raw stack trace."""
    code = (
        "from ttassistant.cli import app\n"
        "from ttassistant.domain.exceptions import TTAssistantError\n"
        "@app.command('test-error')\n"
        "def error_cmd():\n"
        "    raise TTAssistantError('Standards missing', details='Create common_standards/')\n"
        "app()\n"
    )
    # Without --debug
    proc = subprocess.run(
        [sys.executable, "-c", code, "test-error"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Standards missing" in proc.stderr
    assert "Details: Create common_standards/" in proc.stderr
    assert "Traceback (most recent call last)" not in proc.stderr
    assert proc.stdout == ""

    # With --debug
    proc_debug = subprocess.run(
        [sys.executable, "-c", code, "--debug", "test-error"],
        capture_output=True,
        text=True,
    )
    assert proc_debug.returncode == 1
    assert "Traceback (most recent call last)" in proc_debug.stderr or "Traceback" in proc_debug.stderr


def test_cli_top_level_error_handling_abort():
    """Verify typer.Abort exits with code 130 and prints 'Aborted.'."""
    code = (
        "import typer\n"
        "from ttassistant.cli import app\n"
        "@app.command('test-abort')\n"
        "def abort_cmd():\n"
        "    raise typer.Abort()\n"
        "app()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, "test-abort"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 130
    assert "Aborted." in proc.stdout or "Aborted." in proc.stderr


def test_cli_top_level_error_handling_unexpected_exception():
    """Verify unexpected Exception is caught and formatted on stderr without traceback unless --debug."""
    code = (
        "from ttassistant.cli import app\n"
        "@app.command('test-crash')\n"
        "def crash_cmd():\n"
        "    raise RuntimeError('Unexpected disk corruption')\n"
        "app()\n"
    )
    # Without --debug
    proc = subprocess.run(
        [sys.executable, "-c", code, "test-crash"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Unexpected error: Unexpected disk corruption" in proc.stderr
    assert "Traceback (most recent call last)" not in proc.stderr

    # With --debug
    proc_debug = subprocess.run(
        [sys.executable, "-c", code, "--debug", "test-crash"],
        capture_output=True,
        text=True,
    )
    assert proc_debug.returncode == 1
    assert "Traceback (most recent call last)" in proc_debug.stderr or "Traceback" in proc_debug.stderr


def test_terminal_adapter_implements_protocol():
    """Verify RichTerminalAdapter satisfies TerminalUIPort protocol."""
    adapter = RichTerminalAdapter()
    assert isinstance(adapter, TerminalUIPort)


def test_terminal_adapter_methods(capsys):
    """Verify terminal adapter printing and formatting methods."""
    adapter = RichTerminalAdapter()
    adapter.print("Standard message")
    adapter.print("Stderr detail", stderr=True)
    adapter.print_success("Success message")
    adapter.print_warning("Warning message")
    adapter.print_info("Info message")
    adapter.display_diff("--- a\n+++ b\n+added line")

    captured = capsys.readouterr()
    assert "Standard message" in captured.out
    assert "Stderr detail" in captured.err
    assert "Success message" in captured.out
    assert "Warning message" in captured.out
    assert "Info message" in captured.out
    assert "+added line" in captured.out


def test_terminal_adapter_error(capsys):
    """Verify terminal adapter error message output to stderr."""
    adapter = RichTerminalAdapter()
    adapter.print_error("Critical error")
    captured = capsys.readouterr()
    assert "Critical error" in captured.err


def test_terminal_adapter_fallback_prompts(monkeypatch):
    """Verify terminal adapter non-TTY prompt fallbacks."""
    adapter = RichTerminalAdapter()
    monkeypatch.setattr(adapter, "is_tty", lambda: False)

    # confirm fallback
    monkeypatch.setattr("sys.stdin.readline", lambda: "y\n")
    assert adapter.confirm("Are you sure?", default=False) is True

    monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
    assert adapter.confirm("Are you sure?", default=False) is False

    # prompt_text fallback
    monkeypatch.setattr("sys.stdin.readline", lambda: "custom_val\n")
    assert adapter.prompt_text("Enter name", default="default_val") == "custom_val"

    monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
    assert adapter.prompt_text("Enter name", default="default_val") == "default_val"

    # prompt_select fallback
    choices = ["Option A", "Option B", "Option C"]
    monkeypatch.setattr("sys.stdin.readline", lambda: "2\n")
    assert adapter.prompt_select("Choose", choices=choices) == "Option B"


def test_terminal_adapter_interactive_questionary_delegation(monkeypatch):
    """Verify terminal adapter delegates to Questionary when in interactive TTY mode."""
    adapter = RichTerminalAdapter()
    monkeypatch.setattr(adapter, "is_tty", lambda: True)
    monkeypatch.setattr(adapter, "is_term_dumb", lambda: False)

    # Test confirm delegation
    with patch("questionary.confirm") as mock_confirm:
        mock_confirm.return_value.ask.return_value = True
        res = adapter.confirm("Proceed with commit?", default=True)
        assert res is True
        mock_confirm.assert_called_once_with("Proceed with commit?", default=True)

    # Test prompt_text delegation
    with patch("questionary.text") as mock_text:
        mock_text.return_value.ask.return_value = "my_resource"
        res = adapter.prompt_text("Resource name", default="default_name")
        assert res == "my_resource"
        mock_text.assert_called_once_with("Resource name", default="default_name")

    # Test prompt_select delegation with valid default
    with patch("questionary.select") as mock_select:
        mock_select.return_value.ask.return_value = "choice_2"
        choices = ["choice_1", "choice_2"]
        res = adapter.prompt_select("Select one", choices=choices, default="choice_2")
        assert res == "choice_2"
        mock_select.assert_called_once_with("Select one", choices=choices, default="choice_2")

    # Test prompt_select guards against default not in choices (preventing questionary ValueError)
    with patch("questionary.select") as mock_select:
        mock_select.return_value.ask.return_value = "choice_1"
        choices = ["choice_1", "choice_2"]
        res = adapter.prompt_select("Select one", choices=choices, default="not_in_list")
        assert res == "choice_1"
        # guarded to choices[0]
        mock_select.assert_called_once_with("Select one", choices=choices, default="choice_1")


def test_terminal_adapter_interactive_abort_on_none(monkeypatch):
    """Verify interactive prompts raise typer.Abort when user cancels (ask returns None)."""
    adapter = RichTerminalAdapter()
    monkeypatch.setattr(adapter, "is_tty", lambda: True)
    monkeypatch.setattr(adapter, "is_term_dumb", lambda: False)

    with patch("questionary.confirm") as mock_confirm:
        mock_confirm.return_value.ask.return_value = None
        with pytest.raises(typer.Abort):
            adapter.confirm("Cancel here?")

    with patch("questionary.text") as mock_text:
        mock_text.return_value.ask.return_value = None
        with pytest.raises(typer.Abort):
            adapter.prompt_text("Input text")

    with patch("questionary.select") as mock_select:
        mock_select.return_value.ask.return_value = None
        with pytest.raises(typer.Abort):
            adapter.prompt_select("Select choice", choices=["a", "b"])


def test_terminal_adapter_markup_escaping_and_bracket_preservation(capsys, monkeypatch):
    """Verify bracketed names and diff brackets are preserved and not stripped as Rich markup tags."""
    adapter = RichTerminalAdapter()

    # Test non-color path
    monkeypatch.setattr(adapter, "is_color_supported", lambda: False)
    monkeypatch.setattr(adapter, "is_stderr_color_supported", lambda: False)

    adapter.print("Deploying [azurerm_resource_group.rg]")
    adapter.print_success("Created [azurerm_storage_account.sa]")
    adapter.print_warning("Deprecated [azurerm_virtual_network.vnet]")
    adapter.print_info("Info [azurerm_subnet.sub]")
    adapter.print_error("Failed [azurerm_private_endpoint.pe]")
    adapter.display_diff("--- a\n+++ b\n+[azurerm_key_vault.kv]")

    captured = capsys.readouterr()
    assert "[azurerm_resource_group.rg]" in captured.out
    assert "[azurerm_storage_account.sa]" in captured.out
    assert "[azurerm_virtual_network.vnet]" in captured.out
    assert "[azurerm_subnet.sub]" in captured.out
    assert "[azurerm_private_endpoint.pe]" in captured.err
    assert "+[azurerm_key_vault.kv]" in captured.out

    # Test color path
    monkeypatch.setattr(adapter, "is_color_supported", lambda: True)
    monkeypatch.setattr(adapter, "is_stderr_color_supported", lambda: True)

    adapter.print_success("Created [azurerm_storage_account.sa]")
    adapter.print_warning("Deprecated [azurerm_virtual_network.vnet]")
    adapter.print_info("Info [azurerm_subnet.sub]")
    adapter.print_error("Failed [azurerm_private_endpoint.pe]")
    adapter.display_diff("--- a\n+++ b\n+[azurerm_key_vault.kv]")

    captured_color = capsys.readouterr()
    assert "[azurerm_storage_account.sa]" in captured_color.out
    assert "[azurerm_virtual_network.vnet]" in captured_color.out
    assert "[azurerm_subnet.sub]" in captured_color.out
    assert "[azurerm_private_endpoint.pe]" in captured_color.err
    assert "+[azurerm_key_vault.kv]" in captured_color.out


def test_terminal_adapter_stderr_force_terminal_isolation(monkeypatch):
    """Verify err_console force_terminal checks stderr.isatty independently from stdout."""
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)

    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True
    mock_stdout.encoding = "utf-8"

    mock_stderr = MagicMock()
    mock_stderr.isatty.return_value = False
    mock_stderr.encoding = "utf-8"

    adapter = RichTerminalAdapter(stdout=mock_stdout, stderr=mock_stderr)
    assert adapter.is_tty() is True
    assert adapter.is_stderr_tty() is False
    assert adapter.is_color_supported() is True
    assert adapter.is_stderr_color_supported() is False
    assert adapter.console.no_color is False
    assert adapter.err_console.no_color is True
