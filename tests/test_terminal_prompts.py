"""Unit tests for Terminal UI Adapter prompts, validation callbacks, and TTY/non-TTY modes."""

import io
from unittest.mock import MagicMock, patch
import pytest
import typer

from ttassistant.adapters.terminal_adapter import RichTerminalAdapter


def test_prompt_text_tty_delegates_to_questionary_with_validate(monkeypatch):
    """Verify prompt_text passes validate callback to questionary.text in TTY mode."""
    adapter = RichTerminalAdapter()
    monkeypatch.setattr(adapter, "is_tty", lambda: True)
    monkeypatch.setattr(adapter, "is_term_dumb", lambda: False)

    dummy_validator = lambda s: True

    with patch("questionary.text") as mock_text:
        mock_text.return_value.ask.return_value = "custom_value"
        res = adapter.prompt_text("Enter name:", default="def", validate=dummy_validator)
        assert res == "custom_value"
        mock_text.assert_called_once_with("Enter name:", default="def", validate=dummy_validator)


def test_prompt_text_tty_cancellation_raises_abort(monkeypatch):
    """Verify prompt_text raises typer.Abort when questionary returns None or raises KeyboardInterrupt."""
    adapter = RichTerminalAdapter()
    monkeypatch.setattr(adapter, "is_tty", lambda: True)
    monkeypatch.setattr(adapter, "is_term_dumb", lambda: False)

    with patch("questionary.text") as mock_text:
        mock_text.return_value.ask.return_value = None
        with pytest.raises(typer.Abort):
            adapter.prompt_text("Prompt:")

    with patch("questionary.text") as mock_text:
        mock_text.return_value.ask.side_effect = KeyboardInterrupt()
        with pytest.raises(typer.Abort):
            adapter.prompt_text("Prompt:")


def test_prompt_text_nontty_valid_input():
    """Verify prompt_text returns stripped input on valid entry in non-TTY mode."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = io.StringIO("my_input\n")

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    res = adapter.prompt_text("Enter value:")
    assert res == "my_input"
    assert "Enter value:" in stdout.getvalue()


def test_prompt_text_nontty_default_value_on_empty():
    """Verify prompt_text returns default value when empty string is submitted in non-TTY mode."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = io.StringIO("\n")

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    res = adapter.prompt_text("Enter value:", default="my_default")
    assert res == "my_default"


def test_prompt_text_nontty_validation_loop_recovery():
    """Verify non-TTY prompt_text displays error message and retries until valid input is received."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    # Feed invalid input first, then valid input
    stdin = io.StringIO("invalid_val\nvalid_val\n")

    def validator(val: str):
        if val == "valid_val":
            return True
        return "Must be valid_val"

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    res = adapter.prompt_text("Enter value:", validate=validator)

    assert res == "valid_val"
    assert "Must be valid_val" in stderr.getvalue()


def test_prompt_text_nontty_validation_returns_false_message():
    """Verify non-TTY prompt_text prints 'Invalid input' when validator returns False."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = io.StringIO("bad\ngood\n")

    def validator(val: str):
        return val == "good"

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    res = adapter.prompt_text("Enter:", validate=validator)

    assert res == "good"
    assert "Invalid input" in stderr.getvalue()


def test_prompt_text_nontty_eof_raises_abort():
    """Verify non-TTY prompt_text cleanly raises typer.Abort on EOF without infinite loop."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = io.StringIO("")  # Empty stream -> EOF immediately

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    with pytest.raises(typer.Abort):
        adapter.prompt_text("Enter:")


def test_prompt_confirm_and_select_nontty_eof_raises_abort():
    """Verify confirm and prompt_select cleanly raise typer.Abort on unexpected EOF in non-TTY mode."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = io.StringIO("")

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    with pytest.raises(typer.Abort):
        adapter.confirm("Confirm?")

    with pytest.raises(typer.Abort):
        adapter.prompt_select("Select:", choices=["choice1", "choice2"])


def test_prompt_select_nontty_invalid_input_recovery():
    """Verify non-TTY prompt_select prints error and loops on invalid numbers or non-numeric inputs until valid."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    # Out of range, non-numeric, then valid choice 2
    stdin = io.StringIO("99\ninvalid_choice\n2\n")

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    choices = ["Alpha", "Beta", "Gamma"]
    res = adapter.prompt_select("Select Greek letter:", choices=choices)

    assert res == "Beta"
    err_output = stderr.getvalue()
    assert "Invalid choice '99'" in err_output
    assert "Invalid choice 'invalid_choice'" in err_output


def test_prompt_text_tty_delegates_completer(monkeypatch):
    """Verify prompt_text passes completer parameter to questionary.text in TTY mode."""
    adapter = RichTerminalAdapter()
    monkeypatch.setattr(adapter, "is_tty", lambda: True)
    monkeypatch.setattr(adapter, "is_term_dumb", lambda: False)

    dummy_completer = object()

    with patch("questionary.text") as mock_text:
        mock_text.return_value.ask.return_value = "autocompleted"
        res = adapter.prompt_text("Enter word:", completer=dummy_completer)
        assert res == "autocompleted"
        mock_text.assert_called_once_with("Enter word:", default="", completer=dummy_completer)

