---
title: 'Story 2.4: Decoupled Data Source Generator'
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

**Problem:** Scaffolding cloud infrastructure with upstream networking dependencies (Virtual Networks and Subnets) frequently leads developers to hardcode Azure resource IDs or introduce brittle `terraform_remote_state` data sources, causing cross-module state coupling, state-locking contention, and blast-radius escalation.

**Approach:** Extend `ScaffoldEngine.synthesize_data` and `ProvisioningFlow` to automatically generate clean, decoupled `data "azurerm_*"` blocks (`azurerm_resource_group`, `azurerm_virtual_network`, and `azurerm_subnet`) in `data.tf` referencing upstream infrastructure by name and resource group without hardcoded resource IDs or remote state blocks.

## Boundaries & Constraints

**Always:**
- Keep pure synthesis and domain logic in `ttassistant.domain.scaffold` and `ttassistant.domain.models`, completely decoupled from terminal UI and I/O (AD-1).
- Emit `data "azurerm_resource_group"` in `data.tf` referencing the parent resource group by name for non-RG resources (AD-3, FR-7).
- When a subnet is selected (`params.selected_subnet` is not None and `params.network_action != "none"`):
  - Emit `data "azurerm_virtual_network"` in `data.tf` referencing the parent VNet by name and parent RG.
  - Emit `data "azurerm_subnet"` in `data.tf` referencing the selected subnet name, `virtual_network_name = data.azurerm_virtual_network.<name>.name`, and `resource_group_name = data.azurerm_virtual_network.<name>.resource_group_name` (or parent RG).
- Enforce strictly zero `terraform_remote_state` data blocks across all generated Terraform files (AD-3, FR-7).
- In cross-subscription scenarios (`params.network_action == "cross_subscription"` or remote lookup), emit decoupled data sources configured with appropriate source subscription attributes/provider references.
- In greenfield/standalone scenarios where no subnet is selected or network binding is skipped (`network_action == "none"`), only emit the resource group data source in `data.tf`.
- Omit `data.tf` entirely when scaffolding `azurerm_resource_group` workloads.
- Emit valid HCL with deterministic alphabetical attribute ordering and proper reference types using `ttassistant.domain.hcl` (NFR-6).

**Never:**
- Never emit `data "terraform_remote_state"` blocks anywhere in generated files (AD-3, FR-7).
- Never hardcode Azure subscription IDs, tenant IDs, or full ARM resource IDs (`/subscriptions/.../resourceGroups/...`) in data source queries (AD-3).
- Never execute external `terraform` or `az` CLI commands (AD-2, NFR-5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Workload with Selected Subnet | `params.selected_subnet="snet-pe-01"`, `selected_vnet="vnet-prod"`, `subscription="sub-prod"` | `data.tf` contains `data "azurerm_resource_group" "primary"`, `data "azurerm_virtual_network" "primary"`, `data "azurerm_subnet" "primary"`; 0 remote state blocks | Validates parent VNet and RG names cleanly |
| Workload with Subnet but Unspecified VNet | `params.selected_subnet="snet-pe-01"`, `selected_vnet=None` | Infers default VNet naming pattern `vnet-<subscription>` or resolves from topology | Uses inferred VNet name with standard RG reference |
| Cross-Subscription Shared Subnet | `network_action="remote"`, `cross_sub_source="sub-hub"`, `selected_subnet="snet-shared"` | `data.tf` contains decoupled data sources referencing shared hub network coordinates | Validates remote subscription format |
| Workload with Skipped Network Configuration | `params.selected_subnet=None` or `network_action="none"` | `data.tf` contains only `data "azurerm_resource_group" "primary"`; no VNet/Subnet data sources | N/A |
| Resource Group Workload | `params.resource_type="azurerm_resource_group"` | `data.tf` is omitted completely from `StagedWorkspace` | N/A |
| AST Roundtrip & HCL Validity | Any generated `data.tf` | Python `hcl2.loads()` parses the generated document without errors | Asserts syntax validity |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/models.py` -- Extend `ProvisioningParameters` with `selected_vnet` and `selected_subnet_rg`.
- `ttassistant/domain/scaffold.py` -- Enhance `ScaffoldEngine.synthesize_data` to emit decoupled `azurerm_virtual_network` and `azurerm_subnet` data sources when `selected_subnet` is present.
- `ttassistant/application/provisioning_flow.py` -- Pass discovered candidate VNet and RG metadata into `ProvisioningParameters` during subnet selection, ensuring `scaffold_engine.scaffold` produces populated `data.tf`.
- `tests/test_data_sources.py` -- Dedicated test suite for decoupled data source synthesis, verifying HCL syntax, attribute bindings, and zero remote state.
- `tests/test_scaffold.py` -- Update existing scaffolding tests to assert new decoupled data source generator capabilities.
- `tests/test_architecture.py` -- Verify strict architectural boundary enforcement (AD-1).

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/models.py` -- Extend `ProvisioningParameters` with `selected_vnet` and `selected_subnet_rg` fields.
- [x] `ttassistant/domain/scaffold.py` -- Implement decoupled VNet and Subnet data block generation in `synthesize_data` with zero `terraform_remote_state`.
- [x] `ttassistant/application/provisioning_flow.py` -- Wire discovered subnet candidate VNet and RG metadata into `ProvisioningParameters` during collaborative dialogue.
- [x] `tests/test_data_sources.py` -- Author comprehensive unit and integration tests covering decoupled data source generation across single-subscription, cross-subscription, and greenfield flows.
- [x] `tests/test_architecture.py` -- Re-verify zero external binaries and strict domain isolation.

**Acceptance Criteria:**
- Given a selected subnet, parent Resource Group, and target subscription.
- When `ScaffoldEngine.scaffold` generates `data.tf`.
- Then it emits `data "azurerm_resource_group"` referencing the parent resource group by name.
- And it emits `data "azurerm_subnet"` and `data "azurerm_virtual_network"` referencing the selected subnet and VNet by name and resource group.
- And the generated HCL contains strictly zero `terraform_remote_state` data blocks.
- And all generated HCL is validly parseable by `python-hcl2`.

## Implementation Notes

- **Provisioning Parameters**: Extended `ProvisioningParameters` in `ttassistant.domain.models` with `selected_vnet: Optional[str]` and `selected_subnet_rg: Optional[str]`.
- **Decoupled Data Source Synthesis**: Enhanced `ScaffoldEngine.synthesize_data` in `ttassistant.domain.scaffold` to emit decoupled `azurerm_resource_group`, `azurerm_virtual_network`, and `azurerm_subnet` data blocks in `data.tf` when a subnet is selected, strictly avoiding `terraform_remote_state` and hardcoded ARM IDs. Attribute order is alphabetically deterministic (`name`, `provider`, `resource_group_name`, `virtual_network_name`).
- **Validation**: Added validation for parent VNet names (`azurerm_virtual_network` naming rule), RG names (`azurerm_resource_group`), and remote subscription formats.
- **Cross-Subscription Support**: In cross-subscription scenarios (`cross_subscription` / `remote`), emits remote hub coordinates and provider aliases (`azurerm.<source_sub_alias>`).
- **Provisioning Flow Wiring**: Wired discovered candidate VNet and RG metadata into `ProvisioningParameters` during subnet selection in `ProvisioningFlow`, passing the populated parameters to `scaffold_engine.scaffold`.
- **Testing**: Added comprehensive test suite in `tests/test_data_sources.py` covering single-subscription, cross-subscription, greenfield/skipped, validation, air-gap zero binaries, and flow integration. Updated `tests/test_scaffold.py`. All 275 tests in repository pass.

## Review Triage Log

- `ttassistant/domain/scaffold.py`: Numeric or UUID cross-subscription provider aliases generate invalid HCL identifier `azurerm.<digit>` — Verdict: `medium` — Fix: ensure alias starts with letter or underscore (prepend `sub_` if starting with a digit).
- `ttassistant/domain/scaffold.py`: Inferred fallback VNet and RG names can fail regex naming validation if subscription contains uppercase or underscores — Verdict: `low` — Fix: normalize inferred names to lowercase with hyphens.
- `ttassistant/domain/scaffold.py`: Valid existing or Azure-reserved subnets (`GatewaySubnet`, `AzureBastionSubnet`) fail greenfield `snet_rule` validation — Verdict: `low` — Fix: allow reserved subnet names in data source reference validation.
- `ttassistant/application/provisioning_flow.py`: Custom subnet selection discards discovered VNet's parent RG — Verdict: `low` — Fix: preserve `matching_vnets[0].resource_group_name`.
- `ttassistant/application/provisioning_flow.py`: Multi-directory target path display does not normalize Windows backslashes to POSIX slashes — Verdict: `low` — Fix: normalize with `replace('\\', '/')`.
- `ttassistant/cli.py`: Redundant double topology scan in CLI when running non-interactively — Verdict: `low` — Fix: remove duplicate CLI pre-scan; let `ProvisioningFlow` handle non-interactive selection natively.
- `ttassistant/application/provisioning_flow.py`: Pre-seeded subnet (`--subnet`) discovered candidate VNet and RG binding to `data.tf` lacks verification — Verdict: `medium` (pre-verified gap) — Fix: add test verifying candidate VNet and RG wire into `data.tf`.
- `ttassistant/application/provisioning_flow.py`: Automated non-interactive mode candidate recommendation and VNet/RG wiring lacks verification — Verdict: `medium` (pre-verified gap) — Fix: add test with `is_interactive=False` verifying recommended subnet wires into `data.tf`.
- `ttassistant/domain/scaffold.py`: Parent Resource Group naming rule validation in `synthesize_data` lacks verification — Verdict: `low` (pre-verified gap) — Fix: add test verifying `ValueError` on invalid parent RG name.
- `ttassistant/domain/scaffold.py`: Missing `provider` configuration block for cross-sub aliases — Verdict: `false` — Provider declarations are part of provider catalog / infrastructure setup, not within data source generator scope.
- `ttassistant/domain/scaffold.py`: Missing Hub Private DNS Zone data source in `data.tf` — Verdict: `false` — Private DNS Zone data source bundling is explicitly scheduled in Epic 3 (Story 3.3).
- `ttassistant/domain/scaffold.py`: Primary resource block does not reference subnet ID — Verdict: `defer` — PaaS Private Endpoint resource binding is scheduled for Story 3.2 and 3.3.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_data_sources.py` -- expected: All decoupled data source tests pass.
- `./.venv/bin/pytest tests/test_scaffold.py` -- expected: Scaffolding engine tests pass.
- `./.venv/bin/pytest tests/test_architecture.py` -- expected: Architectural boundaries remain intact.
- `./.venv/bin/pytest` -- expected: Full test suite passes (260+ tests).

