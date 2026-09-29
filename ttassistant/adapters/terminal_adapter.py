"""Rich Terminal UI Adapter implementation."""

import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from ttassistant.ports.terminal import TerminalUIPort


class RichTerminalAdapter:
    """Terminal UI adapter using Rich with TTY and Dumb-terminal fallback."""

    def __init__(
        self,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        stdin: TextIO | None = None,
    ) -> None:
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.stdin = stdin or sys.stdin

        self._init_consoles()

    def _init_consoles(self) -> None:
        stdout_color_ok = self.is_color_supported()
        stdout_is_tty = self.is_tty()

        stderr_color_ok = self.is_stderr_color_supported()
        stderr_is_tty = self.is_stderr_tty()

        self.console = Console(
            file=self.stdout,
            force_terminal=stdout_is_tty and stdout_color_ok,
            no_color=not stdout_color_ok,
            highlight=False,
        )
        self.err_console = Console(
            file=self.stderr,
            force_terminal=stderr_is_tty and stderr_color_ok,
            no_color=not stderr_color_ok,
            highlight=False,
        )

    def is_tty(self) -> bool:
        """Return True if stdout is attached to an interactive terminal."""
        try:
            return bool(self.stdout.isatty())
        except (AttributeError, ValueError):
            return False

    def is_interactive(self) -> bool:
        """Return True if both stdout and stdin are interactive terminals."""
        if not self.is_tty() or self.is_term_dumb():
            return False
        if self.stdin.__class__.__name__ == "DontReadFromInput":
            return True
        try:
            return bool(getattr(self.stdin, "isatty", lambda: False)())
        except (AttributeError, ValueError):
            return False


    def is_stderr_tty(self) -> bool:
        """Return True if stderr is an interactive TTY."""
        try:
            return bool(self.stderr.isatty())
        except (AttributeError, ValueError):
            return False

    def is_term_dumb(self) -> bool:
        """Return True if the terminal is dumb."""
        return os.environ.get("TERM", "").strip().lower() == "dumb"

    def is_no_color(self) -> bool:
        """Return True if NO_COLOR environment variable is set."""
        return "NO_COLOR" in os.environ

    def is_utf8(self) -> bool:
        """Return True if stream encoding supports UTF-8."""
        encoding = getattr(self.stdout, "encoding", None) or ""
        return "utf-8" in encoding.lower() or "utf8" in encoding.lower()

    def is_color_supported(self) -> bool:
        """Return True if colors/ANSI codes are supported and enabled on stdout."""
        if self.is_term_dumb() or self.is_no_color():
            return False
        return self.is_tty()

    def is_stderr_color_supported(self) -> bool:
        """Return True if colors/ANSI codes are supported and enabled on stderr."""
        if self.is_term_dumb() or self.is_no_color():
            return False
        return self.is_stderr_tty()

    @property
    def glyph_success(self) -> str:
        return "✔" if (self.is_utf8() and not self.is_term_dumb()) else "[x]"

    @property
    def glyph_error(self) -> str:
        return "✖" if (self.is_utf8() and not self.is_term_dumb()) else "[!]"

    @property
    def glyph_warning(self) -> str:
        return "⚠" if (self.is_utf8() and not self.is_term_dumb()) else "[?]"

    @property
    def glyph_info(self) -> str:
        return "ℹ" if (self.is_utf8() and not self.is_term_dumb()) else "[*]"

    @property
    def glyph_arrow(self) -> str:
        return "»" if (self.is_utf8() and not self.is_term_dumb()) else ">"

    def print(self, message: str = "", stderr: bool = False) -> None:
        """Print standard output or details to stderr if requested."""
        target_console = self.err_console if stderr else self.console
        target_console.print(message, markup=False)

    def print_success(self, message: str) -> None:
        """Print a success message."""
        if self.is_color_supported():
            self.console.print(f"[bold green]{self.glyph_success}[/bold green] {escape(message)}")
        else:
            self.console.print(f"{self.glyph_success} {message}", markup=False)

    def print_error(self, message: str) -> None:
        """Print an error message."""
        if self.is_stderr_color_supported():
            self.err_console.print(f"[bold red]{self.glyph_error}[/bold red] [red]{escape(message)}[/red]")
        else:
            self.err_console.print(f"{self.glyph_error} {message}", markup=False)

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        if self.is_color_supported():
            self.console.print(f"[bold yellow]{self.glyph_warning}[/bold yellow] [yellow]{escape(message)}[/yellow]")
        else:
            self.console.print(f"{self.glyph_warning} {message}", markup=False)

    def print_info(self, message: str) -> None:
        """Print an informational message."""
        if self.is_color_supported():
            self.console.print(f"[bold cyan]{self.glyph_info}[/bold cyan] {escape(message)}")
        else:
            self.console.print(f"{self.glyph_info} {message}", markup=False)

    def display_diff(self, diff_content: str) -> None:
        """Render diff content."""
        if not diff_content:
            return
        if self.is_color_supported():
            syntax = Syntax(
                diff_content,
                "diff",
                theme="monokai",
                line_numbers=False,
                background_color="default",
                padding=0,
            )
            self.console.print(syntax)
        else:
            self.console.print(diff_content, markup=False, soft_wrap=True)

    def display_security_warning(
        self,
        message: str,
        details: list[str] | None = None,
        title: str = "SECURITY POLICY WARNING",
    ) -> None:
        """Render a high-visibility security warning banner/modal."""
        if self.is_color_supported():
            content_lines = [f"[bold red]{self.glyph_warning} {escape(message)}[/bold red]"]
            if details:
                content_lines.append("")
                for item in details:
                    content_lines.append(f"[yellow]• {escape(item)}[/yellow]")
            body = "\n".join(content_lines)
            panel = Panel(
                body,
                title=f"[bold red] {escape(title)} [/bold red]",
                border_style="red",
                padding=(1, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            border = "=" * 70
            self.console.print()
            self.console.print(border)
            self.console.print(f" {self.glyph_warning} {title}")
            self.console.print(border)
            self.console.print(f" {message}")
            if details:
                for item in details:
                    self.console.print(f"  * {item}")
            self.console.print(border)

    def print_security_warning(self, message: str) -> None:
        """Print a security warning banner."""
        self.display_security_warning(message)

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """Prompt user for confirmation."""
        default_str = "Y/n" if default else "y/N"
        if not self.is_interactive() or self.is_term_dumb():
            self.stdout.write(f"{prompt} [{default_str}]: ")
            self.stdout.flush()
            try:
                raw_line = self.stdin.readline()
            except (KeyboardInterrupt, EOFError):
                raise typer.Abort()
            if raw_line == "":
                raise typer.Abort()
            line = raw_line.strip().lower()
            if not line:
                return default
            return line in ("y", "yes")

        import questionary

        try:
            res = questionary.confirm(prompt, default=default).ask()
        except KeyboardInterrupt:
            raise typer.Abort()
        if res is None:
            raise typer.Abort()
        return bool(res)

    def prompt_text(
        self,
        prompt: str,
        default: str = "",
        validate: Callable[[str], bool | str] | None = None,
        completer: Any = None,
    ) -> str:
        """Prompt user for text."""
        if not self.is_interactive() or self.is_term_dumb():
            base_prompt = prompt.rstrip()
            sep = " " if base_prompt.endswith(":") else ": "
            prompt_str = f"{base_prompt} [{default}]: " if default else f"{base_prompt}{sep}"
            while True:
                self.stdout.write(prompt_str)
                self.stdout.flush()
                try:
                    raw_line = self.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    raise typer.Abort()
                if raw_line == "":
                    raise typer.Abort()
                line = raw_line.strip()
                val = line if line else default
                if validate is not None:
                    res = validate(val)
                    if res is True:
                        return val
                    elif isinstance(res, str):
                        self.print_error(res)
                        continue
                    else:
                        self.print_error("Invalid input")
                        continue
                return val

        import questionary

        kwargs = {}
        if validate is not None:
            kwargs["validate"] = validate
        if completer is not None:
            kwargs["completer"] = completer

        try:
            res = questionary.text(prompt, default=default, **kwargs).ask()
        except KeyboardInterrupt:
            raise typer.Abort()
        if res is None:
            raise typer.Abort()
        return str(res)

    def prompt_select(self, prompt: str, choices: list[str], default: str | None = None) -> str:
        """Prompt user to select an option."""
        if not choices:
            return ""

        if not self.is_interactive() or self.is_term_dumb():
            self.stdout.write(f"{prompt}\n")
            for idx, choice in enumerate(choices, 1):
                marker = "*" if default and choice == default else " "
                self.stdout.write(f" {idx}) [{marker}] {choice}\n")
            default_idx = choices.index(default) + 1 if default in choices else 1
            while True:
                self.stdout.write(f"Select choice [1-{len(choices)}] (default: {default_idx}): ")
                self.stdout.flush()
                try:
                    raw_line = self.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    raise typer.Abort()
                if raw_line == "":
                    raise typer.Abort()
                line = raw_line.strip()
                if not line:
                    return choices[default_idx - 1]
                if line in choices:
                    return line
                try:
                    val = int(line)
                    if 1 <= val <= len(choices):
                        return choices[val - 1]
                except ValueError:
                    pass
                self.print_error(f"Invalid choice '{line}'. Please enter a number between 1 and {len(choices)}.")

        import questionary

        valid_default = default if (default is not None and default in choices) else choices[0]
        try:
            res = questionary.select(prompt, choices=choices, default=valid_default).ask()
        except KeyboardInterrupt:
            raise typer.Abort()
        if res is None:
            raise typer.Abort()
        return str(res)

    def prompt_select_subnet(
        self,
        prompt: str,
        choices: list[str],
        default: str | None = None,
    ) -> str:
        """Prompt user to select a subnet candidate, defaulting to (Recommended) option if present."""
        if default is None and choices:
            for c in choices:
                if "(Recommended)" in c:
                    default = c
                    break
        return self.prompt_select(prompt, choices=choices, default=default)

    def prompt_confirmation_gate(self, prompt: str = "Action:") -> str:
        """Prompt user for confirmation gate decision: 'commit', 'cancel', or 'tweak'."""
        if not self.is_interactive() or self.is_term_dumb():
            while True:
                self.stdout.write(f"{prompt} [Y] Commit / [N] Cancel / [T] Tweak (default: Y): ")
                self.stdout.flush()
                try:
                    raw_line = self.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    raise typer.Abort()
                if raw_line == "":
                    raise typer.Abort()
                line = raw_line.strip().lower()
                if not line or line in ("y", "yes", "commit"):
                    return "commit"
                if line in ("n", "no", "cancel"):
                    return "cancel"
                if line in ("t", "tweak", "refine"):
                    return "tweak"
                self.print_error("Invalid selection. Please enter 'y' to commit, 'n' to cancel, or 't' to tweak.")

        import questionary

        choices = [
            questionary.Choice(title="[Y] Commit changes to disk", value="commit"),
            questionary.Choice(title="[Tweak] Enter refinement instruction", value="tweak"),
            questionary.Choice(title="[N] Cancel and exit", value="cancel"),
        ]
        try:
            res = questionary.select(prompt, choices=choices, default=choices[0]).ask()
        except KeyboardInterrupt:
            raise typer.Abort()
        if res is None:
            raise typer.Abort()
        return str(res)

    def clear_screen(self) -> None:
        """Clear or refresh the terminal screen if supported."""
        if self.is_interactive():
            self.console.clear()

    def display_table(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
    ) -> None:
        """Render a tabular dataset with headers and rows."""
        if not rows:
            return
        if self.is_color_supported():
            table = Table(title=title, show_header=True, header_style="bold cyan")
            for h in headers:
                table.add_column(h)
            for row in rows:
                table.add_row(*row)
            self.console.print(table)
        else:
            self.console.print(f"\n=== {title} ===")
            col_widths = [len(h) for h in headers]
            for row in rows:
                for idx, cell in enumerate(row):
                    if idx < len(col_widths):
                        # Use first line length if multi-line
                        first_line = str(cell).split("\n")[0] if str(cell) else ""
                        col_widths[idx] = max(col_widths[idx], len(first_line))
            fmt_header = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
            separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
            self.console.print(fmt_header)
            self.console.print(separator)
            for row in rows:
                fmt_row = " | ".join(
                    str(cell).split("\n")[0].ljust(col_widths[i])
                    for i, cell in enumerate(row)
                    if i < len(col_widths)
                )
                self.console.print(fmt_row)

