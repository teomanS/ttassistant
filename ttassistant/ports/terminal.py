"""Terminal UI Port definition."""

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TerminalUIPort(Protocol):
    """Abstract port defining the interface for terminal interactions."""

    def is_tty(self) -> bool:
        """Return True if stdout is attached to an interactive terminal."""
        ...

    def is_interactive(self) -> bool:
        """Return True if both stdout and stdin are interactive terminals."""
        ...

    def is_color_supported(self) -> bool:
        """Return True if color/ANSI styling is supported in the current environment."""
        ...

    def print(self, message: str = "", stderr: bool = False) -> None:
        """Print standard message to stdout, or to stderr if stderr=True."""
        ...

    def print_success(self, message: str) -> None:
        """Print a success message."""
        ...

    def print_error(self, message: str) -> None:
        """Print an error message."""
        ...

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        ...

    def print_info(self, message: str) -> None:
        """Print an informational message."""
        ...

    def display_diff(self, diff_content: str) -> None:
        """Display unified diff content with syntax highlighting if supported."""
        ...

    def display_security_warning(
        self,
        message: str,
        details: list[str] | None = None,
        title: str = "SECURITY POLICY WARNING",
    ) -> None:
        """Render a high-visibility security warning banner/modal."""
        ...

    def print_security_warning(self, message: str) -> None:
        """Print a security warning banner."""
        ...

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """Prompt user for confirmation (yes/no)."""
        ...

    def prompt_text(
        self,
        prompt: str,
        default: str = "",
        validate: Callable[[str], bool | str] | None = None,
        completer: Any = None,
    ) -> str:
        """Prompt user for text input."""
        ...

    def prompt_select(self, prompt: str, choices: list[str], default: str | None = None) -> str:
        """Prompt user to select from a list of options."""
        ...

    def prompt_select_subnet(
        self,
        prompt: str,
        choices: list[str],
        default: str | None = None,
    ) -> str:
        """Prompt user to select a subnet candidate from formatted options, defaulting to recommended."""
        ...

    def prompt_confirmation_gate(self, prompt: str = "Action:") -> str:
        """Prompt user for confirmation gate decision: 'commit', 'cancel', or 'tweak'."""
        ...

    def clear_screen(self) -> None:
        """Clear or refresh the terminal screen if supported."""
        ...

    def display_table(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
    ) -> None:
        """Render a tabular dataset with headers and rows."""
        ...


