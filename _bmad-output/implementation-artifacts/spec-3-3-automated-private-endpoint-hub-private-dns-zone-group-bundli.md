---
title: 'Story 3.3: Automated Private Endpoint & Hub Private DNS Zone Group Bundling'
type: 'feature'
created: '2026-09-25'
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

**Problem:** Manually configuring Azure Private Endpoints and linking them to centralized corporate Hub Private DNS Zones is complex, error-prone, and involves extensive boilerplate across `main.tf` and `data.tf`. Omitting these configurations leaves PaaS services disconnected from private networks or requires manual DNS workarounds.

**Approach:** Automatically bundle companion `azurerm_private_endpoint` and nested `private_dns_zone_group` resources in `main.tf` and scaffold the corresponding Hub `data "azurerm_private_dns_zone"` in `data.tf` for all Tier 1 PaaS resources when a target subnet is selected, resolving DNS zone coordinates from corporate standards (`common_standards/networking_policy.md`).

## Boundaries & Constraints

**Always:**
- Keep pure synthesis and policy resolution logic in `ttassistant.domain` (`scaffold.py`, `standards.py`, `catalog.py`), strictly decoupled from terminal adapters and external I/O (AD-1).
- For all Tier 1 PaaS resources (`azurerm_storage_account`, `azurerm_key_vault`, `azurerm_mssql_server`, `azurerm_cosmosdb_account`, `azurerm_eventhub_namespace`, `azurerm_postgresql_flexible_server`, `azurerm_mysql_flexible_server`, `azurerm_redis_cache`, `azurerm_linux_web_app`) when a target subnet is selected (`params.selected_subnet` is not None):
  - In `main.tf`, synthesize a companion `resource "azurerm_private_endpoint" "primary"` block.
  - Set `subnet_id = HclReference("data.azurerm_subnet.primary.id")`.
  - Set `resource_group_name = HclReference("data.azurerm_resource_group.primary.name")` and `location = HclReference("data.azurerm_resource_group.primary.location")`.
  - Apply standard corporate compliance tags to the private endpoint.
  - Add nested `private_service_connection` block with `name = f"psc-{params.resource_name}"`, `private_connection_resource_id = HclReference(f"{params.resource_type}.primary.id")`, `is_manual_connection = False`, and service-specific `subresource_names` (e.g. `["blob"]` for storage, `["vault"]` for key vault, etc.).
  - Add nested `private_dns_zone_group` block with `name = "default"` and `private_dns_zone_ids = [HclReference("data.azurerm_private_dns_zone.hub.id")]`.
  - In `data.tf`, emit a decoupled `data "azurerm_private_dns_zone" "hub"` block resolving zone name and resource group from corporate `common_standards/networking_policy.md` (or canonical Microsoft Azure private DNS defaults).
- Non-PaaS foundation resources (`azurerm_resource_group`, `azurerm_virtual_network`, `azurerm_subnet`) never scaffold private endpoints or private DNS zone data sources.
- Generated HCL must parse cleanly with zero syntax errors via `python-hcl2.loads()`.
- Reference upstream infrastructure strictly through decoupled `data "azurerm_*"` blocks without hardcoding resource IDs or relying on `terraform_remote_state` (AD-3, FR-7).

**Never:**
- Never create new `azurerm_private_dns_zone` managed resources in spoke workloads (Hub DNS zones are centrally managed and read-only) (AD-7, FR-13).
- Never emit `terraform_remote_state` blocks across any generated files (AD-3, FR-7).
- Never execute external `terraform` or `az` CLI commands (AD-2, NFR-5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Storage Account Private Endpoint | `params.resource_type="azurerm_storage_account"`, `selected_subnet="snet-data-prod"` | `main.tf` contains `azurerm_private_endpoint.primary` with `subresource_names = ["blob"]` and `private_dns_zone_group`; `data.tf` contains `data "azurerm_private_dns_zone" "hub"` for `privatelink.blob.core.windows.net` | N/A |
| Key Vault Private Endpoint | `params.resource_type="azurerm_key_vault"`, `selected_subnet="snet-sec-prod"` | `main.tf` contains `azurerm_private_endpoint.primary` with `subresource_names = ["vault"]`; `data.tf` contains `data "azurerm_private_dns_zone" "hub"` for `privatelink.vaultcore.azure.net` | N/A |
| Other Tier 1 PaaS Resource | Any Tier 1 PaaS (e.g. `azurerm_mssql_server`, `azurerm_cosmosdb_account`, `azurerm_redis_cache`, etc.) with `selected_subnet` | Synthesizes appropriate private endpoint with canonical subresource name and matching Hub Private DNS zone | Uses canonical Azure subresource mapping |
| Foundation Resource Scaffolding | `params.resource_type="azurerm_resource_group"` or `"azurerm_virtual_network"` | `main.tf` omits `azurerm_private_endpoint`; `data.tf` omits `data.azurerm_private_dns_zone.hub` | N/A |
| Tier 1 PaaS Without Subnet | `params.resource_type="azurerm_storage_account"`, `selected_subnet=None` | `main.tf` emits primary resource only; omits `azurerm_private_endpoint` | Logs info/warning that subnet is required for private endpoint |
| Cross-Subscription Subnet Binding | `network_action="cross_subscription"`, `cross_sub_source="sub-hub"` | Private endpoint references `data.azurerm_subnet.primary.id` which references cross-sub VNet | N/A |
| Schema & HCL Syntax Validity | Any generated `main.tf` and `data.tf` | Parsed with `python-hcl2.loads()` without syntax errors | Valid HCL asserted |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/catalog.py` -- Define mapping of canonical Tier 1 PaaS subresource names (`PAAS_SUBRESOURCE_NAMES`) and default Hub Private DNS Zone names (`PAAS_DEFAULT_DNS_ZONES`).
- `ttassistant/domain/standards.py` -- Add `resolve_networking_policy(resource_type: str) -> Optional[NetworkingPolicyRule]` to `StandardsEngine`.
- `ttassistant/domain/scaffold.py` -- Update `ScaffoldEngine.synthesize_main` to generate `azurerm_private_endpoint` with nested `private_service_connection` and `private_dns_zone_group` for Tier 1 PaaS resources when subnet is selected. Update `synthesize_data` to generate `data "azurerm_private_dns_zone" "hub"`.
- `ttassistant/application/provisioning_flow.py` -- Ensure collected networking parameters pass through to `ScaffoldEngine` and display private endpoint summary.
- `tests/test_private_endpoint.py` -- Comprehensive test suite covering private endpoint bundling, subresource names, Hub DNS data source synthesis, foundation omission, and HCL validity.
- `tests/test_scaffold.py` -- Update scaffolding tests for PaaS resources to assert presence of bundled private endpoint and DNS zone blocks.
- `tests/test_architecture.py` -- Verify strict architectural boundary isolation (AD-1) and zero external binaries.

## Tasks & Acceptance

**Execution:**
- [ ] `ttassistant/domain/catalog.py` -- Define subresource names and fallback Hub DNS zone mappings for Tier 1 PaaS services.
- [ ] `ttassistant/domain/standards.py` -- Add `resolve_networking_policy` to `StandardsEngine` to resolve zone IDs and names from `common_standards/networking_policy.md`.
- [ ] `ttassistant/domain/scaffold.py` -- Implement `azurerm_private_endpoint` and `private_dns_zone_group` synthesis in `synthesize_main`, and `data "azurerm_private_dns_zone" "hub"` synthesis in `synthesize_data`.
- [ ] `ttassistant/application/provisioning_flow.py` -- Verify seamless parameter flow and terminal display for bundled private endpoint and DNS coordinates.
- [ ] `tests/test_private_endpoint.py` -- Author comprehensive test suite validating the complete Enterprise Security Triad (private endpoint, private DNS zone group, subresource names, HCL AST validity).
- [ ] `tests/test_scaffold.py` & `tests/test_architecture.py` -- Verify updated scaffolding behavior and architectural boundary invariants.

**Acceptance Criteria:**
- Given a scaffolded Tier 1 PaaS resource and selected candidate subnet.
- When `main.tf` and `data.tf` are synthesized.
- Then `main.tf` includes an `azurerm_private_endpoint` resource referencing `data.azurerm_subnet.primary.id` and the primary resource ID.
- And it includes a `private_dns_zone_group` block linked to the corporate Hub Private DNS zone data source resolved from `common_standards/`.
- And `data.tf` automatically includes the required Hub Private DNS Zone data source block (`data "azurerm_private_dns_zone" "hub"`).

## Implementation Notes
- Implemented `PAAS_SUBRESOURCE_NAMES` and `PAAS_DEFAULT_DNS_ZONES` in `ttassistant/domain/catalog.py` covering all 9 Tier 1 PaaS services.
- Added `hub_resource_group` and `hub_subscription_id` extraction properties to `NetworkingPolicyRule` in `ttassistant/domain/models.py`.
- Added whitespace trimming validator for `selected_subnet` in `ProvisioningParameters`.
- Enhanced `StandardsEngine.resolve_networking_policy` and `resolve_hub_dns_zone` to extract zone FQDN from custom zone IDs and deterministically resolve Hub resource groups.
- Implemented companion `azurerm_private_endpoint` with nested `private_service_connection` and `private_dns_zone_group` in `ScaffoldEngine.synthesize_main`, with naming validation against `azurerm_private_endpoint` rule.
- Implemented decoupled `data "azurerm_private_dns_zone" "hub"` in `ScaffoldEngine.synthesize_data` with validation ensuring non-empty zone names.
- Updated `ProvisioningFlow` summary display to accurately reflect private endpoint enablement and Hub DNS coordinates.
- Authored 22 tests in `tests/test_private_endpoint.py`, extended `tests/test_standards_models.py`, `tests/test_standards_engine.py`, `tests/test_scaffold.py`, and `tests/test_data_sources.py`; all 359 tests passing.

## Spec Change Log

## Review Triage Log
- [medium -> patch] BH-2 / EH-2 / VG-Other-2: Made `hub_resource_group` regex case-insensitive and trailing-slash tolerant (`r"/resource[Gg]roups/([^/]+)(?:/|$)"`).
- [low -> patch] BH-3: Added `hub_subscription_id` property on `NetworkingPolicyRule` extracting subscription ID from `private_dns_zone_id`.
- [low -> patch] BH-4: Made `resolve_hub_dns_zone` fallback RG deterministic by checking `"default"` rule before falling back to `"rg-hub-dns"`.
- [low -> patch] BH-5: Raised `StandardsError` in `synthesize_data` if `dns_info.get("name")` is empty.
- [medium -> patch] BH-6 / EH-1: Added corporate naming convention validation for `pe_name` against `azurerm_private_endpoint` rule.
- [low -> patch] BH-8: Implemented validation in `synthesize_main` ensuring non-empty `subresource_names`.
- [medium -> patch] BH-9 / EH-5: Aligned terminal summary check condition to `if params.selected_subnet and params.network_action != "none":`.
- [low -> patch] BH-13: Added whitespace trimming on `ProvisioningParameters.selected_subnet`.
- [low -> patch] BH-15: Added test coverage in `tests/test_private_endpoint.py` verifying `network_action="none"` suppression.
- [medium -> patch] VG-1: Added unit tests in `tests/test_standards_models.py` and `tests/test_standards_engine.py` verifying custom `hub_resource_group` and `hub_subscription_id` extraction.
- [medium -> patch] VG-2: Added test `test_provisioning_flow_paas_without_subnet_warns_omission` in `tests/test_private_endpoint.py`.
- [medium -> patch] VG-Other-1 / EH-2: In `resolve_networking_policy`, extract zone name from `rule.private_dns_zone_id` before falling back to `default_dns`.
- [medium -> defer] BH-1: Deferred cross-subscription Hub DNS provider alias configuration.
- [low -> defer] BH-7: Pre-existing domain resource name validation.
- [low -> defer] BH-10: Pre-existing missing subnet network policy configuration in `scaffold_subnet`.
- [low -> defer] BH-11: Deferred multi-zone private DNS zone group bundling to deferred work.
- [false] BH-12: Omitting `outputs.tf` follows architectural lean layout rule (AD-3).
- [false] BH-14: Catalog dictionary completeness is verified by unit test `test_paas_catalog_has_all_tier_1_paas_services`.
- [low -> defer] EH-3, EH-4: Pre-existing interactive prompt edge cases in subnet flow from Story 2.3.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_private_endpoint.py` -- expected: All Private Endpoint and DNS zone tests pass.
- `./.venv/bin/pytest tests/test_scaffold.py` -- expected: All scaffolding engine tests pass.
- `./.venv/bin/pytest tests/test_architecture.py` -- expected: Architectural boundary assertions pass.
- `./.venv/bin/pytest` -- expected: Full test suite passes (345+ tests).

