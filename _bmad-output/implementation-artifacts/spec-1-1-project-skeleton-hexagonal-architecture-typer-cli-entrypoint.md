---
title: 'Story 1.1: Project Skeleton, Hexagonal Architecture & Typer CLI Entrypoint'
type: 'feature'
created: '2026-09-21'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md'
  - '_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Infrastructure engineers need a fast, cross-platform terminal CLI co-pilot entrypoint (`ttassistant`) executable inside VSCode terminal environments across Linux and Windows without requiring local `terraform` or `az` binaries.

**Approach:** Bootstrap the project skeleton using Hatchling (`pyproject.toml`), establish Hexagonal Architecture package boundaries (`domain`, `ports`, `adapters`, `application`), and implement the Typer CLI entrypoint supporting `--help` and `--version` with ANSI terminal output and graceful non-TTY / `TERM=dumb` fallback.

## Boundaries & Constraints

**Always:**
- Keep pure business domain packages (`ttassistant.domain`) free of terminal UI, prompt, and filesystem I/O dependencies (AD-1).
- Package as standard PEP 621 configuration in `pyproject.toml` with `hatchling` build system, targeting Python 3.10+.
- Support both Linux and Windows terminal execution with UTF-8 encoding and ASCII fallback for non-UTF-8 code pages.
- Handle non-TTY and `TERM=dumb` gracefully without terminal crash.
- Ensure CLI cold boot time is <= 1.5s for `--help` and `--version`.

**Never:**
- Never invoke external `terraform`, `az`, or shell binaries on `PATH`.
- Never import UI packages (`rich`, `questionary`, `typer`) inside `ttassistant.domain`.
- Never execute live cloud deployments or `terraform apply`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Help flag | `ttassistant --help` | Exit code 0, formatted help with available commands and options | N/A |
| Version flag | `ttassistant --version` | Exit code 0, prints package version string (`ttassistant 0.1.0`) | N/A |
| Non-TTY execution | `echo "" \| ttassistant --help` | Clean plain-text help output without ANSI escape corruption | Fallback to plain text |
| TERM=dumb environment | `TERM=dumb ttassistant --help` | Plain text output without color formatting or cursor movement escape codes | Fallback to plain text |
| Invalid option | `ttassistant --unknown` | Exit code 2, friendly CLI usage error message | Typer parameter error |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- Project metadata, Hatchling build system, dependencies (`typer`, `rich`, `questionary`, `pydantic`), and CLI script entrypoint (`ttassistant = "ttassistant.cli:app"`).
- `ttassistant/__init__.py` -- Package version definition (`__version__ = "0.1.0"`).
- `ttassistant/__main__.py` -- Module execution entrypoint (`python -m ttassistant`).
- `ttassistant/cli.py` -- Typer CLI application, global options (`--version`), and top-level error formatting.
- `ttassistant/domain/__init__.py` -- Domain layer marker (pure business logic, zero I/O imports).
- `ttassistant/ports/__init__.py` -- Ports layer marker (abstract Protocols).
- `ttassistant/adapters/__init__.py` -- Adapters layer marker (concrete I/O implementations).
- `ttassistant/application/__init__.py` -- Application orchestration layer marker.
- `ttassistant/ports/terminal.py` -- Initial `TerminalUIPort` Protocol definition.
- `ttassistant/adapters/terminal_adapter.py` -- Initial `RichTerminalAdapter` scaffolding with TTY detection.
- `tests/test_cli.py` -- CLI integration tests verifying `--help`, `--version`, non-TTY fallback, and performance.
- `tests/test_architecture.py` -- Architectural boundary test ensuring `ttassistant.domain` contains zero imports from `rich`, `questionary`, `typer`, or direct I/O.

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- Create PEP 621 Hatchling project specification with core dependencies and `ttassistant` CLI console script entrypoint.
- [x] `ttassistant/__init__.py` & `ttassistant/__main__.py` -- Initialize package root with version string and module runner invoking `ttassistant.cli:app`.
- [x] `ttassistant/domain/__init__.py`, `ttassistant/ports/__init__.py`, `ttassistant/adapters/__init__.py`, `ttassistant/application/__init__.py` -- Establish hexagonal package boundaries.
- [x] `ttassistant/ports/terminal.py` -- Define abstract `TerminalUIPort` protocol for terminal interactions.
- [x] `ttassistant/adapters/terminal_adapter.py` -- Implement basic terminal utilities with TTY / encoding detection and ANSI/ASCII handling.
- [x] `ttassistant/cli.py` -- Implement Typer CLI entrypoint with `--help`, `--version`, and graceful error handling.
- [x] `tests/test_cli.py` -- Implement unit tests for CLI entrypoint, version output, help text rendering, and invalid flags.
- [x] `tests/test_architecture.py` -- Implement architectural AST lint test verifying domain layer isolation from UI/IO modules (AD-1).

**Acceptance Criteria:**
- Given an environment with Python 3.10+ where `terraform` and `az` are not installed on PATH, when the user runs `ttassistant --help` or `ttassistant --version`, then the CLI responds in <= 1.5 seconds with clear command-line usage and version information.
- Given a non-TTY or `TERM=dumb` terminal execution, when running `ttassistant`, then output degrades gracefully to plain text without crashing or emitting corrupt escape codes.
- Given the codebase, when inspecting the directory structure and running architecture boundary tests, then `ttassistant` adheres to Hexagonal Architecture with `ttassistant.domain` completely decoupled from UI and filesystem dependencies.

## Implementation Notes

- Implemented PEP 621 `pyproject.toml` with Hatchling build system, specifying all required core dependencies and script entrypoint `ttassistant = "ttassistant.cli:app"`.
- Created package root `ttassistant/__init__.py` (`__version__ = "0.1.0"`) and module entrypoint `ttassistant/__main__.py`.
- Established Hexagonal Architecture package boundaries with layer markers and docstrings (`domain`, `ports`, `adapters`, `application`).
- Defined domain exception `TTAssistantError` in `ttassistant.domain.exceptions`.
- Defined `TerminalUIPort` as a `runtime_checkable` `Protocol` in `ttassistant/ports/terminal.py`.
- Implemented `RichTerminalAdapter` in `ttassistant/adapters/terminal_adapter.py` supporting TTY detection, `TERM=dumb` / `NO_COLOR` fallbacks, UTF-8 / ASCII glyph toggling, and non-interactive stream prompting fallbacks.
- Implemented `TTAssistantCLI` in `ttassistant/cli.py` subclassing `typer.Typer` to provide top-level exception catching, graceful exit code handling, and banner formatting without raw stack traces unless `--debug` is active.
- Added comprehensive unit and integration tests in `tests/test_cli.py` (15 tests) and `tests/test_architecture.py` (4 tests), passing with 100% success rate. Cold boot benchmark verified at ~0.13s - 0.21s (< 1.5s budget).

## Spec Change Log

## Review Triage Log

| Finding | Layer | Verdict | Evidence | Route |
| :--- | :--- | :--- | :--- | :--- |
| CLI exception handling unverified | verification-gap | medium | Tests in `tests/test_cli.py` do not test `TTAssistantError`, `Abort`, or `--debug` handling in `TTAssistantCLI`. | patch |
| AST lint ignores relative imports | verification-gap | medium | `get_imports_from_file` does not inspect `node.level` or unqualified relative imports from prohibited layers. | patch |
| Interactive TTY prompt methods unverified | verification-gap | low | Tests only assert non-TTY readline fallbacks; interactive Questionary paths are unverified. | patch |
| Color/syntax output paths unexercised | verification-gap | low | `test_terminal_adapter_methods` runs under pytest capsys where `is_tty` is False, bypassing color branches. | patch |
| Non-color diff markup stripping | edge-case-hunter | medium | `display_diff` in non-color mode calls `console.print(diff_content)` without `markup=False`, stripping square brackets. | patch |
| `prompt_select` invalid default raises ValueError | edge-case-hunter | medium | Calling `questionary.select` with default not in choices raises unhandled ValueError in TTY mode. | patch |
| Error output split between stderr and stdout | edge-case-hunter | low | `cli.py` prints error message to stderr but details to stdout console. | patch |
| Asymmetric TTY detection on stderr console | edge-case-hunter | low | `err_console` forces terminal based on stdout TTY rather than stderr TTY. | patch |
| Interactive cancellation defaults instead of aborting | blind-hunter | medium | When user cancels Questionary prompt (Ctrl+C/Esc), `ask()` returns None which silently defaulted rather than raising Abort. | patch |
| Private import `typer._click` | blind-hunter | low | `import typer._click as click` uses private API; direct `import click` should be used. | patch |
| Missing PEP 561 `py.typed` | blind-hunter | low | Package lacks `py.typed` marker for type annotations. | patch |
| Missing package exports in `ports` and `adapters` | blind-hunter | low | `ports/__init__.py` and `adapters/__init__.py` omit `__all__` exports. | patch |

## Design Notes

- CLI uses Typer with Rich console integration for styled rendering while maintaining fallback detection via `sys.stdout.isatty()` and `os.environ.get("TERM") == "dumb"`.
- Hexagonal boundary enforcement is verified by inspecting domain module imports using Python's `ast` module in `tests/test_architecture.py`.

