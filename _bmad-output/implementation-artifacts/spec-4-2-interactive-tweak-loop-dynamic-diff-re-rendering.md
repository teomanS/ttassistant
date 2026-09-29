---
title: 'Story 4.2: Interactive Tweak Loop & Dynamic Diff Re-rendering'
type: 'feature'
created: '2026-09-28'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/implementation-artifacts/epic-4-context.md'
  - 'ttassistant/ports/terminal.py'
  - 'ttassistant/adapters/terminal_adapter.py'
  - 'ttassistant/application/provisioning_flow.py'
  - 'ttassistant/application/tweak_handler.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Before committing generated Terraform code to disk, infrastructure developers need the ability to visually verify changes and iteratively refine them in an interactive loop. Currently, the diff confirmation prompt only allows binary accept/reject (`confirm()`), forcing developers to restart the entire dialogue if any attribute or tag needs adjustment.

**Approach:** Upgrade the confirmation gate in `ProvisioningFlow` and `TerminalUIPort` to present a 3-way choice: `[Y] Commit / [N] Cancel / [Tweak] Enter refinement`. When `[Tweak]` is selected, prompt for conversational instructions, apply the mutation in memory via `TweakHandler`, immediately re-render the colorized unified terminal diff, and loop back to the confirmation gate until the user commits or cancels.

## Boundaries & Constraints

**Always:**
- Keep staged modifications purely in memory within `StagedWorkspace` during the entire tweak loop; never write to disk until explicit `[Y] Commit` confirmation is received (AD-5).
- Re-calculate and display the updated unified diff immediately following any successful tweak mutation.
- Support multiple consecutive tweaks within the same interactive session (e.g. tweak replication, then tweak TLS, then add a tag, then commit).
- Provide clean degradation for non-TTY / `TERM=dumb` environments using standard line input with `[Y/N/T]`.
- Allow `--yes` (`auto_approve=True`) to bypass the confirmation gate for automated CI/testing runs.
- Cancelling via `[N]`, `Escape`, or `Ctrl+C` must immediately abort leaving the disk completely untouched.
- Enforce Pure Hexagonal Architecture (AD-1): `ProvisioningFlow` communicates through `TerminalUIPort` and uses `TweakHandler` without importing adapter implementations.

**Never:**
- Never commit partial or unconfirmed files to disk on tweak errors or session aborts.
- Never lose previous consecutive tweaks when applying a new refinement in the loop.
- Never invoke `terraform apply` or execute remote cloud API calls (AD-4, AD-5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Commit immediately | User selects `[Y] Commit` on initial diff preview | Writes workspace files atomically to disk | N/A |
| Cancel immediately | User selects `[N] Cancel` or presses `Ctrl+C` | Exits cleanly, 0 files written to disk | Typer abort / no disk changes |
| Single tweak then commit | User selects `[Tweak]`, inputs "Change replication to GRS", then selects `[Y] Commit` | Diff re-renders showing `+ account_replication_type = "GRS"`, then commits | Validated before commit |
| Multiple consecutive tweaks | User applies tweak 1 (TLS), then tweak 2 (tags), then selects `[Y] Commit` | Diff shows both TLS and tag modifications; all changes committed atomically | Caches updated in memory |
| Failed tweak in loop | User enters invalid tweak ("Make it fast") | Displays descriptive error banner, re-presents confirmation gate with unchanged diff | Does not corrupt workspace |
| Headless execution | `auto_approve=True` (`--yes`) | Skips interactive gate, commits diff immediately | Bypasses prompt |
| Non-TTY environment | `is_interactive() == False` | Line-oriented input `Action [Y/n/t]: ` | Defaults to commit or cancel |

</frozen-after-approval>

## Code Map

- `ttassistant/ports/terminal.py` -- Add `prompt_confirmation_gate(self, prompt: str = ...) -> str` and `clear_screen(self) -> None` to `TerminalUIPort`.
- `ttassistant/adapters/terminal_adapter.py` -- Implement Questionary 3-way select (`Commit`, `Tweak`, `Cancel`) and line-oriented fallback in `RichTerminalAdapter`.
- `ttassistant/application/provisioning_flow.py` -- Update diff review loop in `ProvisioningFlow.run()` to orchestrate `tweak_handler.apply_tweak()`, diff re-computation, and re-rendering.
- `ttassistant/cli.py` -- Inject `DeterministicTweakParserAdapter` and `TweakHandler` into `ProvisioningFlow` inside `ttassistant new`.
- `tests/test_tweak_loop.py` -- Automated unit and integration tests verifying the interactive tweak loop, multi-turn refinements, diff re-rendering, and cancellation semantics.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/ports/terminal.py` -- Add `prompt_confirmation_gate` to `TerminalUIPort` -- Defines port contract for 3-way confirmation gate.
- [x] `ttassistant/adapters/terminal_adapter.py` -- Implement `prompt_confirmation_gate` in `RichTerminalAdapter` -- Interactive Questionary menu and non-TTY line input fallback.
- [x] `ttassistant/application/provisioning_flow.py` -- Implement interactive tweak loop with dynamic diff re-calculation and `TweakHandler` orchestration -- Application flow loop.
- [x] `ttassistant/cli.py` -- Wire `DeterministicTweakParserAdapter` and `TweakHandler` into `ProvisioningFlow` in CLI `new` command -- Production CLI injection.
- [x] `tests/test_tweak_loop.py` -- Comprehensive test suite covering multi-tweak iterations, diff re-rendering, error recovery, and cancellation -- Verification.

**Acceptance Criteria:**
- Given a staged workspace diff displayed in the terminal, when the confirmation gate appears, then the user is presented with `[Y] Commit`, `[N] Cancel`, and `[Tweak] Enter refinement`.
- Given the user selects `[Tweak]` and enters `"Change replication to GRS"`, then the diff is re-calculated in memory and displayed with updated modifications, and the confirmation gate is re-presented.
- Given multiple consecutive tweaks are entered (e.g. replication change followed by tag addition), then all modifications accumulate in `StagedWorkspace` and appear in the diff.
- Given the user enters an unparseable tweak, then an error banner is displayed and the loop re-presents the gate without crashing or corrupting files.
- Given the user selects `[N] Cancel` at any point during the loop, then the session terminates immediately leaving the disk untouched.
- Given `--yes` (`auto_approve=True`), then the confirmation loop is bypassed and the workspace is committed directly.

## Implementation Notes
- Pure Hexagonal Architecture adherence:
  - `ttassistant/ports/terminal.py`: Added `prompt_confirmation_gate` (3-way `[Y] Commit / [N] Cancel / [T] Tweak`) and `clear_screen`.
  - `ttassistant/adapters/terminal_adapter.py`: Implemented `prompt_confirmation_gate` with Questionary interactive select and non-TTY line input fallback, plus `clear_screen`.
  - `ttassistant/application/tweak_handler.py`: Strict layer isolation (AD-1) requiring `parser: TweakParserPort` without importing adapter implementations.
  - `ttassistant/application/provisioning_flow.py`: Implemented dynamic `while True` confirmation loop that coordinates `tweak_handler`, re-computes unified diff, clears screen between turns, and commits atomically on confirmation or aborts cleanly leaving disk untouched.
  - `ttassistant/cli.py`: Wired `DeterministicTweakParserAdapter(catalog=catalog)` and `TweakHandler(parser=tweak_parser, catalog=catalog)` into `ProvisioningFlow`.
- Security Policy Gate (AD-7):
  - In `ProvisioningFlow.run`, conversational tweaks enabling `public_network_access_enabled = true` on Tier 1 PaaS services automatically trigger the critical security warning gate, requiring explicit user override; if rejected, the tweak is automatically reverted to secure private-only state.
- Automated Verification:
  - 442 tests passing across entire test suite with 100% pass rate.

## Spec Change Log

## Review Triage Log
| Lens | Finding | Verdict | Evidence / Resolution |
| :--- | :--- | :--- | :--- |
| Verification Gap | `display_diff` call assertions in `test_tweak_loop.py` only checked call count, not the actual rendered diff text content. | high | Updated `test_single_tweak_then_commit` and `test_multiple_consecutive_tweaks_then_commit` to assert that refined attribute lines appear in the post-tweak diff preview. |
| Verification Gap | Production CLI `ttassistant new` wiring of `TweakHandler` was untested via CLI runner. | high | Added `test_cli_new_interactive_tweak_refinement_committed_to_disk` in `tests/test_cli_new.py` asserting non-TTY tweak entry `t` and verification of disk output. |
| Verification Gap | `RichTerminalAdapter.prompt_confirmation_gate` cancellation via Escape (`None`) or Ctrl+C (`KeyboardInterrupt`) lacked unit test coverage. | medium | Added `test_interactive_confirmation_gate_abort_on_none` and `test_interactive_confirmation_gate_keyboard_interrupt` in `tests/test_tweak_loop.py`. |
| Edge Case Hunter | `TweakHandler.apply_tweak` unconditionally assigned `workspace.metadata["last_tweak"]` and `tweak_applied = True` before checking `if not modified`. | high | Fixed in `ttassistant/application/tweak_handler.py`: moved metadata assignment inside `if modified` block; returns failure without modifying metadata on unapplied tweaks. |
| Edge Case Hunter | Enabling public network access on Tier 1 PaaS via conversational tweak bypassed the AD-7 corporate security warning gate. | high | Fixed in `ttassistant/application/provisioning_flow.py`: added security gate evaluation in tweak loop; triggers warning banner and requires confirmation, reverting if rejected. |
| Edge Case Hunter | `stdin.isatty()` in `RichTerminalAdapter.is_interactive` could raise unhandled `ValueError` when called on a closed stream. | low | Fixed in `ttassistant/adapters/terminal_adapter.py`: wrapped `isatty()` call in `try / except (AttributeError, ValueError)`. |
| Blind Hunter | `clear_screen()` in `RichTerminalAdapter` was inappropriately gated on `is_color_supported()` rather than terminal interactivity. | medium | Fixed in `ttassistant/adapters/terminal_adapter.py`: updated `clear_screen` to check `self.is_interactive()`. |
| Blind Hunter | `clear_screen()` was never called in the diff review loop in `ProvisioningFlow.run`, causing diff previews to stack on each turn. | medium | Fixed in `ttassistant/application/provisioning_flow.py`: invoked `self.terminal.clear_screen()` on loop iterations > 0. Verified via `test_clear_screen_called_in_provisioning_flow`. |
| Blind Hunter | `TweakHandler.apply_tweak` hardcoded fallback to `main.tf` even when target resource was declared in other files. | low | Fixed in `ttassistant/application/tweak_handler.py`: added search for `.tf` files containing resource definitions if target file is not found. |

## Design Notes

### Confirmation Gate Prompt Design
In interactive mode:
- Options:
  - `[Y] Commit changes to disk` -> `"commit"`
  - `[Tweak] Enter conversational refinement` -> `"tweak"`
  - `[N] Cancel and discard` -> `"cancel"`
In non-interactive / dumb mode:
- Plain prompt: `Action [Y] Commit / [N] Cancel / [T] Tweak: `

### Tweak Loop State Management
In `ProvisioningFlow.run()`:
```python
while True:
    workspace_diff = compute_workspace_diff(workspace, existing_files)
    self.terminal.display_diff(workspace_diff.diff_text)
    choice = self.terminal.prompt_confirmation_gate()
    if choice == "commit":
        # Commit workspace atomically
        break
    elif choice == "cancel":
        # Cancel without disk modification
        break
    elif choice == "tweak":
        tweak_str = self.terminal.prompt_text("Enter refinement instruction:")
        result = self.tweak_handler.apply_tweak(workspace, tweak_str)
        if result.success:
            self.terminal.print_success(f"Applied tweak: {result.diff_summary}")
        else:
            self.terminal.print_error(f"Tweak failed: {result.error_message}")
```

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_tweak_loop.py -v` -- expected: all tweak loop tests pass.
- `./.venv/bin/pytest` -- expected: full test suite passes without regressions.

