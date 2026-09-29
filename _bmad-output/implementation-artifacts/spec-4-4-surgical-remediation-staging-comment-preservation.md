---
title: 'Story 4.4: Surgical Remediation Staging & Comment Preservation'
type: 'feature'
created: '2026-09-28'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/implementation-artifacts/epic-4-context.md'
  - 'ttassistant/domain/compliance.py'
  - 'ttassistant/domain/patcher.py'
  - 'ttassistant/application/remediation_flow.py'
  - 'ttassistant/cli.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When existing Terraform directories drift from corporate standards, developers can discover violations using `ttassistant remediate --check` (Story 4.3). However, manually applying fixes is error-prone, and automated AST re-serialization (e.g. naive parsing and emitting) destroys developer comments, strips inline documentation, alters custom indentation, and risks clobbering unmanaged resource blocks. Infrastructure teams need an automated, surgical remediation engine that stages non-destructive corrective patches in memory, previews the unified diff, and commits atomic file updates only upon explicit human approval.

**Approach:** Implement a surgical text-level remediation patcher in `ttassistant.domain.patcher` that performs targeted line insertions and attribute replacements. Integrate this patcher into `RemediationFlow` in `ttassistant.application.remediation_flow` to stage in-memory file buffers within `StagedWorkspace`. When `ttassistant remediate <path>` runs without `--check`, it audits the folder, stages surgical corrections (inserting missing tags into `tags = { ... }`, setting `public_network_access_enabled = false`, or appending companion `azurerm_private_endpoint` blocks), presents the colorized terminal diff, and prompts the human confirmation gate before committing via atomic file replacement (`os.replace`).

## Boundaries & Constraints

**Always:**
- 100% preserve existing file comments (`# ...`, `// ...`, `/* ... */`), custom variable references, unmanaged resource blocks, and original indentation during surgical patching (AD-2, AD-5).
- Stage all remediation modifications in-memory within `StagedWorkspace` before touching disk (AD-5).
- Require explicit human confirmation (`[Y]` or `--yes`) on the rendered unified diff before committing changes to disk.
- Execute disk commits via atomic rename (`.tmp` sibling staging, `os.fsync`, and `os.replace`) with automatic rollback on failure (AD-5, NFR-7).
- If `public_network_access_enabled` is missing on Tier 1 PaaS, surgically inject `public_network_access_enabled = false` matching surrounding indentation.
- If `public_network_access_enabled = true` (or truthy/non-denial string), surgically replace it in-place with `public_network_access_enabled = false`.
- If missing mandatory tags are detected, inject missing key/value pairs into existing `tags = { ... }` blocks with matching indentation, or create a clean `tags = { ... }` block if none exists.
- If a companion Private Endpoint is absent for a Tier 1 PaaS resource, synthesize and append an `azurerm_private_endpoint` block referencing the target resource and Hub Private DNS zone group.
- Aborting via `[N]`, `Escape`, or `Ctrl+C` must immediately exit with status code 0 or 130 leaving disk contents 100% untouched.

**Never:**
- Never use naive AST re-serialization (`hcl2.dump()` or destructive AST writers) that wipes out comments or reformats unmanaged lines.
- Never write directly to target `.tf` files without atomic sibling staging (`.tmp` + `os.replace`).
- Never invoke external `terraform apply` or perform automated live cloud deployments (AD-2, NFR-5).
- Never modify files if zero compliance violations were detected (exit cleanly with 100% compliant banner).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Non-compliant legacy folder | Storage account missing tags and public access enabled, user runs `ttassistant remediate .` | Stages surgical patches, renders unified terminal diff with green additions and red replacements, prompts `Action: [Y] Commit / [N] Cancel` | On `N` / abort, disk unchanged |
| Comments in target `.tf` file | Target file contains header comments, block comments, and inline `#` notes | Patched file 100% preserves every comment character and blank line intact | Zero comment loss |
| Missing tags injection | `tags = { ... }` block exists with 1 existing tag | Appends missing tags before closing `}`, matching indentation of existing tag | Valid HCL tags block |
| Missing tags block creation | Resource block has no `tags` attribute at all | Injects a new `tags = { ... }` block inside resource before closing `}` | Valid HCL resource block |
| Public access toggle in-place | Line has `public_network_access_enabled = true` | Surgically replaces `true` with `false`, preserving indentation and inline comments | Line-level replacement |
| Public access missing injection | Tier 1 PaaS lacks `public_network_access_enabled` line | Injects `public_network_access_enabled = false` after resource opening line | Preserves resource layout |
| Companion Private Endpoint append | PaaS resource lacks private endpoint | Appends companion `azurerm_private_endpoint` block to `main.tf` with Hub Private DNS zone group | Appends valid companion block |
| Auto-approve flag (`--yes` / `-y`) | User runs with `--yes` in non-interactive environment | Bypasses interactive confirmation gate, applies atomic commit immediately, exits code 0 | Headless execution |
| Human rejects changes (`[N]`) | User selects `[N]` or enters `n` | Prints `Remediation cancelled. Disk left untouched.` and exits code 0 | Zero filesystem changes |
| Fully compliant folder | Directory has 0 compliance violations | Prints `100% compliant with corporate standards` banner, stages 0 diffs, exits code 0 | No unnecessary writes |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/patcher.py` -- Pure domain service for surgical, comment-preserving HCL text patching (`patch_public_network_access`, `patch_tags`, `generate_private_endpoint_block`).
- `ttassistant/application/remediation_flow.py` -- Orchestrate `stage_remediation()`, unified diff generation via `StagedWorkspace`, human confirmation gate, and atomic commit via `FileSystemPort`.
- `ttassistant/cli.py` -- Wire `remediate` command to support interactive staging, `--yes` / `-y` auto-approval, and diff preview.
- `tests/test_remediation_staging.py` -- Comprehensive unit and integration test suite covering comment preservation, surgical attribute replacements, tag injections, companion PE synthesis, atomic commit rollback, and CLI workflows.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/patcher.py` -- Implement surgical HCL text patcher functions preserving all comments, indentation, and unmanaged blocks -- Pure domain patcher.
- [x] `ttassistant/application/remediation_flow.py` -- Implement `stage_remediation()`, interactive diff preview, confirmation gate, and atomic commit -- Remediation flow execution.
- [x] `ttassistant/cli.py` -- Update `remediate` CLI command to support remediation application and `--yes` auto-approve flag -- CLI command enhancement.
- [x] `tests/test_remediation_staging.py` -- Implement comprehensive tests for comment preservation, surgical tagging, public access toggle, companion PE generation, and atomic disk writes -- Verification.

**Acceptance Criteria:**
- Given an existing directory containing non-compliant Terraform configurations, when `ttassistant remediate <path>` executes without `--check`, then it stages corrective patches as an in-memory `StagedWorkspace`.
- Given a file with comments before, inside, or after resource blocks, when surgical patching executes, then all comments and unmanaged code are 100% preserved.
- Given a Tier 1 PaaS resource with public access enabled or missing denial, then it surgically sets `public_network_access_enabled = false`.
- Given a resource with missing mandatory tags, then missing tags are surgically injected into `tags = { ... }` or a new `tags` block is created with proper indentation.
- Given a Tier 1 PaaS resource lacking a companion private endpoint, then a companion `azurerm_private_endpoint` block is synthesized and appended.
- Given human confirmation (`[Y]` or `--yes`), then changes are committed to disk via atomic swap (`os.replace`) with zero live `terraform apply`.
- Given rejection (`[N]`), then the process exits leaving disk contents completely untouched.

## Implementation Notes

- Implemented pure Hexagonal domain service in `ttassistant/domain/patcher.py` providing `find_resource_block_lines`, `patch_public_network_access`, `patch_tags`, and `generate_companion_private_endpoint` with zero external dependencies (AD-1, AD-2).
- Designed non-destructive text patching routines that preserve 100% of existing inline `#`, `//`, and `/* ... */` comments, block comments, and custom indentation.
- Extended `RemediationFlow.stage_remediation` in `ttassistant/application/remediation_flow.py` to synthesize in-memory `StagedWorkspace` without touching target files on disk.
- Implemented human confirmation gate in `RemediationFlow.run_remediation` presenting unified diff preview and committing via atomic `.tmp` swap and rollback on `FileSystemPort.commit_workspace()`.
- Added `--yes` / `-y` headless auto-approval override in `ttassistant/cli.py` and handled `typer.Abort` to cleanly exit code 0 leaving disk untouched.

## Spec Change Log

- None.

## Review Triage Log

- **Verification Gap Reviewer**:
  - *Finding 1 (Omitted PNA attribute integration test)*: Added `test_stage_remediation_omitted_public_network_access_attribute` in `tests/test_remediation_staging.py` verifying `RemediationFlow` handles `MISSING_PUBLIC_NETWORK_ACCESS_DENIAL`. -> **Fixed**.
  - *Finding 2 (INVALID_TAG_VALUE omitted in stage_remediation)*: Updated `remediation_flow.py` to include `ComplianceViolationType.INVALID_TAG_VALUE` during violation grouping and added `test_stage_remediation_handles_invalid_tag_value`. -> **Fixed**.
- **Edge Case Hunter**:
  - *Finding 1 (Single-line resource block expansion)*: Added `_expand_single_line_resource` in `ttassistant/domain/patcher.py` ensuring single-line blocks are cleanly expanded into valid multi-line HCL without placing attributes outside the block. -> **Fixed**.
  - *Finding 2 (Multi-line C-style comment braces)*: Added multi-line block comment state tracking (`/* ... */`) in `find_resource_block_lines` so braces inside block comments do not corrupt resource boundary calculation. -> **Fixed**.
  - *Finding 3 (Dynamic tag assignments)*: Added guard in `patch_tags` to detect non-map tag assignments (`tags = var.tags` / `tags = merge(...)`) and prevent injecting duplicate conflicting `tags` blocks. -> **Fixed**.
  - *Finding 4 (Quoted tag keys & trailing commas)*: Updated `patch_tags` regex to match and preserve quoted keys (`"Environment" = ""`) and maintain trailing commas. -> **Fixed**.
  - *Finding 5 (Enforce port injections)*: Added explicit checks raising `RuntimeError` in `inspect_directory` if `hcl_parser` is None and in `run_remediation` if `fs` is None. -> **Fixed**.
- **Blind Hunter**:
  - *Finding 1 (Arithmetic: N=9)*: Fixed tag value replacement and comma preservation, single-line resource handling, and dynamic tag guards as described above. -> **Fixed**.

## Design Notes

- Surgical patching strictly avoids destructive AST parsers (`hcl2.dump()` re-serialization) to adhere to NFR-5 and AD-5, ensuring enterprise formatting, comments, and variable references are preserved with zero loss.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_remediation_staging.py -v` -- 36/36 tests passed.
- `./.venv/bin/pytest tests/test_architecture.py -v` -- 17/17 tests passed (zero architectural boundary violations).
- `./.venv/bin/pytest` -- 506/506 passed in 23.96s across the entire repository.

