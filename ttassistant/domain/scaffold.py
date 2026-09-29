"""Standards-governed greenfield Terraform scaffolding engine."""

import ipaddress
import logging
import re
from typing import Any, Optional

from ttassistant.domain.hcl import (
    HclBlock,
    HclReference,
    build_backend_block,
    build_data_block,
    build_resource_block,
    render_hcl_document,
)
from ttassistant.domain.catalog import get_paas_subresource_names, is_tier_1_paas
from ttassistant.domain.exceptions import StandardsError
from ttassistant.domain.models import (
    ProvisioningParameters,
    StagedFile,
    StagedWorkspace,
)
from ttassistant.domain.standards import StandardsEngine
from ttassistant.ports.catalog import ResourceCatalogPort

logger = logging.getLogger(__name__)

# Default AzureRM resource-specific baseline attributes
RESOURCE_DEFAULTS: dict[str, dict[str, Any]] = {
    "azurerm_storage_account": {
        "account_tier": "Standard",
        "account_replication_type": "LRS",
    },
    "azurerm_key_vault": {
        "sku_name": "standard",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
    },
    "azurerm_virtual_network": {
        "address_space": ["10.0.0.0/16"],
    },
    "azurerm_api_management": {
        "publisher_name": "Corporate",
        "publisher_email": "admin@corporate.local",
        "sku_name": "Developer_1",
    },
    "azurerm_application_insights": {
        "application_type": "web",
    },
    "azurerm_cognitive_account": {
        "kind": "OpenAI",
        "sku_name": "S0",
    },
    "azurerm_container_app": {
        "container_app_environment_id": "",
    },
    "azurerm_container_registry": {
        "sku": "Premium",
    },
    "azurerm_firewall": {
        "sku_name": "AZFW_VNet",
        "sku_tier": "Standard",
    },
    "azurerm_mssql_database": {
        "server_id": "",
    },
    "azurerm_public_ip": {
        "allocation_method": "Static",
    },
    "azurerm_search_service": {
        "sku": "standard",
    },
    "azurerm_service_plan": {
        "os_type": "Linux",
        "sku_name": "B1",
    },
    "azurerm_servicebus_namespace": {
        "sku": "Standard",
    },
}

RESOURCE_NO_LOCATION = {"azurerm_subnet"}

AZURE_RESERVED_SUBNETS: frozenset[str] = frozenset({
    "GatewaySubnet",
    "AzureBastionSubnet",
    "AzureFirewallSubnet",
    "AzureFirewallManagementSubnet",
    "RouteServerSubnet",
})


class ScaffoldEngine:
    """Domain service responsible for greenfield Terraform workspace scaffolding."""

    def __init__(
        self,
        standards: StandardsEngine,
        catalog: Optional[ResourceCatalogPort] = None,
    ) -> None:
        """Initialize the scaffolding engine with a standards engine and optional resource catalog.

        Args:
            standards: StandardsEngine domain service.
            catalog: Optional ResourceCatalogPort for schema-governed argument generation.
        """
        self.standards = standards
        self.catalog = catalog

    def synthesize_backend(self, params: ProvisioningParameters) -> StagedFile:
        """Synthesize backend.tf with isolated Azure Blob remote state coordinates."""
        backend_info = self.standards.resolve_backend(
            subscription=params.subscription,
            resource_type=params.resource_type,
        )

        config: dict[str, Any] = {}
        if backend_info.get("resource_group_name"):
            config["resource_group_name"] = backend_info["resource_group_name"]
        config["storage_account_name"] = backend_info["storage_account_name"]
        config["container_name"] = backend_info["container_name"]
        config["key"] = backend_info["key"]

        block = build_backend_block(backend_type="azurerm", **config)
        content = render_hcl_document([block])

        return StagedFile(
            path="backend.tf",
            content=content,
            is_new=True,
            metadata={"type": "backend", "subscription": params.subscription},
        )

    def synthesize_data(self, params: ProvisioningParameters) -> StagedFile:
        """Synthesize data.tf with decoupled upstream data sources (RG, and optional VNet & Subnet)."""
        backend_info = self.standards.resolve_backend(
            subscription=params.subscription,
            resource_type=params.resource_type,
        )

        rg_name = backend_info.get("resource_group_name") or f"rg-{params.subscription.lower().replace('_', '-')}"

        # Validate parent RG name against corporate naming conventions
        rg_rule = self.standards.bundle.get_naming_rule("azurerm_resource_group")
        if rg_rule is not None:
            is_valid, err = rg_rule.validate_name(rg_name)
            if not is_valid:
                raise ValueError(err or f"Invalid resource group name '{rg_name}'")

        blocks: list[HclBlock] = []

        # 1. Primary Resource Group data source
        rg_block = build_data_block(
            data_type="azurerm_resource_group",
            name="primary",
            attributes={"name": rg_name},
        )
        blocks.append(rg_block)

        # 2. Virtual Network and Subnet data sources when subnet is selected
        vnet_name: Optional[str] = None
        if params.selected_subnet and params.network_action != "none":
            # Validate subnet name against corporate naming conventions (allowing Azure-reserved subnet names)
            if params.selected_subnet not in AZURE_RESERVED_SUBNETS:
                snet_rule = self.standards.bundle.get_naming_rule("azurerm_subnet")
                if snet_rule is not None:
                    is_valid, err = snet_rule.validate_name(params.selected_subnet)
                    if not is_valid:
                        raise ValueError(err or f"Invalid subnet name '{params.selected_subnet}'")

            is_cross_sub = params.network_action in ("cross_subscription", "remote") or bool(params.cross_sub_source)
            if is_cross_sub:
                sub_source = (params.cross_sub_source or "").strip()
                if not sub_source or not re.fullmatch(r"^[a-zA-Z0-9_-]+$", sub_source):
                    raise ValueError(f"Invalid remote subscription format '{sub_source}'")
                if sub_source.strip().lower() == params.subscription.strip().lower():
                    raise ValueError("Remote subscription cannot be the same as target subscription")

                normalized_sub = sub_source.lower().replace("_", "-")
                vnet_name = params.selected_vnet or f"vnet-{normalized_sub}"
                vnet_rg = params.selected_subnet_rg or f"rg-{normalized_sub}"
                provider_alias = sub_source.replace("-", "_")
                if provider_alias and provider_alias[0].isdigit():
                    provider_alias = f"sub_{provider_alias}"

                # Validate VNet name
                vnet_rule = self.standards.bundle.get_naming_rule("azurerm_virtual_network")
                if vnet_rule is not None:
                    is_valid, err = vnet_rule.validate_name(vnet_name)
                    if not is_valid:
                        raise ValueError(err or f"Invalid virtual network name '{vnet_name}'")

                # Validate remote subnet RG name if specified or inferred
                if rg_rule is not None and isinstance(vnet_rg, str):
                    is_valid, err = rg_rule.validate_name(vnet_rg)
                    if not is_valid:
                        raise ValueError(err or f"Invalid resource group name '{vnet_rg}'")

                vnet_attrs = {
                    "name": vnet_name,
                    "provider": HclReference(f"azurerm.{provider_alias}"),
                    "resource_group_name": vnet_rg,
                }
                vnet_block = build_data_block(
                    data_type="azurerm_virtual_network",
                    name="primary",
                    attributes=vnet_attrs,
                )
                blocks.append(vnet_block)

                snet_attrs = {
                    "name": params.selected_subnet,
                    "provider": HclReference(f"azurerm.{provider_alias}"),
                    "resource_group_name": HclReference("data.azurerm_virtual_network.primary.resource_group_name"),
                    "virtual_network_name": HclReference("data.azurerm_virtual_network.primary.name"),
                }
                snet_block = build_data_block(
                    data_type="azurerm_subnet",
                    name="primary",
                    attributes=snet_attrs,
                )
                blocks.append(snet_block)
            else:
                normalized_sub = params.subscription.lower().replace("_", "-")
                vnet_name = params.selected_vnet or f"vnet-{normalized_sub}"

                # Validate VNet name
                vnet_rule = self.standards.bundle.get_naming_rule("azurerm_virtual_network")
                if vnet_rule is not None:
                    is_valid, err = vnet_rule.validate_name(vnet_name)
                    if not is_valid:
                        raise ValueError(err or f"Invalid virtual network name '{vnet_name}'")

                if params.selected_subnet_rg and params.selected_subnet_rg != rg_name:
                    if rg_rule is not None:
                        is_valid, err = rg_rule.validate_name(params.selected_subnet_rg)
                        if not is_valid:
                            raise ValueError(err or f"Invalid resource group name '{params.selected_subnet_rg}'")
                    vnet_rg_ref: Any = params.selected_subnet_rg
                else:
                    vnet_rg_ref = HclReference("data.azurerm_resource_group.primary.name")

                vnet_attrs = {
                    "name": vnet_name,
                    "resource_group_name": vnet_rg_ref,
                }
                vnet_block = build_data_block(
                    data_type="azurerm_virtual_network",
                    name="primary",
                    attributes=vnet_attrs,
                )
                blocks.append(vnet_block)

                snet_attrs = {
                    "name": params.selected_subnet,
                    "resource_group_name": HclReference("data.azurerm_virtual_network.primary.resource_group_name"),
                    "virtual_network_name": HclReference("data.azurerm_virtual_network.primary.name"),
                }
                snet_block = build_data_block(
                    data_type="azurerm_subnet",
                    name="primary",
                    attributes=snet_attrs,
                )
                blocks.append(snet_block)

        # 3. Hub Private DNS Zone data source for Tier 1 PaaS when subnet is selected (AD-7, FR-13)
        dns_info: Optional[dict[str, str]] = None
        if is_tier_1_paas(params.resource_type) and params.selected_subnet and params.network_action != "none":
            dns_info = self.standards.resolve_hub_dns_zone(params.resource_type)
            zone_name = dns_info.get("name") if dns_info else ""
            if not zone_name:
                raise StandardsError(
                    f"No Private DNS Zone resolved for Tier 1 PaaS resource '{params.resource_type}'.",
                    details="Ensure networking_policy.md defines a Private DNS Zone or provider defaults exist.",
                )
            dns_block = build_data_block(
                data_type="azurerm_private_dns_zone",
                name="hub",
                attributes={
                    "name": zone_name,
                    "resource_group_name": dns_info["resource_group_name"],
                },
            )
            blocks.append(dns_block)

        content = render_hcl_document(blocks)

        metadata: dict[str, Any] = {"type": "data_sources", "resource_group": rg_name}
        if params.selected_subnet:
            metadata["subnet"] = params.selected_subnet
        if vnet_name:
            metadata["vnet"] = vnet_name
        if dns_info and dns_info.get("name"):
            metadata["private_dns_zone"] = dns_info["name"]

        return StagedFile(
            path="data.tf",
            content=content,
            is_new=True,
            metadata=metadata,
        )

    def _add_tier_2_nested_blocks(self, block: HclBlock, params: ProvisioningParameters) -> None:
        """Add required complex child blocks for Tier 2 resources."""
        rt = params.resource_type
        if rt == "azurerm_kubernetes_cluster":
            block.add_nested_block(
                HclBlock(
                    block_type="default_node_pool",
                    attributes={
                        "name": "default",
                        "node_count": 1,
                        "vm_size": "Standard_DS2_v2",
                    },
                )
            )
        elif rt == "azurerm_network_interface":
            subnet_ref: Any = (
                HclReference("data.azurerm_subnet.primary.id")
                if (params.selected_subnet and params.network_action != "none")
                else ""
            )
            block.add_nested_block(
                HclBlock(
                    block_type="ip_configuration",
                    attributes={
                        "name": "internal",
                        "subnet_id": subnet_ref,
                        "private_ip_address_allocation": "Dynamic",
                    },
                )
            )
        elif rt == "azurerm_bastion_host":
            subnet_ref = (
                HclReference("data.azurerm_subnet.primary.id")
                if (params.selected_subnet and params.network_action != "none")
                else ""
            )
            block.add_nested_block(
                HclBlock(
                    block_type="ip_configuration",
                    attributes={
                        "name": "configuration",
                        "subnet_id": subnet_ref,
                        "public_ip_address_id": "",
                    },
                )
            )
        elif rt == "azurerm_container_app":
            container_block = HclBlock(
                block_type="container",
                attributes={
                    "name": "app",
                    "image": "mcr.microsoft.com/azuredocs/aci-helloworld:latest",
                    "cpu": 0.25,
                    "memory": "0.5Gi",
                },
            )
            block.add_nested_block(
                HclBlock(
                    block_type="template",
                    nested_blocks=[container_block],
                )
            )
        elif rt == "azurerm_private_endpoint":
            block.add_nested_block(
                HclBlock(
                    block_type="private_service_connection",
                    attributes={
                        "name": "psc",
                        "private_connection_resource_id": "",
                        "is_manual_connection": False,
                    },
                )
            )

    def synthesize_main(self, params: ProvisioningParameters) -> StagedFile:
        """Synthesize main.tf with primary resource, mandatory compliance tags, and companion private endpoint."""
        attributes: dict[str, Any] = {
            "name": params.resource_name,
        }

        # Check schema or fallback rules for location and resource_group_name
        schema = self.catalog.get_resource_schema(params.resource_type) if self.catalog else None

        if params.resource_type == "azurerm_resource_group":
            attributes["location"] = "westeurope"
        else:
            accepts_rg = True
            accepts_location = True
            if schema is not None:
                accepts_rg = "resource_group_name" in schema.arguments
                accepts_location = "location" in schema.arguments
            else:
                if params.resource_type in ("azurerm_mssql_database",):
                    accepts_rg = False
                if params.resource_type in RESOURCE_NO_LOCATION or params.resource_type in (
                    "azurerm_dns_zone",
                    "azurerm_private_dns_zone",
                    "azurerm_container_app",
                    "azurerm_mssql_database",
                ):
                    accepts_location = False

            if accepts_rg:
                attributes["resource_group_name"] = HclReference(
                    "data.azurerm_resource_group.primary.name"
                )
            if accepts_location:
                attributes["location"] = HclReference(
                    "data.azurerm_resource_group.primary.location"
                )

        # Apply standard defaults for resource type if known
        if params.resource_type in RESOURCE_DEFAULTS:
            attributes.update(RESOURCE_DEFAULTS[params.resource_type])

        # If schema is available, populate required schema arguments and defaults
        if schema is not None:
            for arg_name, arg_schema in schema.arguments.items():
                if arg_name in ("name", "resource_group_name", "location", "tags"):
                    continue
                # Do not set complex nested block types as top-level attributes
                if arg_schema.type == "object" or arg_schema.type.startswith("list(object)"):
                    continue
                if arg_schema.required and arg_name not in attributes:
                    if arg_schema.default is not None:
                        attributes[arg_name] = arg_schema.default
                    elif arg_name == "dns_prefix":
                        attributes[arg_name] = params.resource_name
                    elif arg_schema.type == "string":
                        attributes[arg_name] = ""
                    elif arg_schema.type == "number":
                        attributes[arg_name] = 1
                    elif arg_schema.type == "bool":
                        attributes[arg_name] = False
                    elif arg_schema.type in ("list", "set") or arg_schema.type.startswith("list("):
                        attributes[arg_name] = []
                    elif arg_schema.type in ("map", "map(string)") or arg_schema.type.startswith("map("):
                        attributes[arg_name] = {}

        if params.resource_type == "azurerm_kubernetes_cluster" and "dns_prefix" not in attributes:
            attributes["dns_prefix"] = params.resource_name

        if params.resource_type == "azurerm_private_endpoint" and "subnet_id" not in attributes:
            attributes["subnet_id"] = (
                HclReference("data.azurerm_subnet.primary.id")
                if params.selected_subnet
                else ""
            )

        # Enforce mandatory public network access denial for Tier 1 PaaS resources (AD-7, FR-12)
        if is_tier_1_paas(params.resource_type):
            attributes["public_network_access_enabled"] = params.public_network_access

        # Apply mandatory corporate compliance tags
        final_tags = self.standards.apply_default_tags(params.tags)
        if final_tags:
            attributes["tags"] = final_tags

        primary_block = build_resource_block(
            resource_type=params.resource_type,
            name="primary",
            attributes=attributes,
        )

        # Add complex nested blocks for Tier 2 resources
        self._add_tier_2_nested_blocks(primary_block, params)

        blocks: list[HclBlock] = [primary_block]

        # Bundle companion azurerm_private_endpoint for Tier 1 PaaS resources when subnet is selected (AD-7, FR-13)
        if is_tier_1_paas(params.resource_type):
            if params.selected_subnet and params.network_action != "none":
                pe_name = f"pe-{params.resource_name}"
                pe_rule = self.standards.bundle.get_naming_rule("azurerm_private_endpoint")
                if pe_rule is not None:
                    is_valid, err = pe_rule.validate_name(pe_name)
                    if not is_valid:
                        raise ValueError(err or f"Invalid private endpoint name '{pe_name}'")

                pe_attributes: dict[str, Any] = {
                    "name": pe_name,
                    "location": HclReference("data.azurerm_resource_group.primary.location"),
                    "resource_group_name": HclReference("data.azurerm_resource_group.primary.name"),
                    "subnet_id": HclReference("data.azurerm_subnet.primary.id"),
                }
                if final_tags:
                    pe_attributes["tags"] = final_tags

                psc_block = HclBlock(
                    block_type="private_service_connection",
                    attributes={
                        "name": f"psc-{params.resource_name}",
                        "private_connection_resource_id": HclReference(f"{params.resource_type}.primary.id"),
                        "is_manual_connection": False,
                        "subresource_names": get_paas_subresource_names(params.resource_type),
                    },
                )
                pdz_group_block = HclBlock(
                    block_type="private_dns_zone_group",
                    attributes={
                        "name": "default",
                        "private_dns_zone_ids": [HclReference("data.azurerm_private_dns_zone.hub.id")],
                    },
                )
                pe_block = HclBlock(
                    block_type="resource",
                    labels=["azurerm_private_endpoint", "primary"],
                    attributes=pe_attributes,
                    nested_blocks=[psc_block, pdz_group_block],
                )
                blocks.append(pe_block)
            else:
                logger.info(
                    "Tier 1 PaaS resource '%s' scaffolded without subnet; private endpoint omitted.",
                    params.resource_type,
                )

        content = render_hcl_document(blocks)

        metadata: dict[str, Any] = {
            "type": "primary_resource",
            "resource_type": params.resource_type,
        }
        if is_tier_1_paas(params.resource_type) and params.selected_subnet and params.network_action != "none":
            metadata["private_endpoint"] = f"pe-{params.resource_name}"

        return StagedFile(
            path="main.tf",
            content=content,
            is_new=True,
            metadata=metadata,
        )

    def scaffold(self, params: ProvisioningParameters) -> StagedWorkspace:
        """Synthesize complete in-memory StagedWorkspace for validated parameters.

        Args:
            params: Validated ProvisioningParameters.

        Returns:
            StagedWorkspace targeting <resource_type>/<subscription>/.
        """
        target_dir = f"{params.resource_type}/{params.subscription}/"

        backend_file = self.synthesize_backend(params)
        main_file = self.synthesize_main(params)

        workspace = StagedWorkspace(
            target_dir=target_dir,
            parameters=params,
            metadata={"generator": "ttassistant.domain.scaffold"},
        )
        workspace.add_file(main_file)
        if params.resource_type != "azurerm_resource_group":
            data_file = self.synthesize_data(params)
            workspace.add_file(data_file)
        workspace.add_file(backend_file)

        return workspace

    def scaffold_subnet(
        self,
        subscription: str,
        subnet_name: str,
        address_prefixes: list[str] | str = "10.0.1.0/24",
        vnet_name: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
        environment: Optional[str] = None,
        workspace: Optional[StagedWorkspace] = None,
    ) -> list[StagedFile]:
        """Synthesize standards-compliant azurerm_subnet configuration files with isolated backend and tags.

        Args:
            subscription: Target subscription identifier.
            subnet_name: Desired subnet name (validated against naming rules).
            address_prefixes: CIDR prefix string or list of CIDR strings.
            vnet_name: Optional target virtual network name.
            tags: Optional resource tags dictionary.
            environment: Optional environment string (defaults to inferred from subscription).
            workspace: Optional StagedWorkspace to directly add files to.

        Returns:
            List of generated StagedFile instances targeting azurerm_subnet/<subscription>/.

        Raises:
            ValueError: If subnet_name violates corporate naming conventions or address_prefixes is invalid.
        """
        # Validate subnet name against corporate naming conventions
        naming_rule = self.standards.bundle.get_naming_rule("azurerm_subnet")
        if naming_rule is not None:
            is_valid, err = naming_rule.validate_name(subnet_name)
            if not is_valid:
                raise ValueError(err or f"Invalid subnet name '{subnet_name}'")

        # Normalize address prefixes list
        if isinstance(address_prefixes, str):
            prefixes = [address_prefixes.strip()]
        else:
            prefixes = [p.strip() for p in address_prefixes if p and p.strip()]

        if not prefixes:
            prefixes = ["10.0.1.0/24"]

        # Validate CIDR notation strictly (no host bits allowed)
        for p in prefixes:
            try:
                ipaddress.ip_network(p, strict=True)
            except ValueError as exc:
                raise ValueError(f"Invalid subnet CIDR prefix '{p}': {exc}") from exc

        # Resolve isolated backend for azurerm_subnet
        backend_info = self.standards.resolve_backend(
            subscription=subscription,
            resource_type="azurerm_subnet",
        )

        backend_config: dict[str, Any] = {}
        if backend_info.get("resource_group_name"):
            backend_config["resource_group_name"] = backend_info["resource_group_name"]
        backend_config["storage_account_name"] = backend_info["storage_account_name"]
        backend_config["container_name"] = backend_info["container_name"]
        backend_config["key"] = backend_info["key"]

        backend_block = build_backend_block(backend_type="azurerm", **backend_config)
        backend_content = render_hcl_document([backend_block])

        # Synthesize data sources (Resource Group & Virtual Network)
        rg_name = backend_info.get("resource_group_name") or f"rg-{subscription}"
        target_vnet = vnet_name or f"vnet-{subscription}"

        data_rg_block = build_data_block(
            data_type="azurerm_resource_group",
            name="primary",
            attributes={"name": rg_name},
        )
        data_vnet_block = build_data_block(
            data_type="azurerm_virtual_network",
            name="primary",
            attributes={
                "name": target_vnet,
                "resource_group_name": HclReference("data.azurerm_resource_group.primary.name"),
            },
        )
        data_content = render_hcl_document([data_rg_block, data_vnet_block])

        # Synthesize main subnet resource block (azurerm_subnet does not take tags)
        attributes: dict[str, Any] = {
            "name": subnet_name,
            "resource_group_name": HclReference("data.azurerm_resource_group.primary.name"),
            "virtual_network_name": HclReference("data.azurerm_virtual_network.primary.name"),
            "address_prefixes": prefixes,
        }

        main_block = build_resource_block(
            resource_type="azurerm_subnet",
            name="primary",
            attributes=attributes,
        )
        main_content = render_hcl_document([main_block])

        folder = f"azurerm_subnet/{subscription}"
        main_file = StagedFile(
            path=f"{folder}/main.tf",
            content=main_content,
            is_new=True,
            metadata={"type": "subnet_resource", "subscription": subscription, "subnet_name": subnet_name},
        )
        data_file = StagedFile(
            path=f"{folder}/data.tf",
            content=data_content,
            is_new=True,
            metadata={"type": "subnet_data_sources", "subscription": subscription},
        )
        backend_file = StagedFile(
            path=f"{folder}/backend.tf",
            content=backend_content,
            is_new=True,
            metadata={"type": "subnet_backend", "subscription": subscription},
        )

        staged_files = [main_file, data_file, backend_file]

        if workspace is not None:
            for f in staged_files:
                workspace.add_file(f)

        return staged_files


