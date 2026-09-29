"""Pure business logic domain service for enterprise standards enforcement."""

import re
from typing import Any, Optional

from ttassistant.domain.catalog import get_paas_default_dns_zone
from ttassistant.domain.exceptions import StandardsError
from ttassistant.domain.models import (
    BackendMappingRule,
    NamingRule,
    NetworkingPolicyRule,
    StandardsBundle,
    TagRule,
)


DEFAULT_RESOURCE_PREFIXES: dict[str, tuple[str, str]] = {
    "azurerm_log_analytics_workspace": ("law-", "-"),
    "azurerm_application_insights": ("appi-", "-"),
    "azurerm_network_security_group": ("nsg-", "-"),
    "azurerm_public_ip": ("pip-", "-"),
    "azurerm_container_registry": ("cr", ""),
    "azurerm_kubernetes_cluster": ("aks-", "-"),
    "azurerm_api_management": ("apim-", "-"),
    "azurerm_firewall": ("afw-", "-"),
    "azurerm_user_assigned_identity": ("id-", "-"),
    "azurerm_bastion_host": ("bas-", "-"),
    "azurerm_dns_zone": ("dns-", "-"),
    "azurerm_service_plan": ("asp-", "-"),
    "azurerm_servicebus_namespace": ("sb-", "-"),
    "azurerm_cognitive_account": ("cog-", "-"),
    "azurerm_container_app": ("ca-", "-"),
    "azurerm_container_app_environment": ("cae-", "-"),
    "azurerm_mssql_database": ("sqldb-", "-"),
    "azurerm_network_interface": ("nic-", "-"),
    "azurerm_private_dns_zone": ("pdns-", "-"),
    "azurerm_search_service": ("srch-", "-"),
}


class StandardsEngine:
    """Pure domain service executing enterprise standards validation and policy resolution."""

    def __init__(self, standards: StandardsBundle) -> None:
        """Initialize with an in-memory standards bundle.

        Args:
            standards: Aggregated StandardsBundle domain object.
        """
        self._standards = standards

    @property
    def bundle(self) -> StandardsBundle:
        """Access the underlying standards bundle."""
        return self._standards

    def validate_resource_name(
        self, resource_type: str, name: str
    ) -> tuple[bool, Optional[str]]:
        """Validate a resource name against naming standards for the given resource type.

        Args:
            resource_type: Azure resource type (e.g. 'azurerm_storage_account').
            name: Proposed resource name.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        rule = self._standards.get_naming_rule(resource_type)
        if rule is None:
            # If no rule is defined for this resource type, accept as valid
            return True, None
        return rule.validate_name(name)

    def validate_tags(self, tags: dict[str, str]) -> tuple[bool, list[str]]:
        """Validate a dictionary of resource tags against corporate tagging baseline.

        Checks:
        1. All mandatory tags are present and non-empty.
        2. Provided tags match allowed values when restricted (optional empty tags permitted).

        Args:
            tags: Dictionary of tag key-value pairs.

        Returns:
            Tuple of (is_valid, list_of_error_messages). If valid, list is empty.
        """
        errors: list[str] = []

        for rule in self._standards.tag_rules.values():
            matching_val: Optional[str] = None
            for k, v in tags.items():
                if k.lower() == rule.key.lower():
                    matching_val = v
                    break
            is_valid, err = rule.validate_tag(matching_val)
            if not is_valid and err:
                errors.append(err)

        return len(errors) == 0, errors

    def apply_default_tags(
        self, existing_tags: Optional[dict[str, str]] = None
    ) -> dict[str, str]:
        """Generate a tag dictionary incorporating default values from tagging baseline.

        Args:
            existing_tags: Optional existing or user-provided tags that take precedence.

        Returns:
            Merged dictionary containing default tags overlaid with existing tags.
        """
        existing = existing_tags or {}
        existing_lower = {k.lower() for k in existing.keys()}

        result: dict[str, str] = {}
        for rule in self._standards.tag_rules.values():
            if rule.default_value is not None:
                if rule.key.lower() not in existing_lower:
                    result[rule.key] = rule.default_value

        result.update(existing)
        return result

    def resolve_backend(
        self, subscription: str, resource_type: str = ""
    ) -> dict[str, str]:
        """Resolve Azure Blob remote state backend configuration for a subscription and resource.

        Args:
            subscription: Target subscription identifier or environment.
            resource_type: Azure resource type being scaffolded.

        Returns:
            Dictionary with backend configuration keys:
            - storage_account_name
            - container_name
            - key
            - resource_group_name

        Raises:
            StandardsError: If no matching backend mapping rule is found.
        """
        rule = self._standards.get_backend_rule(subscription)
        if rule is None:
            raise StandardsError(
                f"No remote state backend mapping found for subscription '{subscription}'.",
                details="Please configure a mapping rule in 'backend_mapping.md' for this subscription or add a wildcard '*' entry.",
            )

        resolved_key = rule.resolve_key(
            resource_type=resource_type,
            subscription=subscription,
        )

        return {
            "storage_account_name": rule.storage_account_name,
            "container_name": rule.container_name,
            "key": resolved_key,
            "resource_group_name": rule.resource_group_name or "",
        }

    def resolve_networking_policy(
        self, resource_type: str
    ) -> Optional[NetworkingPolicyRule]:
        """Resolve networking policy and Hub Private DNS configuration for a resource type.

        Args:
            resource_type: Azure PaaS resource type.

        Returns:
            Matching NetworkingPolicyRule or None if no policy matches.
        """
        rule = self._standards.get_networking_rule(resource_type)
        default_dns = get_paas_default_dns_zone(resource_type)
        if rule is not None:
            if not rule.private_dns_zone_name:
                zone_from_id = (
                    rule.private_dns_zone_id.rstrip("/").split("/")[-1]
                    if rule.private_dns_zone_id
                    else None
                )
                if rule.resource_type == resource_type:
                    zone_to_use = zone_from_id or default_dns
                else:
                    zone_to_use = default_dns or zone_from_id

                if zone_to_use:
                    return rule.model_copy(update={"private_dns_zone_name": zone_to_use})
            return rule
        if default_dns:
            return NetworkingPolicyRule(
                resource_type=resource_type,
                private_dns_zone_name=default_dns,
            )
        return None

    def resolve_hub_dns_zone(self, resource_type: str) -> dict[str, str]:
        """Resolve Hub Private DNS Zone coordinates (name and resource_group_name).

        Resolves zone coordinates from corporate networking_policy.md (if defined)
        or falls back to canonical Microsoft Azure private DNS defaults.

        Args:
            resource_type: Azure PaaS resource type.

        Returns:
            Dictionary with 'name' and 'resource_group_name'.
        """
        policy = self.resolve_networking_policy(resource_type)

        # 1. Resolve Zone Name
        zone_name = ""
        if policy and policy.private_dns_zone_name:
            zone_name = policy.private_dns_zone_name
        elif policy and policy.private_dns_zone_id:
            zone_name = policy.private_dns_zone_id.rstrip("/").split("/")[-1]
        elif default_dns := get_paas_default_dns_zone(resource_type):
            zone_name = default_dns

        # 2. Resolve Hub Resource Group
        hub_rg = policy.hub_resource_group if policy else None

        # Check the 'default' rule first before searching other rules
        if not hub_rg:
            default_rule = self._standards.networking_rules.get("default")
            if default_rule and default_rule.hub_resource_group:
                hub_rg = default_rule.hub_resource_group

        # Deterministically check remaining networking rules with a zone ID
        if not hub_rg:
            for k in sorted(self._standards.networking_rules.keys()):
                r = self._standards.networking_rules[k]
                if r.hub_resource_group:
                    hub_rg = r.hub_resource_group
                    break

        # Fallback to corporate standard default Hub DNS resource group
        if not hub_rg:
            hub_rg = "rg-hub-dns"

        return {
            "name": zone_name,
            "resource_group_name": hub_rg,
        }

    def compute_resource_name(
        self, resource_type: str, workload_name: str, environment: str = ""
    ) -> str:
        """Compute corporate standards compliant resource name.

        Args:
            resource_type: Azure resource type (e.g. 'azurerm_storage_account').
            workload_name: Base workload identifier (e.g. 'appdata').
            environment: Optional environment identifier (e.g. 'prod', 'dev').

        Returns:
            Computed compliant resource name (e.g. 'stappdataprod', 'rg-appdata-prod').
        """
        rule = self._standards.get_naming_rule(resource_type)
        clean_workload = workload_name.strip()
        clean_env = environment.strip().lower()

        prefix = ""
        separator = "-"
        if rule is not None:
            if rule.pattern:
                m = re.match(r"^\^?([a-z0-9]+-?)", rule.pattern)
                if m:
                    raw_prefix = m.group(1)
                    if raw_prefix.endswith("-"):
                        prefix = raw_prefix
                        separator = "-"
                    else:
                        prefix = raw_prefix
                        separator = ""
        elif resource_type in DEFAULT_RESOURCE_PREFIXES:
            prefix, separator = DEFAULT_RESOURCE_PREFIXES[resource_type]
        else:
            if clean_env:
                return f"{clean_workload}-{clean_env}"
            return clean_workload

        # Check for explicit separator matching environment suffix in clean_workload
        core_workload = clean_workload
        if clean_env:
            for explicit_sep in ("-", "_"):
                suffix = f"{explicit_sep}{clean_env}"
                if core_workload.endswith(suffix):
                    core_workload = core_workload[: -len(suffix)]
                    break

        # Check if workload already starts with prefix
        if prefix:
            if prefix.endswith("-") and core_workload.startswith(prefix):
                core_workload = core_workload[len(prefix):]
            elif not prefix.endswith("-"):
                if core_workload.startswith(f"{prefix}-"):
                    core_workload = core_workload[len(prefix) + 1:]
                elif core_workload.startswith(prefix) and len(core_workload) > len(prefix):
                    candidate = core_workload[len(prefix):]
                    if not candidate.startswith("-"):
                        core_workload = candidate

        if not clean_env:
            return f"{prefix}{core_workload}"

        if separator == "":
            clean_env_val = clean_env.replace("-", "").replace("_", "")
            return f"{prefix}{core_workload}{clean_env_val}"
        else:
            return f"{prefix}{core_workload}-{clean_env}"

    def infer_environment(self, subscription: str) -> str:
        """Infer environment identifier from subscription name based on tagging baseline."""
        tag_rule = self._standards.get_tag_rule("Environment")
        allowed = [v.lower() for v in (tag_rule.allowed_values if tag_rule else [])]
        if not allowed:
            allowed = ["dev", "test", "stage", "prod"]
        default_env = tag_rule.default_value if (tag_rule and tag_rule.default_value) else "dev"

        tokens = [t.lower() for t in re.split(r"[-_.]", subscription)]
        for token in tokens:
            if token in allowed:
                return token
        return default_env

