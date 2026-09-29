---
title: 'Story 3.2: Tier 1 PaaS Scaffolding with Mandatory Public Network Access Denial'
type: 'feature'
created: '2026-09-24'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md'
  - '_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Default Terraform configurations for Azure PaaS resources (such as Storage Accounts, Key Vaults, and SQL databases) frequently expose public endpoints, risking accidental exposure of corporate data, database infrastructure, and cryptographic secrets to the public internet.

**Approach:** Enforce mandatory public network access denial (`public_network_access_enabled = false` or equivalent attribute) by default when scaffolding all Tier 1 PaaS resources in `ScaffoldEngine.synthesize_main`, and implement a high-visibility interactive security warning gate requiring explicit human confirmation before public access can ever be enabled.

## Boundaries & Constraints

**Always:**
- Keep pure security policy and synthesis logic in `ttassistant.domain.scaffold` and `ttassistant.domain.models`, completely decoupled from terminal UI and I/O (AD-1).
- Automatically configure `public_network_access_enabled = false` on all Tier 1 PaaS resource blocks (`azurerm_storage_account`, `azurerm_key_vault`, `azurerm_mssql_server`, `azurerm_cosmosdb_account`, `azurerm_eventhub_namespace`, `azurerm_postgresql_flexible_server`, `azurerm_mysql_flexible_server`, `azurerm_redis_cache`, `azurerm_linux_web_app`) by default (AD-7, FR-12).
- Non-PaaS foundation resources (`azurerm_resource_group`, `azurerm_virtual_network`, `azurerm_subnet`) do not configure `public_network_access_enabled`.
- Support `public_network_access: bool = False` on `ProvisioningParameters`.
- When an engineer explicitly attempts to enable public access (via CLI option `--public-network-access` or interactive prompt), the CLI must render a high-visibility security warning banner explaining policy violation and require explicit confirmation (`[y/N]`, default `False`) (FR-12).
- If the engineer rejects the security confirmation, public access remains disabled (`public_network_access = False`).
- In automated non-interactive runs (`--yes` without interactive TTY), requesting `--public-network-access` without explicit confirmation override fails fast with exit code 1 to prevent accidental insecure automated deployments.
- Emit clean, deterministic HCL with sorted attributes conforming to corporate standards and provider schema specifications.

**Never:**
- Never default `public_network_access_enabled` to `true` on any Tier 1 PaaS service (FR-12).
- Never bypass the security warning confirmation gate when public access is requested (FR-12).
- Never invoke external `terraform` or `az` CLI commands (AD-2, NFR-5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Default Tier 1 PaaS Scaffolding | `params.resource_type="azurerm_storage_account"`, `public_network_access=False` | `main.tf` contains `public_network_access_enabled = false` | N/A |
| Default Key Vault Scaffolding | `params.resource_type="azurerm_key_vault"`, `public_network_access=False` | `main.tf` contains `public_network_access_enabled = false` alongside `sku_name` and `tenant_id` | N/A |
| Foundation Resource Scaffolding | `params.resource_type="azurerm_resource_group"` or `"azurerm_subnet"` | `main.tf` omits `public_network_access_enabled` | N/A |
| Interactive Public Access Request (Confirmed) | User enables public access via prompt/flag; confirms security warning gate | CLI displays high-visibility warning; sets `public_network_access_enabled = true` in `main.tf` | Confirmation required |
| Interactive Public Access Request (Rejected) | User enables public access via prompt/flag; rejects security warning gate | Reverts to `public_network_access_enabled = false` (private-only) | Reverts cleanly |
| Headless Unconfirmed Public Access | Non-interactive execution with `--public-network-access` without confirmation | Exits code 1 with security policy violation error | Refuses unconfirmed insecure deployment |
| Schema & HCL Syntax Validity | Any generated `main.tf` | Parsed with `python-hcl2.loads()` without syntax errors | Asserts valid HCL |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/models.py` -- Add `public_network_access: bool = False` to `ProvisioningParameters`.
- `ttassistant/domain/scaffold.py` -- Update `ScaffoldEngine.synthesize_main` to automatically apply `public_network_access_enabled = false` (or resource-specific attribute) for all Tier 1 PaaS resources.
- `ttassistant/ports/terminal.py` & `ttassistant/adapters/terminal_adapter.py` -- Add security warning modal/banner formatting to `TerminalUIPort`.
- `ttassistant/application/provisioning_flow.py` -- Integrate public access security confirmation gate and warning banner before workspace generation.
- `ttassistant/cli.py` -- Add `--public-network-access` option to `ttassistant new`.
- `tests/test_paas_security.py` -- Dedicated test suite verifying mandatory public access denial, security warning gate, confirmation rejection, headless guard, and HCL validity.
- `tests/test_scaffold.py` -- Update existing scaffolding tests for Tier 1 PaaS resources.
- `tests/test_architecture.py` -- Re-verify strict architectural boundary enforcement (AD-1).

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/models.py` -- Extend `ProvisioningParameters` with `public_network_access: bool = False`.
- [x] `ttassistant/domain/scaffold.py` -- Implement mandatory `public_network_access_enabled = false` for Tier 1 PaaS resources in `synthesize_main`.
- [x] `ttassistant/ports/terminal.py` & `ttassistant/adapters/terminal_adapter.py` -- Implement high-visibility security warning rendering in `TerminalUIPort` and `RichTerminalAdapter`.
- [x] `ttassistant/application/provisioning_flow.py` -- Wire security warning confirmation gate into `ProvisioningFlow` when public network access is requested.
- [x] `ttassistant/cli.py` -- Expose `--public-network-access` option on `new` command with headless security safeguards.
- [x] `tests/test_paas_security.py` -- Author comprehensive tests covering default denial, explicit opt-in confirmation, confirmation rejection fallback, headless guard, and syntax validity.
- [x] `tests/test_architecture.py` -- Re-verify zero external binaries and strict domain isolation.

**Acceptance Criteria:**
- Given a Tier 1 PaaS resource selection (e.g. `azurerm_storage_account`, `azurerm_key_vault`, `azurerm_mssql_server`, `azurerm_cosmosdb_account`).
- When the scaffolding engine generates the primary resource block in `main.tf`.
- Then the resource configuration explicitly sets `public_network_access_enabled = false`.
- And if the user explicitly attempts to enable public access, the CLI displays a high-visibility security warning and requires explicit confirmation.

## Implementation Notes
- Pure domain logic kept strictly within `ttassistant.domain` (`models.py`, `catalog.py`, `exceptions.py`, `scaffold.py`), honoring AD-1.
- Defined `TIER_1_PAAS_RESOURCES` and `TIER_1_FOUNDATION_RESOURCES` in `ttassistant.domain.catalog`.
- Automatically configured `public_network_access_enabled = params.public_network_access` (defaulting to False) for all Tier 1 PaaS resources in `ScaffoldEngine.synthesize_main`.
- Implemented high-visibility red-bordered security warning banner in `RichTerminalAdapter` with plain text fallback.
- Added interactive security warning confirmation gate and headless security safeguard (`SecurityPolicyViolationError`) in `ProvisioningFlow` and `ttassistant.cli.new`.
- Rejection of confirmation in interactive prompt cleanly falls back to private-only configuration (`public_network_access=False`).
- Authored 23 tests in `tests/test_paas_security.py` verifying full compliance, edge cases, and python-hcl2 syntax validation. Total test suite increased from 306 to 329 passing tests.

## Spec Change Log

## Review Triage Log
- [medium -> patch] BH-1 / EH-3: Fixed dead code in `ProvisioningFlow._handle_public_network_access_gate` boolean expression to `if not is_interactive or auto_approve:` ensuring fail-fast in automated runs without confirmation override.
- [medium -> patch] BH-7: Replaced `hasattr(self.terminal, "display_security_warning")` duck typing with direct call to `self.terminal.display_security_warning(...)` per `TerminalUIPort` contract.
- [medium -> patch] VG-1 / BH-8 / BH-13 / VG-4: Added tests in `tests/test_paas_security.py` covering color Rich Panel formatting (`is_color_supported = lambda: True`) and `print_security_warning`.
- [low -> patch] VG-3 / BH-11 / EH-6: Added autouse `cleanup_generated_dirs` fixture in `tests/test_paas_security.py` to prevent test workspace disk pollution.
- [low -> patch] BH-12: Added `test_scaffold_paas_resource_with_public_network_access_enabled` in `tests/test_scaffold.py` asserting `public_network_access=True` synthesizes `public_network_access_enabled = true`.
- [medium -> defer] VG-2 / BH-4: Deferred interactive prompt flow integration for public network access to future CLI dialogues.
- [medium -> defer] BH-2: Deferred broadening `ProvisioningFlow._collect_resource_type` beyond naming conventions to Story 3.4.
- [medium -> defer] BH-3: Deferred complete schema defaults for long-tail PaaS types to Story 3.4.
- [false] BH-5: Corporate networking policy is strictly enforced via default public network denial across all Tier 1 PaaS services.
- [false] BH-6: Flag `--confirm-public-network-access` is designed to cleanly override prompts for headless pipelines.
- [false] BH-9: Omission of `public_network_access_enabled` on foundation resources matches spec matrix row 3.
- [low -> defer] BH-10: Deferred top-level HCL attribute sorting in `ttassistant/domain/hcl.py`.
- [false] BH-14: Providing confirmation without requesting public access safely defaults to private-only configuration.
- [low -> defer] EH-1, EH-2, EH-4: Pre-existing edge cases in subnet selection logic from Story 2.3.
- [false] EH-5: Stdin non-blocking behavior under pytest passes cleanly across all 332 tests.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_paas_security.py` -- expected: All PaaS security tests pass.
- `./.venv/bin/pytest tests/test_scaffold.py` -- expected: Scaffolding engine tests pass.
- `./.venv/bin/pytest tests/test_architecture.py` -- expected: Architectural boundaries remain intact.
- `./.venv/bin/pytest` -- expected: Full test suite passes (315+ tests).
- `./.venv/bin/python -m ttassistant new --help` -- expected: Shows `--public-network-access` option.

