---
title: 'Story 1.5: Unified Terminal Diff Preview, Human Confirmation Gate & Atomic Disk Writes'
type: 'feature'
created: '2026-09-23'
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

**Problem:** Infrastructure developers risk corrupting existing Terraform states or accidentally modifying monorepo files when automated tools execute uninspected disk writes or lack atomic transaction rollbacks, and developers must be assured that no unauthorized `terraform apply` operations occur.

**Approach:** Implement a pure-Python in-memory diff engine in `ttassistant.domain.diff`, a robust atomic filesystem adapter with sibling `.tmp` writes, `os.fsync`, and atomic `os.replace` rollbacks in `ttassistant.adapters.fs_adapter`, and wire a color-coded unified terminal diff preview and explicit confirmation gate `[Y] Commit / [N] Cancel` into the scaffolding workflow.

## Boundaries & Constraints

**Always:**
- Keep pure business domain packages (`ttassistant.domain.diff`, `ttassistant.domain.models`) strictly decoupled from terminal UI and physical filesystem I/O dependencies (AD-1).
- Compute unified diffs using standard library `difflib` in pure memory comparing existing file state against in-memory `StagedWorkspace` (AD-1, FR-15).
- Display a color-coded unified terminal diff matching the exact bytes to be written (additions in green, removals in red) in TTY environments, and plain text in non-TTY environments (FR-15, NFR-1).
- Present an explicit human confirmation gate: `[Y] Commit / [N] Cancel` before writing any bytes to disk (FR-15, AD-5).
- Selecting `[N]` or pressing Ctrl+C must exit cleanly leaving the working directory completely untouched.
- Selecting `[Y]` (or passing `--yes` flag) must commit all files atomically across target directories: write to hidden sibling `.tmp` files, flush with `os.fsync`, and swap with `os.replace` (AD-5, NFR-7).
- Any disk write or I/O failure must trigger an immediate rollback of all modified/created files in the transaction and clean up temporary files (AD-5).

**Never:**
- Under no circumstances invoke `terraform apply` or live cloud deployments (AD-5).
- Never perform in-place partial writes or leave orphaned `.tmp` files on disk if an operation is aborted or fails (AD-5).
- Never write files to disk without explicit human confirmation or an explicit `--yes` CLI flag.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Greenfield Diff Preview | Staged greenfield workspace (`main.tf`, `data.tf`, `backend.tf`) | Displays unified diff for all 3 files showing additions (`+`) in green from `/dev/null` | N/A |
| User Confirms Scaffolding | User answers `[Y]` or `--yes` provided | Atomically writes all files to target path `<resource-type>/<subscription>/`, reports success | Exit code 0 |
| User Cancels Scaffolding | User answers `[N]` | Displays "Scaffolding cancelled. No files written to disk.", working directory remains untouched | Exit code 0 |
| User Aborts via Ctrl+C | KeyboardInterrupt during confirmation | Aborts cleanly, no partial files or `.tmp` files created on disk | Exit code 130 / Typer.Abort |
| Disk Write Failure / Permission Error | Write error or OS error on 2nd file in transaction | Rolls back previously swapped files in transaction, removes all `.tmp` files, leaves clean directory | Raises `FileSystemError`, exits code 1 |
| Sibling `.tmp` and `os.fsync` Persistence | Writing files in transaction | Each file staged to `.<filename>.<uuid>.tmp`, flushed, fsynced, then atomically swapped with `os.replace` | N/A |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/diff.py` -- Pure domain logic for generating unified diff strings and structured file diffs between disk files and in-memory `StagedWorkspace` using Python's `difflib`.
- `ttassistant/ports/filesystem.py` -- Define `FileSystemPort` protocol specifying atomic workspace commitment, file reading, and existence checks.
- `ttassistant/adapters/fs_adapter.py` -- Implement `DiskFileSystemAdapter(FileSystemPort)` providing sibling `.tmp` writes, `os.fsync`, atomic `os.replace`, and multi-file transaction rollback.
- `ttassistant/adapters/terminal_adapter.py` -- Ensure `display_diff` and `confirm` properly render color-coded diff syntax and handle prompt options with Ctrl+C abortion.
- `ttassistant/application/provisioning_flow.py` -- Wire diff generation, terminal diff preview, confirmation gate, and atomic disk commit into `ProvisioningFlow.run`.
- `ttassistant/cli.py` -- Add `--yes` / `-y` flag to `ttassistant new` and execute atomic provisioning flow.
- `tests/test_diff.py` -- Unit tests for domain diff calculation across greenfield and existing files.
- `tests/test_fs_adapter.py` -- Unit tests for atomic filesystem writes, sibling `.tmp` files, `os.fsync`, and transaction rollback on failure.
- `tests/test_provisioning_flow.py` -- Integration tests for provisioning flow diff preview, confirmation [Y], rejection [N], and atomic persistence.
- `tests/test_cli_new.py` -- CLI tests for `ttassistant new` with confirmation prompt, `--yes` flag, and cancellation.
- `tests/test_architecture.py` -- Verify domain boundary isolation for `ttassistant.domain.diff`.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/diff.py` -- Implement pure-Python domain diff engine for computing unified diffs for `StagedWorkspace`.
- [x] `ttassistant/ports/filesystem.py` -- Define `FileSystemPort` interface for filesystem reading and atomic workspace commits.
- [x] `ttassistant/adapters/fs_adapter.py` -- Implement `DiskFileSystemAdapter` with hidden sibling `.tmp` writes, `os.fsync`, `os.replace`, and rollback on error.
- [x] `ttassistant/adapters/terminal_adapter.py` -- Verify and enhance `display_diff` and `confirm` for diff preview and confirmation gates.
- [x] `ttassistant/application/provisioning_flow.py` -- Connect diff display, confirmation gate, and atomic filesystem commit.
- [x] `ttassistant/cli.py` -- Add `--yes` flag and wire atomic scaffolding execution in `new` command.
- [x] `tests/test_diff.py` -- Test diff engine with new files, modified files, and empty workspaces.
- [x] `tests/test_fs_adapter.py` -- Test atomic file writing, sibling temp files, and rollback on injected I/O failures.
- [x] `tests/test_provisioning_flow.py` & `tests/test_cli_new.py` -- Test end-to-end confirmation, `--yes`, cancellation, and terminal diff output.
- [x] `tests/test_architecture.py` -- Assert AD-1 domain layer purity for `diff.py`.

**Acceptance Criteria:**
- Given staged Terraform files held in `StagedWorkspace` memory, when the scaffolding flow reaches review, then the CLI renders a unified terminal diff showing additions (+) in green and context lines matching the exact bytes to be written.
- The CLI prompts the user with an explicit confirmation gate: `[Y] Commit / [N] Cancel`.
- Selecting `[N]` or pressing Ctrl+C exits cleanly leaving the working directory completely untouched.
- Selecting `[Y]` (or `--yes`) atomically writes all files by writing to hidden `.tmp` sibling files, flushing via `os.fsync`, and swapping via `os.replace`.
- Any disk write failure triggers an immediate rollback leaving no orphaned temporary or corrupt files.
- Under no circumstances does the CLI invoke `terraform apply` or live cloud deployments.

## Implementation Notes

- Added `FileSystemError` domain exception in `ttassistant.domain.exceptions`.
- Implemented pure-Python domain diff engine in `ttassistant.domain.diff` (`compute_file_diff`, `compute_workspace_diff`, `FileDiff`, `WorkspaceDiff`) using standard library `difflib`.
- Defined `@runtime_checkable` `FileSystemPort` protocol in `ttassistant.ports.filesystem`.
- Implemented `DiskFileSystemAdapter` in `ttassistant.adapters.fs_adapter` with hidden sibling temporary files (`.tmp.<uuid>`), `os.fsync`, atomic `os.replace` swap, and multi-file transaction rollback restoring backups on failure.
- Updated `RichTerminalAdapter` in `ttassistant.adapters.terminal_adapter` with syntax-highlighted diff rendering and clean EOF/KeyboardInterrupt abort handling.
- Integrated diff preview, human confirmation gate (`[Y] Commit / [N] Cancel`), and atomic write into `ProvisioningFlow.run` in `ttassistant.application.provisioning_flow`.
- Added `--yes` / `-y` flag to `ttassistant new` in `ttassistant/cli.py`.
- Expanded test suite with `tests/test_diff.py`, `tests/test_fs_adapter.py`, and updated integration/architecture tests, achieving 192 passing tests.

## Spec Change Log

## Review Triage Log

- `ttassistant/domain/diff.py`: Empty string in existing files treated as falsy — Verdict: `low` — Patched: checked `key in existing_files` in `compute_workspace_diff`.
- `ttassistant/domain/diff.py`: Trailing newline differences masked by `splitlines()` — Verdict: `low` — Patched: used `splitlines(keepends=True)`.
- `ttassistant/domain/diff.py`: Populating `from_lines` when `file_is_new=True` with non-empty existing content — Verdict: `low` — Patched: forced `from_lines = []` when `file_is_new=True`.
- `ttassistant/adapters/fs_adapter.py`: Path traversal and workspace escape vulnerability — Verdict: `medium` — Patched: enforced `dest_path.is_relative_to(target_base.resolve())`.
- `ttassistant/adapters/fs_adapter.py`: Existing file mode/permissions wiped by atomic swap — Verdict: `low` — Patched: copied file mode from existing file with `shutil.copymode(dest_path, temp_path)`.
- `ttassistant/adapters/fs_adapter.py`: Orphaned partial `.bak` file left if copy fails — Verdict: `low` — Patched: added cleanup of `backup_path` if `shutil.copy2` fails midway.
- `ttassistant/adapters/fs_adapter.py`: Target base directory might not exist — Verdict: `low` — Patched: ensured `target_base.mkdir(parents=True, exist_ok=True)`.
- `ttassistant/adapters/terminal_adapter.py`: Syntax theme forced dark rectangular box in light terminals and soft-wrapped lines — Verdict: `low` — Patched: used `background_color="default", padding=0` and avoided soft wrapping in non-TTY.
- `ttassistant/adapters/terminal_adapter.py`: Numeric choice strings in `prompt_select` rejected — Verdict: `low` — Patched: checked `if line in choices: return line` before integer index parsing.
- `ttassistant/application/provisioning_flow.py`: Empty diff displayed no feedback and prompt duplicated yes/no markers — Verdict: `low` — Patched: displayed info when files on disk are identical, cleaned up confirmation prompt string to `"Commit changes to disk?"`.
- `tests/test_fs_adapter.py`: Rollback restoration of pre-existing file test failed on 2nd file before reaching 3rd file — Verdict: `low` — Patched: seeded pre-existing file on 1st file (`backend.tf`) and verified rollback restoration.
- `tests/test_provisioning_flow.py`: Missing diff preview verification against existing files on disk — Verdict: `low` — Patched: added integration test asserting diff against existing file content.
- `tests/test_cli_new.py`: Missing CLI error handling for `FileSystemError` and assertion that `terraform` binary is never called — Verdict: `low` — Patched: added CLI tests verifying exit code 1 and confirming zero external binary calls.

## Design Notes

- Diff generation uses `difflib.unified_diff` with standard `/dev/null` source headers for new files to ensure native syntax highlighting compatibility in Rich's `Syntax(..., "diff")`.
- Sibling `.tmp` files are created in the exact same target directory as the destination file (e.g. `<dir>/.<filename>.<uuid>.tmp`) to guarantee they reside on the same filesystem mount point, ensuring `os.replace` is an atomic inode swap rather than a cross-device copy.
- The rollback journal tracks all created directories, temporary files, and swapped files so that upon any exception during the write phase, previously swapped files are restored from backup or unlinked, preventing partial writes.

## Verification

**Commands:**
- `./.venv/bin/pytest` -- expected: All unit, integration, and architecture tests pass (100% pass rate).
- `./.venv/bin/python -m ttassistant new --subscription sub-prod --resource-type azurerm_storage_account --workload appdata --yes` -- expected: Displays unified diff, writes files atomically to `azurerm_storage_account/sub-prod/`, and verifies files exist on disk.

