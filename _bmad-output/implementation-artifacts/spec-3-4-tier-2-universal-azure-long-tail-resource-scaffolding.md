---
title: 'Story 3.4: Tier 2 Universal Azure Long-Tail Resource Scaffolding'
type: 'feature'
created: '2026-09-28'
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

**Problem:** While Tier 1 PaaS services have guided conversational scaffolding and security triad bundling, developers also need to author arbitrary Azure infrastructure resources (e.g. `azurerm_log_analytics_workspace`, `azurerm_application_insights`, `azurerm_network_security_group`, etc.) while maintaining corporate compliance: compliant naming prefixes, mandatory tagging baselines, decoupled remote state backends, and lean directory layouts.

**Approach:** Extend `ScaffoldEngine`, `StandardsEngine`, and `ProvisioningFlow` to leverage the offline `ResourceCatalogPort` (`azurerm_schema.json`) for Tier 2 universal long-tail resources, synthesizing syntactically valid HCL blocks with required schema attributes, Cloud Adoption Framework (CAF) naming prefixes, mandatory enterprise tags, decoupled resource group data sources, and isolated `backend.tf` state, while omitting `variables.tf`, `outputs.tf`, and subnet prompts.

## Boundaries & Constraints

**Always:**
- Keep domain scaffolding and standards logic strictly isolated in `ttassistant.domain` (`scaffold.py`, `standards.py`), preserving pure Hexagonal Architecture (AD-1).
- Recognize all 21 Tier 2 AzureRM resources defined in `ttassistant/data/azurerm_schema.json` in addition to Tier 1 resources.
- For all Tier 2 resources, synthesize a valid `main.tf` block containing:
  - `name`: computed via `StandardsEngine.compute_resource_name`, adhering to corporate naming rules or CAF standard resource prefixes (e.g. `law-` for Log Analytics, `appi-` for Application Insights, `nsg-` for NSG, etc.).
  - `resource_group_name`: set to `HclReference("data.azurerm_resource_group.primary.name")` when the resource schema accepts `resource_group_name`.
  - `location`: set to `HclReference("data.azurerm_resource_group.primary.location")` when the resource schema accepts `location`.
  - Required schema arguments: populate schema default values or sensible typed defaults/placeholders (e.g. `application_type = "web"`, `sku = "Premium"`, `sku_name = "Standard"`, etc.) ensuring 100% syntactically valid HCL.
  - Complex nested blocks: render required child blocks (e.g. `default_node_pool` for AKS, `ip_configuration` for NIC/Bastion, `template` for Container App) as clean HCL blocks.
  - `tags`: inject all mandatory corporate tags resolved from `common_standards/tagging_baseline.md`.
- Generate decoupled `data.tf` containing `data "azurerm_resource_group" "primary"` referencing `rg-{subscription}` without remote state (AD-3, FR-7).
- Generate isolated `backend.tf` with subscription-specific key template from `common_standards/backend_mapping.md`.
- Enforce the Lean File Layout rule (AD-3): scaffold only `main.tf`, `data.tf`, and `backend.tf`, omitting `variables.tf` and `outputs.tf` by default.
- Skip conversational subnet discovery prompts for Tier 2 resources unless `--subnet` is explicitly pre-seeded.
- Ensure all generated HCL documents parse cleanly with `python-hcl2.loads()` without syntax errors.

**Never:**
- Never execute external `terraform` or `az` CLI binaries (AD-2, NFR-5).
- Never invoke external cloud network APIs or ARM REST endpoints; operate purely air-gapped in memory.
- Never emit `terraform_remote_state` blocks across any generated files (AD-3, FR-7).
- Never scaffold `azurerm_private_endpoint` or `azurerm_private_dns_zone` blocks for Tier 2 long-tail resources unless explicitly configured.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Tier 2 Standard Long-Tail Resource | `resource_type="azurerm_log_analytics_workspace"`, `subscription="workload-dev"` | `main.tf` with `name = "law-appdata-dev"`, `location = data.azurerm_resource_group.primary.location`, `resource_group_name = data.azurerm_resource_group.primary.name`, mandatory tags; `data.tf` with RG data source; `backend.tf` with `dev/azurerm_log_analytics_workspace.tfstate` | N/A |
| Tier 2 with Schema Defaults | `resource_type="azurerm_application_insights"` | `main.tf` contains `application_type = "web"` (from schema default) alongside name, location, RG, and tags | N/A |
| Tier 2 Without Location Attribute | `resource_type="azurerm_dns_zone"` | `main.tf` includes `name` and `resource_group_name`; cleanly omits `location` | Omission based on schema argument inspection |
| Tier 2 with Required Complex Nested Block | `resource_type="azurerm_kubernetes_cluster"` | `main.tf` contains `dns_prefix` and nested `default_node_pool { ... }` block; parses cleanly with `hcl2` | Generates valid HCL block structure |
| Tier 2 Subnet Prompt Suppression | User runs interactive flow with Tier 2 resource | Flow skips subnet candidate search and prompts; directly proceeds to diff preview | N/A |
| Tier 2 Explicit Pre-Seeded Subnet | User runs `ttassistant new -r azurerm_network_interface --subnet snet-app-prod` | `params.selected_subnet = "snet-app-prod"`, wires `subnet_id` into `ip_configuration` | N/A |
| Unknown Resource Type | User passes `resource_type="azurerm_nonexistent_xyz"` | Exits with error code 2 indicating unknown resource type not in catalog or standards | Non-crashing validation error |
| Lean File Layout Enforcement | Any Tier 2 scaffolding | `workspace.files` contains strictly `main.tf`, `data.tf`, `backend.tf`; no `variables.tf` or `outputs.tf` | Asserted in workspace inspection |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/catalog.py` -- Provide Tier 2 resource constants and helpers.
- `ttassistant/domain/standards.py` -- Extend `StandardsEngine.compute_resource_name` to support CAF resource prefixes for Tier 2 resources when no explicit entry exists in `naming_conventions.md`.
- `ttassistant/domain/scaffold.py` -- Update `ScaffoldEngine` to accept optional `ResourceCatalogPort`, inspect resource schema, inject required arguments and defaults for Tier 2 resources, and omit non-applicable attributes (e.g. `location` for DNS zones).
- `ttassistant/application/provisioning_flow.py` -- Update `ProvisioningFlow` to accept `ResourceCatalogPort`, allow selecting/validating any cataloged resource type, and suppress subnet discovery prompts for Tier 2 resources when `--subnet` is not pre-seeded.
- `ttassistant/cli.py` -- Inject `JsonResourceCatalogAdapter` into `ProvisioningFlow` within `ttassistant new`.
- `tests/test_tier_2_scaffold.py` -- New unit tests covering Tier 2 scaffolding, CAF naming, schema defaults, complex block synthesis, lean layout, and HCL AST validation via `python-hcl2`.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/standards.py` -- Add CAF resource prefix mappings (`DEFAULT_RESOURCE_PREFIXES`) in `compute_resource_name` while preserving existing fallback behavior for unknown types.
- [x] `ttassistant/domain/scaffold.py` -- Enhance `ScaffoldEngine.synthesize_main` and `ScaffoldEngine.__init__` to support `catalog: Optional[ResourceCatalogPort]`, populate required schema attributes and defaults for Tier 2, and omit non-existent attributes (`location`/`resource_group_name`).
- [x] `ttassistant/application/provisioning_flow.py` -- Update `ProvisioningFlow` to accept `catalog: Optional[ResourceCatalogPort]`, validate resource types against catalog, and suppress subnet discovery prompts for Tier 2 unless pre-seeded.
- [x] `ttassistant/cli.py` -- Wire `JsonResourceCatalogAdapter` into `ProvisioningFlow` in the `new` command.
- [x] `tests/test_tier_2_scaffold.py` -- Create comprehensive test suite testing all 21 Tier 2 resources, naming conventions, lean file layout, and HCL syntax validation.

**Acceptance Criteria:**
- Given any valid Tier 2 `azurerm_*` resource type in `azurerm_schema.json`, when scaffolding is initiated, then `main.tf` contains valid HCL with compliant naming, required schema attributes, and mandatory corporate tags.
- Given a Tier 2 resource scaffolding run, when files are staged, then strictly `main.tf`, `data.tf`, and `backend.tf` are staged without `variables.tf` or `outputs.tf`.
- Given all 21 Tier 2 resources, when each is scaffolded into memory, then all generated `.tf` files parse with `python-hcl2.loads()` with zero syntax errors.

## Implementation Notes

- Added `DEFAULT_RESOURCE_PREFIXES` in `ttassistant.domain.standards` implementing standard Microsoft Cloud Adoption Framework naming prefixes for Tier 2 resources.
- Extended `ttassistant.domain.catalog` with `TIER_2_RESOURCES`, `is_tier_2_resource`, and `is_tier_2` aliases.
- Enhanced `ScaffoldEngine` in `ttassistant.domain.scaffold` to accept `catalog: Optional[ResourceCatalogPort]`, populated required arguments and defaults, correctly omitted attributes not present in schema (such as `location` in DNS zones or `resource_group_name` in SQL database), and rendered required nested child blocks (`default_node_pool`, `ip_configuration`, `template`, `private_service_connection`).
- Updated `ProvisioningFlow` in `ttassistant.application.provisioning_flow` to accept `catalog: Optional[ResourceCatalogPort]`, validate all 33 cataloged resources in addition to standards-defined types while maintaining menu ordering, and suppressed subnet discovery/prompts for Tier 2 resources unless pre-seeded via `--subnet`.
- Injected `JsonResourceCatalogAdapter` into `ProvisioningFlow` in `ttassistant.cli` `new` command.
- Created `tests/test_tier_2_scaffold.py` with 33 unit and integration tests verifying all 21 Tier 2 resources, CAF naming, schema defaults, complex block synthesis, lean layout, and HCL AST validation via `python-hcl2`.
- Total test suite now passes 392 tests with zero regressions.

## Spec Change Log

## Review Triage Log

| Finding | Reviewer | Verdict | Route | Evidence / Resolution |
| :--- | :--- | :--- | :--- | :--- |
| VG-1: Missing CLI integration test for Tier 2 resource scaffolding | Verification Gap | medium | patch | Added `test_cli_new_tier_2_resource_success` running `ttassistant new` for `azurerm_log_analytics_workspace` verifying code 0 and file staging. |
| VG-2: Incomplete assertion of required schema attributes across all 21 resources | Verification Gap | medium | patch | Expanded `test_all_21_tier_2_resources_scaffolding_and_ast_validation` to assert each required schema argument and nested block in `main_hcl`. |
| BH-1: Missing CAF prefixes for 7 Tier 2 resources | Blind Hunter | medium | patch | Added `cog-`, `ca-`, `cae-`, `sqldb-`, `nic-`, `pdns-`, `srch-` to `DEFAULT_RESOURCE_PREFIXES` in `standards.py`. |
| EC-2: Pre-seeded resource type case sensitivity | Edge Case | low | patch | Normalized `rt = pre_seeded.strip().lower()` with case-insensitive matching in `_collect_resource_type`. |
| EC-3: Dangling subnet reference for NIC when network action is none | Edge Case | medium | patch | Guarded `subnet_ref` in `_add_tier_2_nested_blocks` with `params.selected_subnet and params.network_action != "none"`. |
| EC-4: Cross-sub self-reference case sensitivity | Edge Case | low | patch | Added case-insensitive strip check `sub_source.strip().lower() == params.subscription.strip().lower()`. |
| EC-5: ScaffoldEngine catalog sharing in flow initialization | Edge Case | low | patch | Updated `self.catalog = catalog or (scaffold_engine.catalog if scaffold_engine else None)` in `ProvisioningFlow.__init__`. |
| BH-6: Missing map attribute type handling in schema synthesis | Blind Hunter | low | patch | Added `map` / `map(string)` attribute type handling (default `{}`) in `ScaffoldEngine.synthesize_main`. |
| BH-10: Subnet prompt suppression for non-cataloged long-tail resources | Blind Hunter | medium | patch | Set `is_tier_2 = not is_tier_1_resource(resource_type)` to reliably suppress subnet prompts for all non-Tier-1 resources. |
| BH-4: Unreferenced resource group data source for mssql_database | Blind Hunter | false | dismiss | Harmless ambient RG context provided in subscription folder; consistent with decoupled state pattern. |
| BH-7: Ignored public network access flag for Tier 2 resources | Blind Hunter | false | dismiss | Enterprise Security Triad and public network access denial strictly applies to Tier 1 PaaS per AD-7 and spec. |
| BH-8: Hardcoded westeurope location for azurerm_resource_group | Blind Hunter | medium | defer | Pre-existing from Epic 1; recorded in deferred-work.md. |
| BH-9: ArgumentLookupList dual list/dict behavior | Blind Hunter | low | defer | Pre-existing from Story 3.1; recorded in deferred-work.md. |
| BH-13: Hardcoded ANSI tier labels in catalog CLI | Blind Hunter | low | defer | Pre-existing from Story 3.1; recorded in deferred-work.md. |
| BH-14: Silent fallback to dev environment | Blind Hunter | low | defer | Pre-existing from Epic 1; recorded in deferred-work.md. |


## Design Notes

### CAF Resource Prefix Mappings
For common Tier 2 resources without explicit regex patterns in `naming_conventions.md`, `compute_resource_name` defaults to standard Microsoft Cloud Adoption Framework abbreviations:
- `azurerm_log_analytics_workspace` -> `law-{workload}-{env}`
- `azurerm_application_insights` -> `appi-{workload}-{env}`
- `azurerm_network_security_group` -> `nsg-{workload}-{env}`
- `azurerm_public_ip` -> `pip-{workload}-{env}`
- `azurerm_container_registry` -> `cr{workload}{env}`
- `azurerm_kubernetes_cluster` -> `aks-{workload}-{env}`
- `azurerm_api_management` -> `apim-{workload}-{env}`
- `azurerm_firewall` -> `afw-{workload}-{env}`
- `azurerm_user_assigned_identity` -> `id-{workload}-{env}`
- `azurerm_bastion_host` -> `bas-{workload}-{env}`
- `azurerm_dns_zone` -> `dns-{workload}-{env}`
- `azurerm_service_plan` -> `asp-{workload}-{env}`
- `azurerm_servicebus_namespace` -> `sb-{workload}-{env}`

If a resource type is not in the CAF prefix table and not in `naming_conventions.md`, it falls back to `{workload}-{env}` (or `{workload}` if environment is empty).

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_tier_2_scaffold.py` -- expected: All Tier 2 scaffolding tests pass.
- `./.venv/bin/pytest` -- expected: Full test suite passes (>= 370 tests) with zero regressions.
- `./.venv/bin/python -m ttassistant new -r azurerm_log_analytics_workspace -sub workload-dev -w appdata -e dev -y` -- expected: Generates compliant workspace with zero errors.

