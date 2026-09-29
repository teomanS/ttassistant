"""Domain models and logic for the AzureRM provider schema catalog."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# Canonical Tier 1 resources governed by AD-3 and AD-7:
# Guided Enterprise PaaS and core foundation services requiring
# full guided prompts, candidate subnet discovery, and Enterprise Security Triad bundling.
TIER_1_RESOURCES: frozenset[str] = frozenset({
    "azurerm_storage_account",
    "azurerm_key_vault",
    "azurerm_mssql_server",
    "azurerm_cosmosdb_account",
    "azurerm_eventhub_namespace",
    "azurerm_postgresql_flexible_server",
    "azurerm_mysql_flexible_server",
    "azurerm_redis_cache",
    "azurerm_linux_web_app",
    "azurerm_virtual_network",
    "azurerm_subnet",
    "azurerm_resource_group",
})

# Tier 1 PaaS resources requiring Enterprise Security Triad guardrails (FR-12, FR-13, AD-7)
TIER_1_PAAS_RESOURCES: frozenset[str] = frozenset({
    "azurerm_storage_account",
    "azurerm_key_vault",
    "azurerm_mssql_server",
    "azurerm_cosmosdb_account",
    "azurerm_eventhub_namespace",
    "azurerm_postgresql_flexible_server",
    "azurerm_mysql_flexible_server",
    "azurerm_redis_cache",
    "azurerm_linux_web_app",
})

# Non-PaaS core foundation resources (do not configure public_network_access_enabled)
TIER_1_FOUNDATION_RESOURCES: frozenset[str] = frozenset({
    "azurerm_virtual_network",
    "azurerm_subnet",
    "azurerm_resource_group",
})

# Canonical Tier 2 universal Azure long-tail resources defined in azurerm_schema.json
TIER_2_RESOURCES: frozenset[str] = frozenset({
    "azurerm_cognitive_account",
    "azurerm_log_analytics_workspace",
    "azurerm_mssql_database",
    "azurerm_servicebus_namespace",
    "azurerm_container_registry",
    "azurerm_kubernetes_cluster",
    "azurerm_application_insights",
    "azurerm_api_management",
    "azurerm_search_service",
    "azurerm_dns_zone",
    "azurerm_private_dns_zone",
    "azurerm_private_endpoint",
    "azurerm_network_security_group",
    "azurerm_network_interface",
    "azurerm_public_ip",
    "azurerm_bastion_host",
    "azurerm_firewall",
    "azurerm_user_assigned_identity",
    "azurerm_service_plan",
    "azurerm_container_app",
    "azurerm_container_app_environment",
})


def is_tier_1_resource(resource_type: str) -> bool:
    """Check whether a resource type is classified as Tier 1."""
    if not resource_type:
        return False
    return resource_type.strip().lower() in TIER_1_RESOURCES


def is_tier_2_resource(resource_type: str) -> bool:
    """Check whether a resource type is classified as Tier 2."""
    if not resource_type:
        return False
    return resource_type.strip().lower() in TIER_2_RESOURCES


def is_tier_1_paas(resource_type: str) -> bool:
    """Check whether a resource type is classified as a Tier 1 Enterprise PaaS resource."""
    if not resource_type:
        return False
    return resource_type.strip().lower() in TIER_1_PAAS_RESOURCES


# Canonical subresource names for Tier 1 PaaS services (FR-13, AD-7)
PAAS_SUBRESOURCE_NAMES: dict[str, list[str]] = {
    "azurerm_storage_account": ["blob"],
    "azurerm_key_vault": ["vault"],
    "azurerm_mssql_server": ["sqlServer"],
    "azurerm_cosmosdb_account": ["Sql"],
    "azurerm_eventhub_namespace": ["namespace"],
    "azurerm_postgresql_flexible_server": ["postgresqlServer"],
    "azurerm_mysql_flexible_server": ["mysqlServer"],
    "azurerm_redis_cache": ["redisCache"],
    "azurerm_linux_web_app": ["sites"],
}

# Canonical default Hub Private DNS Zone names for Tier 1 PaaS services (FR-13, AD-7)
PAAS_DEFAULT_DNS_ZONES: dict[str, str] = {
    "azurerm_storage_account": "privatelink.blob.core.windows.net",
    "azurerm_key_vault": "privatelink.vaultcore.azure.net",
    "azurerm_mssql_server": "privatelink.database.windows.net",
    "azurerm_cosmosdb_account": "privatelink.documents.azure.com",
    "azurerm_eventhub_namespace": "privatelink.servicebus.windows.net",
    "azurerm_postgresql_flexible_server": "privatelink.postgres.database.azure.com",
    "azurerm_mysql_flexible_server": "privatelink.mysql.database.azure.com",
    "azurerm_redis_cache": "privatelink.redis.cache.windows.net",
    "azurerm_linux_web_app": "privatelink.azurewebsites.net",
}


def get_paas_subresource_names(resource_type: str) -> list[str]:
    """Retrieve canonical subresource names for an Azure PaaS service."""
    if not resource_type:
        return []
    normalized = resource_type.strip().lower()
    return list(PAAS_SUBRESOURCE_NAMES.get(normalized, []))


def get_paas_default_dns_zone(resource_type: str) -> Optional[str]:
    """Retrieve canonical default Hub Private DNS Zone name for an Azure PaaS service."""
    if not resource_type:
        return None
    normalized = resource_type.strip().lower()
    return PAAS_DEFAULT_DNS_ZONES.get(normalized)


# Expose alias for direct domain check
is_tier_1 = is_tier_1_resource
is_tier_2 = is_tier_2_resource


class ResourceTier(str, Enum):
    """Classification tier for Azure resources."""

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            value = str(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("1", "tier1", "tier_1", "t1"):
                return cls.TIER_1
            if normalized in ("2", "tier2", "tier_2", "t2"):
                return cls.TIER_2
        return None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int) and not isinstance(other, bool):
            return (self is ResourceTier.TIER_1 and other == 1) or (self is ResourceTier.TIER_2 and other == 2)
        if isinstance(other, str):
            try:
                resolved = ResourceTier(other)
                return self is resolved
            except (ValueError, TypeError):
                return super().__eq__(other)
        return super().__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()

    @property
    def display_name(self) -> str:
        """Formatted human-readable tier label."""
        if self is ResourceTier.TIER_1:
            return "Tier 1 (Guided PaaS & Foundation)"
        return "Tier 2 (Universal Long-Tail)"


class ResourceArgumentSchema(BaseModel):
    """Schema metadata for an individual resource argument."""

    name: str = Field(..., description="Argument attribute name (e.g. account_tier)")
    type: str = Field(default="string", description="HCL data type (string, bool, number, list, map, object)")
    description: str = Field(default="", description="Descriptive explanation of the argument")
    required: bool = Field(default=False, description="Whether this argument is required by provider schema")
    optional: bool = Field(default=True, description="Whether this argument is optional")
    computed: bool = Field(default=False, description="Whether this argument is computed by the provider")
    default: Optional[Any] = Field(default=None, description="Default value if specified")
    sensitive: bool = Field(default=False, description="Whether the argument contains sensitive credentials")
    forces_new: bool = Field(default=False, description="Whether changing this argument forces resource replacement")


class ArgumentName(str):
    """String representing argument name with .name attribute parity."""

    @property
    def name(self) -> str:
        return str(self)


class ArgumentLookupList(list):
    """List of argument names that also supports key lookup, containment, and dict-like inspection."""

    def __init__(self, names: list[str], args_map: dict[str, ResourceArgumentSchema]) -> None:
        super().__init__([ArgumentName(n) for n in names])
        self._args_map = args_map

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            return self._args_map[item]
        return super().__getitem__(item)

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, str):
            return item in self._args_map
        return super().__contains__(item)

    def get(self, key: str, default: Any = None) -> Any:
        return self._args_map.get(key, default)

    def keys(self):
        return self._args_map.keys()

    def values(self):
        return self._args_map.values()

    def items(self):
        return self._args_map.items()


class ResourceSchema(BaseModel):
    """Complete schema definition for an AzureRM resource."""

    resource_type: str = Field(..., description="Canonical AzureRM resource type, e.g. azurerm_storage_account")
    tier: ResourceTier = Field(default=ResourceTier.TIER_2, description="Resource classification tier")
    description: str = Field(default="", description="High-level description of the resource")
    arguments: dict[str, ResourceArgumentSchema] = Field(
        default_factory=dict,
        description="Map of argument names to argument schemas",
    )

    @property
    def is_tier_1(self) -> bool:
        """Whether this resource is classified as Tier 1."""
        return self.tier == ResourceTier.TIER_1

    @property
    def is_tier_2(self) -> bool:
        """Whether this resource is classified as Tier 2."""
        return self.tier == ResourceTier.TIER_2

    @property
    def required_arguments(self) -> ArgumentLookupList:
        """List of required argument names supporting dict-like lookup and items iteration."""
        req_names = [name for name, arg in self.arguments.items() if arg.required]
        req_map = {name: arg for name, arg in self.arguments.items() if arg.required}
        return ArgumentLookupList(req_names, req_map)

    @property
    def optional_arguments(self) -> ArgumentLookupList:
        """List of optional argument names supporting dict-like lookup and items iteration."""
        opt_names = [name for name, arg in self.arguments.items() if not arg.required]
        opt_map = {name: arg for name, arg in self.arguments.items() if not arg.required}
        return ArgumentLookupList(opt_names, opt_map)

    @property
    def required_argument_names(self) -> list[str]:
        """List of required argument name strings."""
        return [name for name, arg in self.arguments.items() if arg.required]

    @property
    def optional_argument_names(self) -> list[str]:
        """List of optional argument name strings."""
        return [name for name, arg in self.arguments.items() if not arg.required]

    def get_argument(self, name: str) -> Optional[ResourceArgumentSchema]:
        """Look up an argument schema by name."""
        return self.arguments.get(name)

    def validate_arguments(self, args: Optional[dict[str, Any]]) -> tuple[bool, list[str]]:
        """Check that all required arguments are present in the provided dictionary.

        Returns:
            Tuple of (is_valid, list_of_missing_argument_names).
        """
        if args is None:
            return (len(self.required_arguments) == 0, [a.name for a in self.required_arguments])
        missing = [name for name, arg in self.arguments.items() if arg.required and name not in args]
        return (len(missing) == 0, missing)


class CatalogSummary(BaseModel):
    """Summary statistics for the loaded provider schema catalog."""

    total_resources: int = Field(default=0, description="Total number of cataloged resources")
    tier_1_count: int = Field(default=0, description="Count of Tier 1 guided PaaS and foundation resources")
    tier_2_count: int = Field(default=0, description="Count of Tier 2 universal long-tail resources")
    provider_version: Optional[str] = Field(default=None, description="AzureRM provider version")
    resource_types: list[str] = Field(default_factory=list, description="Alphabetical list of resource type names")
