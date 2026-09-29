---
title: 'Story 2.3: Collaborative Subnet Selection & Missing Dependency Scaffolding'
type: 'feature'
created: '2026-09-24'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md'
  - '_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When scaffolding cloud infrastructure requiring internal network integration (such as Private Endpoints for Azure PaaS), developers face guesswork and friction locating existing subnets, while repositories lacking network definitions force developers to manually author boilerplate networking code in separate folders before returning to their workload.

**Approach:** Integrate monorepo topology discovery into `ProvisioningFlow`: present discovered candidate subnets in an interactive selection prompt displaying CIDRs and purpose, highlight standards-compliant subnets with `(Recommended)` as default, offer proactive scaffolding of missing subnet/VNet definitions or cross-subscription shared network lookups when none exist, and stage all affected directories together in `StagedWorkspace` for a single unified diff and atomic multi-directory commit.

## Boundaries & Constraints

**Always:**
- Keep pure business logic (`StagedWorkspace`, `ProvisioningParameters`, `ScaffoldEngine`) in `ttassistant.domain`, strictly decoupled from terminal UI and filesystem I/O (AD-1).
- Present discovered candidate subnets formatted with names, CIDR address prefixes, parent VNet/RG, and purpose (AD-2, UX-DR3).
- Prioritize and flag subnets matching `common_standards/networking_policy.md` or Private Endpoint heuristics with `(Recommended)` and select as the prompt default (FR-6, UX-DR3).
- If no candidate subnet exists in the target subscription, present guided options: (1) Scaffold missing subnet in its designated networking directory, or (2) Configure cross-subscription shared network lookup (FR-6).
- When scaffolding a missing subnet alongside target workload resources, stage both directory hierarchies (`<resource-type>/<subscription>/` and `azurerm_subnet/<subscription>/` or `virtual-networks/<subscription>/`) in `StagedWorkspace` for a unified terminal diff preview and single atomic commit (AD-5, FR-6, NFR-7).
- Support headless CLI parameter `--subnet <name>` in `ttassistant new` to allow non-interactive selection in automated pipelines.
- Degrade gracefully to plain-text line-based prompts in non-TTY or `TERM=dumb` environments (UX-DR1).

**Never:**
- Never invoke external `terraform` or `az` CLI binaries (FR-3, NFR-5).
- Never commit partial writes across directories; multi-directory commits must be 100% atomic with full rollback on failure (AD-5, NFR-7).
- Never hardcode resource IDs or remote state references into scaffolded network definitions (AD-3, FR-7).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Multiple Candidate Subnets | Target subscription has 3 candidate subnets; 1 matches standards patterns | CLI prompts numbered menu; recommended subnet highlighted with `(Recommended)` as default; user selects choice | If user aborts, raises `typer.Abort` |
| Single Candidate Subnet | Target subscription has exactly 1 candidate subnet matching standards | CLI presents choice with `(Recommended)` as default | User can select or enter custom |
| Pre-seeded Subnet Flag | CLI runs with `--subnet snet-pe-01` matching an existing discovered subnet | Bypasses interactive subnet prompt, binds `snet-pe-01` | If pre-seeded subnet not found, warns or validates cleanly |
| No Candidate Subnets (Scaffold Option) | Target subscription has 0 subnets; user chooses to scaffold missing subnet | Prompts for subnet name and CIDR; synthesizes `azurerm_subnet` definition in `azurerm_subnet/<subscription>/main.tf`; stages both folders in `StagedWorkspace` | Validates subnet name against naming conventions |
| No Candidate Subnets (Cross-Sub Option) | Target subscription has 0 subnets; user chooses cross-subscription lookup | Prompts for source subscription and shared subnet name; records cross-subscription binding in parameters | Validates source subscription against backend/naming rules |
| Multi-Directory Atomic Commit | Staged workspace contains files across 2 directories; commit confirmed | Both directories written atomically via sibling `.tmp` and `os.replace`; diff preview shows files from both directories | Rollback restores existing files and cleans temp files across all directories on error |
| Non-TTY Environment | Stdin is not a TTY or `TERM=dumb` | Degrades to indexed plain-text line input or default recommended selection | Handles EOFError/ValueError gracefully |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/models.py` -- Enhance `StagedWorkspace` to support multi-directory file keys (`staged_file.path`) and extend `ProvisioningParameters` with `selected_subnet` and `network_action`.
- `ttassistant/domain/scaffold.py` -- Add `scaffold_subnet` method to synthesize standards-compliant `azurerm_subnet` resource blocks.
- `ttassistant/ports/terminal.py` -- Add `prompt_select_subnet` or extend `prompt_select` to support formatted choices with annotations and default index.
- `ttassistant/adapters/terminal_adapter.py` -- Implement subnet choice rendering and default selection in `RichTerminalAdapter`.
- `ttassistant/adapters/fs_adapter.py` -- Verify multi-directory atomic staging in `commit_workspace` and `read_workspace_existing_files`.
- `ttassistant/application/provisioning_flow.py` -- Integrate topology discovery (`HCLParserPort`), subnet selection prompt, missing subnet scaffolding, and multi-directory staging.
- `ttassistant/cli.py` -- Add `--subnet` option to `ttassistant new`.
- `tests/test_subnet_selection.py` -- Unit and integration tests covering subnet selection prompt, recommended defaults, missing subnet scaffolding, cross-subscription lookup, and multi-directory staging.
- `tests/test_architecture.py` -- Verify AD-1 domain isolation and ports protocols.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/models.py` -- Update `StagedWorkspace.add_file` to key by `staged_file.path` preventing cross-directory collisions, and add `selected_subnet`, `network_action`, `cross_sub_source` fields to `ProvisioningParameters`.
- [x] `ttassistant/domain/scaffold.py` -- Add `scaffold_subnet` to generate compliant `azurerm_subnet` configuration files with isolated backend and tags.
- [x] `ttassistant/ports/terminal.py` & `ttassistant/adapters/terminal_adapter.py` -- Add or enhance subnet selection prompt support with `(Recommended)` annotations and default selection index.
- [x] `ttassistant/application/provisioning_flow.py` -- Wire topology discovery, candidate subnet selection, and missing dependency scaffolding into guided dialogue flow.
- [x] `ttassistant/cli.py` -- Add `--subnet` option to `new` command and pass filesystem/parser dependencies to `ProvisioningFlow`.
- [x] `tests/test_subnet_selection.py` -- Comprehensive test suite covering candidate selection, recommendation ranking, missing subnet scaffolding, cross-subscription lookup, and multi-directory commit.
- [x] `tests/test_architecture.py` -- Confirm architectural boundaries remain intact.

**Acceptance Criteria:**
- Given discovered candidate subnets for the target subscription.
- When multiple candidate subnets are available, the CLI presents an interactive prompt showing subnet names, CIDRs, and purpose, highlighting subnets matching `common_standards/` recommendations with `(Recommended)` as default.
- If no candidate subnet exists within the subscription, the CLI prompts options to either scaffold a missing subnet definition in its designated networking directory or wire a cross-subscription shared network lookup.
- If the developer elects to scaffold a missing subnet, the missing network configuration is added to `StagedWorkspace` for multi-directory atomic staging and commit.

## Implementation Notes

- **StagedWorkspace Multi-Directory Support**: Modified `StagedWorkspace.add_file` to key files by relative path (`staged_file.path`) rather than basename (`staged_file.filename`), completely eliminating file collision when scaffolding multi-directory resources (e.g. `<workload>/<sub_prod>/main.tf` alongside `azurerm_subnet/<sub_prod>/main.tf`).
- **Provisioning Parameters**: Extended `ProvisioningParameters` domain model with `selected_subnet`, `network_action` (`existing`, `scaffold`, `remote`, `none`), and `cross_sub_source`.
- **Subnet Scaffolding**: Implemented `ScaffoldEngine.scaffold_subnet` synthesizing standards-governed `azurerm_subnet` resource definitions, isolated backend configuration, and resource group data source. Omitted `tags` attribute from `azurerm_subnet` (unsupported by AzureRM provider) and enforced strict CIDR notation (`strict=True`).
- **Terminal Ports & Adapters**: Added `prompt_select_subnet` to `TerminalUIPort` and implemented in `RichTerminalAdapter` with formatted candidate metadata (CIDRs, VNet/RG parents, purpose annotations), `(Recommended)` tagging, and default index selection. Enhanced `is_interactive()` to guard both stdout and stdin TTY status.
- **Guided Dialogue Flow**: Integrated topology discovery (`ReadOnlyHclAdapter`) into `ProvisioningFlow._handle_subnet_selection`, supporting interactive candidate selection, missing subnet scaffolding, cross-subscription lookup with self-referencing guards, and `--subnet` pre-seeded flag validation. Added headless automated fallback in `cli.py` for non-interactive `--yes` runs.
- **Testing**: Authored 17 unit and integration tests in `tests/test_subnet_selection.py` validating all positive and edge cases, maintaining full adherence to Hexagonal architectural boundaries. 258/258 tests passing.

## Spec Change Log

## Review Triage Log

- `ttassistant/application/provisioning_flow.py`: `should_prompt` evaluates to False on greenfield repos with 0 subnets, skipping missing dependency scaffolding — Verdict: `high` — Fix: enable prompt whenever resource requires network binding and discovery is active.
- `ttassistant/domain/scaffold.py`: `azurerm_subnet` does not support `tags` attribute in Terraform AzureRM — Verdict: `medium` — Fix: omit `tags` from generated `azurerm_subnet` block.
- `ttassistant/adapters/fs_adapter.py` & `ttassistant/domain/diff.py`: `existing_files[filename]` collides across directories in multi-directory workspaces — Verdict: `medium` — Fix: key/lookup by full relative path instead of bare filename.
- `ttassistant/adapters/terminal_adapter.py`: `is_interactive()` only checks stdout isatty, crashing Questionary when stdin is non-TTY / piped — Verdict: `medium` — Fix: check `self.is_tty() and bool(getattr(self.stdin, "isatty", lambda: False)())`.
- `ttassistant/application/provisioning_flow.py` & `ttassistant/domain/scaffold.py`: CIDR validation allows host bits via `strict=False` and `scaffold_subnet` misses CIDR validation — Verdict: `medium` — Fix: enforce `strict=True` with `ipaddress.ip_network` and validate in `scaffold_subnet`.
- `tests/test_subnet_selection.py`: `test_cli_new_with_subnet_flag_e2e` pollutes repository root by creating files without isolation/cleanup — Verdict: `medium` — Fix: clean up generated directories in test.
- `ttassistant/application/provisioning_flow.py`: Pre-seeded `--subnet` flag not validated for empty string or naming conventions — Verdict: `low` — Fix: validate non-empty and naming rule compliance.
- `ttassistant/application/provisioning_flow.py`: Allows self-referential cross-subscription lookup — Verdict: `low` — Fix: reject `source_sub == subscription`.
- `ttassistant/application/provisioning_flow.py`: Missing prompt for target VNet during missing subnet scaffolding — Verdict: `low` — Fix: resolve from discovered VNets or prompt.
- `tests/test_subnet_selection.py`: Missing test for `azurerm_resource_group` subnet selection bypass — Verdict: `low` — Fix: add test verifying resource groups bypass subnet prompt.
- `ttassistant/application/provisioning_flow.py`: Summary output displays single `workspace.target_dir` omitting secondary directories — Verdict: `low` — Fix: display all staged directories.
- `ttassistant/cli.py`: Root CLI callback MissingStandardsError when common_standards missing — Verdict: `defer` — Pre-existing CLI callback behavior, out of scope for story 2.3.


## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_subnet_selection.py` -- expected: All subnet selection and missing dependency tests pass.
- `./.venv/bin/pytest tests/test_architecture.py` -- expected: Architecture boundary tests pass.
- `./.venv/bin/pytest` -- expected: Complete test suite passes.
- `./.venv/bin/python -m ttassistant new --help` -- expected: Shows `--subnet` option in help output.

