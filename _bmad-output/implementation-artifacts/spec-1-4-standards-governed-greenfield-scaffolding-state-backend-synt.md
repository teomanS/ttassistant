---
title: 'Story 1.4: Standards-Governed Greenfield Scaffolding & State Backend Synthesis'
type: 'feature'
created: '2026-09-22'
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

**Problem:** Infrastructure teams frequently suffer state file collisions and inconsistent Terraform structures because remote state backends, upstream resource group references, and mandatory compliance tags are manually copied or configured inconsistently across monorepo directories.

**Approach:** Implement a pure-Python scaffolding engine in `ttassistant.domain.scaffold` and canonical HCL serializer in `ttassistant.domain.hcl` that takes validated `ProvisioningParameters` and synthesizes an in-memory `StagedWorkspace` containing canonical `main.tf` (with primary resource and mandatory tags), `data.tf` (decoupled upstream resource group data source), and `backend.tf` (isolated Azure Blob remote state coordinates per `backend_mapping.md`).

## Boundaries & Constraints

**Always:**
- Keep pure business domain packages (`ttassistant.domain.scaffold`, `ttassistant.domain.hcl`, `ttassistant.domain.models`) strictly free of UI and filesystem I/O dependencies (AD-1).
- Emit in-memory `StagedWorkspace` buffers targeting target path `<resource-type>/<subscription>/` without performing physical disk writes (AD-5).
- Synthesize `backend.tf` resolving exact subscription storage account, resource group, container, and key pattern from `StandardsEngine.resolve_backend` (AD-3, FR-10).
- Synthesize `data.tf` with decoupled `data "azurerm_resource_group" "primary"` referencing target subscription resource group with zero hardcoded IDs and zero `terraform_remote_state` (FR-7, AD-3).
- Synthesize `main.tf` with primary resource block populated with computed compliant resource name, reference to resource group data source (`data.azurerm_resource_group.primary.name` and `.location`), and corporate tags block from `StandardsEngine.apply_default_tags` (FR-9).
- Format HCL using canonical 2-space indentation and clean attribute layout without invoking external binaries or third-party HCL dumpers that strip comments (AD-2).

**Never:**
- Never invoke external `terraform` or `az` binaries.
- Never write files to physical disk during scaffolding synthesis; writes belong exclusively to Story 1.5's confirmation gate.
- Never emit `terraform_remote_state` blocks (AD-3).
- Never allow cross-subscription state file collisions; backend keys must isolate by resource type and subscription.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Greenfield Storage Account scaffolding | `subscription="sub-prod"`, `resource_type="azurerm_storage_account"`, `workload="appdata"`, `environment="prod"` | `StagedWorkspace` targeting `azurerm_storage_account/sub-prod/` containing `main.tf`, `data.tf`, `backend.tf` | N/A |
| Backend key isolation | Greenfield scaffolding in `sub-prod` vs `sub-nonprod` | Backend keys isolated: `azurerm_storage_account/sub-prod/terraform.tfstate` vs `.../sub-nonprod/...` | N/A |
| Resource group data source wiring | Greenfield resource targeting `sub-prod` | `data.tf` emits `data "azurerm_resource_group" "primary"` referencing resolved backend / subscription resource group | N/A |
| Primary resource block wiring | Primary resource `azurerm_storage_account` | `main.tf` references `data.azurerm_resource_group.primary.name` and `.location` | N/A |
| Mandatory tagging baseline | Corporate standards require tags `Environment`, `Owner`, `CostCenter`, `Project` | `main.tf` includes `tags = { ... }` with all mandatory tags populated with resolved/default values | N/A |
| Custom unlisted subscription | User provisions in custom subscription matching wildcard backend rule | `backend.tf` formats backend key and storage account according to wildcard pattern | If no matching backend rule, raises `StandardsError` |
| Hyphenated vs non-hyphenated resource names | Resource group (`azurerm_resource_group`) vs storage account (`azurerm_storage_account`) | Resource names respect naming rule patterns: `rg-appdata-prod` vs `stappdataprod` | N/A |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/models.py` -- Define `StagedFile` and `StagedWorkspace` Pydantic models capturing staged file buffers, target relative directory, and metadata.
- `ttassistant/domain/hcl.py` -- Pure-Python HCL serialization utilities for formatting Terraform blocks (`resource`, `data`, `terraform`, `backend`), string literals, references, and maps with 2-space indentation.
- `ttassistant/domain/scaffold.py` -- `ScaffoldEngine` business logic synthesizing `main.tf`, `data.tf`, and `backend.tf` into `StagedWorkspace`.
- `ttassistant/application/provisioning_flow.py` -- Integrate `ScaffoldEngine` into `ProvisioningFlow.run`, returning `StagedWorkspace` along with parameters.
- `ttassistant/cli.py` -- Update `new` command to display staged workspace summary (files generated, target folder, line counts).
- `tests/test_hcl.py` -- Unit tests for HCL block builder, attribute alignment, map formatting, and reference rendering.
- `tests/test_scaffold.py` -- Unit tests for `ScaffoldEngine` verifying `backend.tf`, `data.tf`, and `main.tf` synthesis across multiple subscriptions and resource types.
- `tests/test_staged_workspace.py` -- Unit tests for `StagedWorkspace` in-memory staging model.
- `tests/test_provisioning_flow.py` -- Integration tests asserting `ProvisioningFlow` produces complete `StagedWorkspace`.
- `tests/test_cli_new.py` -- CLI tests asserting `ttassistant new` displays staged files and target path.
- `tests/test_architecture.py` -- Verify `ttassistant.domain.scaffold` and `ttassistant.domain.hcl` contain zero forbidden UI or I/O imports (AD-1).

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/models.py` -- Add `StagedFile` and `StagedWorkspace` domain models.
- [x] `ttassistant/domain/hcl.py` -- Implement pure-Python HCL formatting utilities for blocks, attributes, data references, and maps.
- [x] `ttassistant/domain/scaffold.py` -- Implement `ScaffoldEngine` synthesizing `backend.tf`, `data.tf`, and `main.tf` from `ProvisioningParameters` and `StandardsEngine`.
- [x] `ttassistant/application/provisioning_flow.py` -- Wire `ScaffoldEngine` into `ProvisioningFlow.run` to produce and return `StagedWorkspace`.
- [x] `ttassistant/cli.py` -- Update `new` command to report staged files and target directory.
- [x] `tests/test_hcl.py` -- Unit tests for HCL syntax, block generation, and map formatting.
- [x] `tests/test_scaffold.py` -- Unit tests for scaffolding engine verifying generated files, tags, and backend state isolation.
- [x] `tests/test_staged_workspace.py` -- Unit tests for `StagedWorkspace` model.
- [x] `tests/test_provisioning_flow.py` & `tests/test_cli_new.py` -- Update tests verifying end-to-end staged workspace generation.
- [x] `tests/test_architecture.py` -- Verify AD-1 domain layer isolation for `hcl.py` and `scaffold.py`.

**Acceptance Criteria:**
- Given validated provisioning parameters from Story 1.3, when the scaffolding engine executes, then it synthesizes in memory: `main.tf` with target resource block and mandatory tags, `backend.tf` with Azure Blob remote state isolated by subscription and resource type, and `data.tf` with upstream resource group data source.
- State key paths in `backend.tf` follow corporate `backend_mapping.md` conventions with zero collisions.
- Generated HCL code is clean, canonical Terraform syntax with standard 2-space indentation and aligned attribute formatting.

## Implementation Notes

- Implemented `StagedFile` and `StagedWorkspace` domain models in `ttassistant.domain.models` with line counting and dictionary-like operations.
- Implemented pure-Python HCL formatter in `ttassistant.domain.hcl` supporting blocks, attribute alignment, unquoted references (`HclReference`), maps with 2-space indents and aligned keys, and primitives with zero external binaries.
- Implemented `ScaffoldEngine` in `ttassistant.domain.scaffold` synthesizing `main.tf`, `data.tf`, and `backend.tf` strictly in-memory into `StagedWorkspace` targeting `<resource-type>/<subscription>/`.
- Integrated `ScaffoldEngine` into `ProvisioningFlow.run`, returning `(params, workspace)`.
- Updated `ttassistant new` command in `ttassistant/cli.py` to output staged workspace path, file names, and line counts.
- Added comprehensive unit and integration test suites: `tests/test_hcl.py`, `tests/test_scaffold.py`, `tests/test_staged_workspace.py`. Updated `tests/test_provisioning_flow.py`, `tests/test_cli_new.py`, and `tests/test_architecture.py`.
- Verified 100% test pass rate across all 164 tests in the test suite.


## Spec Change Log

## Review Triage Log

- `ttassistant/domain/hcl.py`: `format_hcl_value` map key equals sign misalignment when map keys require quoting — Verdict: `low` — Patched: pre-computed formatted keys before calculating `max_key_len`.
- `ttassistant/domain/hcl.py`: `format_hcl_value` list branch does not support tuple or set — Verdict: `low` — Patched: added `tuple` and `set` support to sequence branch.
- `ttassistant/domain/hcl.py`: `escape_hcl_string` does not escape `${` and `%{` sequence interpolation — Verdict: `low` — Patched: escaped `${` to `$${` and `%{` to `%%{`.
- `ttassistant/domain/scaffold.py`: Subnet resource (`azurerm_subnet`) should not include `location` attribute — Verdict: `low` — Patched: omitted `location` on `azurerm_subnet` in `RESOURCE_NO_LOCATION`.
- `ttassistant/domain/scaffold.py`: `azurerm_resource_group` scaffolding emitted redundant `data.tf` referencing itself — Verdict: `low` — Patched: omitted `data.tf` synthesis for `azurerm_resource_group`.
- `ttassistant/domain/models.py`: `StandardsBundle.get_backend_rule` greedy `default` check intercepted glob matches — Verdict: `medium` — Patched: ordered exact match -> specific glob match -> default/wildcard fallback.
- `tests/test_hcl.py`: Missing coverage for multiline lists, quoted map key alignment, and tuple/set formatting — Verdict: `low` — Patched: added unit test assertions for all scenarios.
- `tests/test_scaffold.py`: Missing explicit assertions on backend.tf attributes and coverage for other resource defaults — Verdict: `low` — Patched: added tests asserting backend attributes and key vault / subnet / resource group scaffold behaviors.

## Design Notes

- Emitted directory structure follows `<resource-type>/<subscription>/` per PRD §4.5 and Architecture AD-3.
- `data.tf` uses `data "azurerm_resource_group" "primary"` to allow the primary resource in `main.tf` to inherit location and resource group name dynamically without hardcoding.
- `backend.tf` configures `terraform { backend "azurerm" { ... } }` with storage account, container, and key resolved directly from corporate `backend_mapping.md`.
- Pure-Python HCL generator avoids `python-hcl2` for dumping because `python-hcl2` is strictly a read-only parser (AD-2).

## Verification

**Commands:**
- `./.venv/bin/pytest` -- expected: All unit, integration, and architecture tests pass (100% pass rate).
- `./.venv/bin/python -m ttassistant new --subscription sub-prod --resource-type azurerm_storage_account --workload appdata` -- expected: Emits staged workspace summary with `main.tf`, `data.tf`, `backend.tf`.

