# Deferred Work

- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-tier-1-paas-scaffolding-with-mandatory-public-network-access.md`
  summary: Expand `ProvisioningFlow._collect_resource_type` to allow all Tier 1 and Tier 2 PaaS resources beyond those in naming conventions.
  evidence: `_collect_resource_type` currently bounds choices to `self.standards.bundle.naming_rules.keys()`, which only contains naming conventions for storage account and key vault; to be broadened in Story 3.4 (Universal Resource Catalog scaffolding).

- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-tier-1-paas-scaffolding-with-mandatory-public-network-access.md`
  summary: Provide complete baseline schema arguments in `RESOURCE_DEFAULTS` for all long-tail PaaS services.
  evidence: Baseline defaults currently exist only for storage account, key vault, and vnet; full schema synthesis across all PaaS resources is scheduled for Story 3.4.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-tier-1-paas-scaffolding-with-mandatory-public-network-access.md`
  summary: Ensure deterministic lexicographical ordering of top-level resource block attributes in `HclBlock.render()`.
  evidence: Pre-existing implementation in `ttassistant/domain/hcl.py` iterates over `scalar_attrs.items()` in dictionary insertion order rather than sorted keys.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-automated-private-endpoint-hub-private-dns-zone-group-bundli.md`
  summary: Support multi-zone Private DNS Zone Group bundling for multi-subresource services.
  evidence: `private_dns_zone_group` currently links to a single Hub Private DNS zone; services such as App Services requiring SCM and standard endpoints or multi-endpoint Cosmos DB can be expanded for multi-zone support in future iterations.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-automated-private-endpoint-hub-private-dns-zone-group-bundli.md`
  summary: Add explicit `private_endpoint_network_policies` setting in `scaffold_subnet`.
  evidence: `scaffold_subnet` from Story 2.3 currently generates baseline `azurerm_subnet` without setting network policies for private endpoints.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-4-tier-2-universal-azure-long-tail-resource-scaffolding.md`
  summary: Make default location for `azurerm_resource_group` configurable via standards or CLI flag instead of hardcoded `"westeurope"`.
  evidence: `ScaffoldEngine.synthesize_main` sets `attributes["location"] = "westeurope"` for `azurerm_resource_group`, which is pre-existing from Epic 1.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-4-tier-2-universal-azure-long-tail-resource-scaffolding.md`
  summary: Use `ResourceTier.display_name` in `catalog list` and `catalog info` commands instead of hardcoded ANSI tier labels.
  evidence: `ttassistant/cli.py` commands hardcode ANSI formatting strings instead of utilizing `ResourceTier.display_name` property from Story 3.1.


