"""Protocol port interface for the offline AzureRM provider schema catalog."""

from typing import Any, Optional, Protocol, Union, runtime_checkable

from ttassistant.domain.catalog import CatalogSummary, ResourceSchema, ResourceTier


@runtime_checkable
class ResourceCatalogPort(Protocol):
    """Abstract port defining provider schema catalog queries, inspections, and validations."""

    def get_resource_schema(self, resource_type: str) -> Optional[ResourceSchema]:
        """Retrieve schema definition for an AzureRM resource type, or None if unknown.

        Args:
            resource_type: Azure resource type string (e.g. 'azurerm_storage_account').

        Returns:
            ResourceSchema if found in catalog, None otherwise.
        """
        ...

    def is_known_resource(self, resource_type: str) -> bool:
        """Check whether a resource type exists in the catalog.

        Args:
            resource_type: Azure resource type string.

        Returns:
            True if catalog contains the resource, False otherwise.
        """
        ...

    def is_tier_1(self, resource_type: str) -> bool:
        """Check whether a resource type is classified as Tier 1 (guided PaaS/foundation).

        Args:
            resource_type: Azure resource type string.

        Returns:
            True if classified as Tier 1, False otherwise.
        """
        ...

    def is_tier_2(self, resource_type: str) -> bool:
        """Check whether a resource type is classified as Tier 2 (universal long-tail).

        Args:
            resource_type: Azure resource type string.

        Returns:
            True if catalog contains the resource and is not Tier 1, False otherwise.
        """
        ...

    def list_resources(
        self,
        filter_prefix: Optional[str] = None,
        tier: Optional[Union[ResourceTier, int, str]] = None,
    ) -> list[str]:
        """List resource types matching optional filter prefix and classification tier.

        Args:
            filter_prefix: Optional prefix string to filter resource names (e.g. 'azurerm_mssql').
            tier: Optional tier filter (ResourceTier, int, or string).

        Returns:
            Sorted list of matching resource type strings.
        """
        ...

    def search(self, query: str) -> list[str]:
        """Search for resources where type name or description matches query substring.

        Args:
            query: Substring search term.

        Returns:
            Sorted list of matching resource type strings.
        """
        ...

    def get_required_arguments(self, resource_type: str) -> list[str]:
        """Retrieve required argument names for a resource type.

        Args:
            resource_type: Azure resource type string.

        Returns:
            List of required argument names, or empty list if resource unknown.
        """
        ...

    def get_optional_arguments(self, resource_type: str) -> list[str]:
        """Retrieve optional argument names for a resource type.

        Args:
            resource_type: Azure resource type string.

        Returns:
            List of optional argument names, or empty list if resource unknown.
        """
        ...

    def get_summary(self) -> CatalogSummary:
        """Retrieve aggregated summary statistics of the catalog.

        Returns:
            CatalogSummary instance.
        """
        ...
