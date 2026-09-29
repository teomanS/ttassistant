"""Domain models and audit rules for existing workspace compliance inspection (AD-1, AD-7)."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, computed_field

from ttassistant.domain.catalog import is_tier_1_paas


class ComplianceSeverity(str, Enum):
    """Severity classification for compliance violations."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ComplianceViolationType(str, Enum):
    """Categorization of compliance audit findings."""

    PUBLIC_NETWORK_ACCESS_ENABLED = "public_network_access_enabled"
    MISSING_PUBLIC_NETWORK_ACCESS_DENIAL = "missing_public_network_access_denial"
    MISSING_TAG = "missing_tag"
    INVALID_TAG_VALUE = "invalid_tag_value"
    MISSING_PRIVATE_ENDPOINT = "missing_private_endpoint"
    MISSING_DNS_ZONE_GROUP = "missing_dns_zone_group"
    INVALID_RESOURCE_NAME = "invalid_resource_name"
    PARSE_WARNING = "parse_warning"


class ComplianceViolation(BaseModel):
    """Structured record of a single compliance rule violation."""

    violation_type: ComplianceViolationType = Field(..., description="Category of violation")
    severity: ComplianceSeverity = Field(..., description="Severity level")
    resource_type: str = Field(..., description="Azure resource type (e.g. azurerm_storage_account)")
    resource_name: str = Field(..., description="Terraform resource name/identifier")
    file_path: str = Field(..., description="Relative or absolute path of file containing the resource")
    message: str = Field(..., description="Human-readable violation description")
    attribute_name: Optional[str] = Field(default=None, description="Name of offending or missing attribute")
    expected_value: Optional[Any] = Field(default=None, description="Expected compliant value")
    actual_value: Optional[Any] = Field(default=None, description="Actual observed value in HCL")
    remediation_hint: str = Field(..., description="Actionable recommendation to resolve the violation")


class ParsedResource(BaseModel):
    """Extracted representation of a declared Terraform resource block."""

    resource_type: str = Field(..., description="Azure resource type")
    resource_name: str = Field(..., description="Terraform block label/name")
    file_path: str = Field(..., description="Source file path")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Top-level resource attributes")
    tags: dict[str, str] = Field(default_factory=dict, description="Resource tags dictionary")
    nested_blocks: dict[str, Any] = Field(default_factory=dict, description="Nested blocks (e.g. private_dns_zone_group)")


class ComplianceReport(BaseModel):
    """Aggregate diagnostic report of workspace compliance inspection."""

    target_dir: str = Field(..., description="Target directory path inspected")
    subscription: Optional[str] = Field(default=None, description="Inferred or detected Azure subscription")
    inspected_files: list[str] = Field(default_factory=list, description="List of .tf files inspected")
    detected_resources: list[str] = Field(default_factory=list, description="Resource identifiers discovered")
    resources: list[ParsedResource] = Field(default_factory=list, description="Parsed resource objects in workspace")
    violations: list[ComplianceViolation] = Field(default_factory=list, description="List of detected violations")
    parse_warnings: list[str] = Field(default_factory=list, description="Non-fatal HCL parsing warnings")

    @computed_field
    @property
    def is_compliant(self) -> bool:
        """Return True if 0 compliance violations were detected."""
        return len(self.violations) == 0

    @computed_field
    @property
    def critical_count(self) -> int:
        """Count of CRITICAL severity violations."""
        return sum(1 for v in self.violations if v.severity == ComplianceSeverity.CRITICAL)

    @computed_field
    @property
    def high_count(self) -> int:
        """Count of HIGH severity violations."""
        return sum(1 for v in self.violations if v.severity == ComplianceSeverity.HIGH)

    @computed_field
    @property
    def medium_count(self) -> int:
        """Count of MEDIUM severity violations."""
        return sum(1 for v in self.violations if v.severity == ComplianceSeverity.MEDIUM)

    @computed_field
    @property
    def low_count(self) -> int:
        """Count of LOW severity violations."""
        return sum(1 for v in self.violations if v.severity == ComplianceSeverity.LOW)


def audit_resource_tags(
    resource: ParsedResource,
    required_tags: list[str],
    standards_defaults: Optional[dict[str, str]] = None,
) -> list[ComplianceViolation]:
    """Audit a resource block against required corporate tags.

    Args:
        resource: Parsed resource block.
        required_tags: List of mandatory tag keys from tagging_baseline.md.
        standards_defaults: Optional default values from standards for remediation hints.

    Returns:
        List of ComplianceViolation objects for missing or invalid tags.
    """
    violations: list[ComplianceViolation] = []
    defaults = standards_defaults or {}

    # Case-insensitive lookup map for observed tags
    observed_tags_lower = {k.lower(): (k, v) for k, v in resource.tags.items()}

    for req_tag in required_tags:
        req_lower = req_tag.lower()
        if req_lower not in observed_tags_lower:
            default_val = defaults.get(req_tag, "...")
            violations.append(
                ComplianceViolation(
                    violation_type=ComplianceViolationType.MISSING_TAG,
                    severity=ComplianceSeverity.HIGH,
                    resource_type=resource.resource_type,
                    resource_name=resource.resource_name,
                    file_path=resource.file_path,
                    message=f"Missing mandatory tag '{req_tag}'.",
                    attribute_name=f"tags.{req_tag}",
                    expected_value=default_val if default_val != "..." else "<compliant_value>",
                    actual_value=None,
                    remediation_hint=f'Add \'{req_tag} = "{default_val}"\' to tags = {{ ... }} in {resource.file_path}',
                )
            )
        else:
            orig_k, val = observed_tags_lower[req_lower]
            if not isinstance(val, str) or not val.strip():
                default_val = defaults.get(req_tag, "...")
                violations.append(
                    ComplianceViolation(
                        violation_type=ComplianceViolationType.INVALID_TAG_VALUE,
                        severity=ComplianceSeverity.HIGH,
                        resource_type=resource.resource_type,
                        resource_name=resource.resource_name,
                        file_path=resource.file_path,
                        message=f"Mandatory tag '{req_tag}' has empty or whitespace value.",
                        attribute_name=f"tags.{orig_k}",
                        expected_value=default_val if default_val != "..." else "<non_empty_value>",
                        actual_value=val,
                        remediation_hint=f'Set \'{orig_k} = "{default_val}"\' in {resource.file_path}',
                    )
                )

    return violations


def _pe_targets_resource(pe: ParsedResource, resource: ParsedResource) -> bool:
    """Determine if an azurerm_private_endpoint targets a specific resource."""
    target_tokens = {
        resource.resource_name,
        f"{resource.resource_type}.{resource.resource_name}",
    }

    # Check top-level attributes
    for attr_name in ("private_connection_resource_id", "target_resource_id"):
        val = str(pe.attributes.get(attr_name, ""))
        if any(token in val for token in target_tokens):
            return True

    # Check nested blocks (e.g. private_service_connection)
    psc = pe.nested_blocks.get("private_service_connection")
    if isinstance(psc, dict):
        val = str(psc.get("private_connection_resource_id", ""))
        if any(token in val for token in target_tokens):
            return True
    elif isinstance(psc, list):
        for item in psc:
            if isinstance(item, dict):
                val = str(item.get("private_connection_resource_id", ""))
                if any(token in val for token in target_tokens):
                    return True

    # Heuristic fallback: PE name contains resource name
    if resource.resource_name in pe.resource_name:
        return True

    return False


def audit_paas_security_triad(
    primary_resource: ParsedResource,
    all_resources: list[ParsedResource],
) -> list[ComplianceViolation]:
    """Audit a Tier 1 PaaS resource against Enterprise Security Triad policies.

    Enforces mandatory public network access denial (AD-7, FR-12) and companion
    private endpoint with Hub Private DNS zone group.

    Args:
        primary_resource: The primary PaaS resource under audit.
        all_resources: All resources declared in the workspace directory.

    Returns:
        List of ComplianceViolation objects for security policy breaches.
    """
    violations: list[ComplianceViolation] = []

    if not is_tier_1_paas(primary_resource.resource_type):
        return violations

    # 1. Mandatory Public Network Access Denial (AD-7, FR-12)
    pna_val = primary_resource.attributes.get("public_network_access_enabled")

    # Explicit denial is strictly required: boolean False or string 'false'/'0'/'no'/'disabled'
    is_explicitly_denied = (pna_val is False) or (
        isinstance(pna_val, str) and pna_val.strip().lower() in ("false", "0", "no", "disabled")
    )

    if not is_explicitly_denied:
        if pna_val is None:
            violations.append(
                ComplianceViolation(
                    violation_type=ComplianceViolationType.MISSING_PUBLIC_NETWORK_ACCESS_DENIAL,
                    severity=ComplianceSeverity.CRITICAL,
                    resource_type=primary_resource.resource_type,
                    resource_name=primary_resource.resource_name,
                    file_path=primary_resource.file_path,
                    message=(
                        f"Tier 1 PaaS resource '{primary_resource.resource_type}.{primary_resource.resource_name}' "
                        f"omits mandatory public network access denial attribute. "
                        f"PaaS resources must explicitly set public_network_access_enabled = false."
                    ),
                    attribute_name="public_network_access_enabled",
                    expected_value=False,
                    actual_value=None,
                    remediation_hint=f"Add 'public_network_access_enabled = false' to {primary_resource.file_path} to deny public internet exposure.",
                )
            )
        else:
            violations.append(
                ComplianceViolation(
                    violation_type=ComplianceViolationType.PUBLIC_NETWORK_ACCESS_ENABLED,
                    severity=ComplianceSeverity.CRITICAL,
                    resource_type=primary_resource.resource_type,
                    resource_name=primary_resource.resource_name,
                    file_path=primary_resource.file_path,
                    message=(
                        f"Tier 1 PaaS resource '{primary_resource.resource_type}.{primary_resource.resource_name}' "
                        f"does not deny public network access (observed: {pna_val!r}). "
                        f"Violates corporate security policy AD-7 & FR-12."
                    ),
                    attribute_name="public_network_access_enabled",
                    expected_value=False,
                    actual_value=pna_val,
                    remediation_hint=f"Set 'public_network_access_enabled = false' in {primary_resource.file_path} to enforce private network access.",
                )
            )

    # 2. Companion Private Endpoint Verification
    all_pes = [r for r in all_resources if r.resource_type == "azurerm_private_endpoint"]
    all_paas = [r for r in all_resources if is_tier_1_paas(r.resource_type)]

    matching_pes = [pe for pe in all_pes if _pe_targets_resource(pe, primary_resource)]
    # Fallback: if only 1 PaaS resource and 1 PE exists in directory, pair them
    if not matching_pes and len(all_paas) == 1 and len(all_pes) == 1:
        matching_pes = all_pes

    if not matching_pes:
        violations.append(
            ComplianceViolation(
                violation_type=ComplianceViolationType.MISSING_PRIVATE_ENDPOINT,
                severity=ComplianceSeverity.HIGH,
                resource_type=primary_resource.resource_type,
                resource_name=primary_resource.resource_name,
                file_path=primary_resource.file_path,
                message=(
                    f"Tier 1 PaaS resource '{primary_resource.resource_type}.{primary_resource.resource_name}' "
                    f"lacks a companion 'azurerm_private_endpoint' resource targeting it in the workspace."
                ),
                attribute_name="azurerm_private_endpoint",
                expected_value="azurerm_private_endpoint",
                actual_value=None,
                remediation_hint=(
                    f"Scaffold companion 'azurerm_private_endpoint' resource in {primary_resource.file_path} referencing "
                    f"{primary_resource.resource_type}.{primary_resource.resource_name}.id and target subnet."
                ),
            )
        )
    else:
        # Check that matching private endpoints have private_dns_zone_group
        for pe in matching_pes:
            has_dns = ("private_dns_zone_group" in pe.nested_blocks) or ("private_dns_zone_group" in pe.attributes)
            if not has_dns:
                violations.append(
                    ComplianceViolation(
                        violation_type=ComplianceViolationType.MISSING_DNS_ZONE_GROUP,
                        severity=ComplianceSeverity.MEDIUM,
                        resource_type=pe.resource_type,
                        resource_name=pe.resource_name,
                        file_path=pe.file_path,
                        message=(
                            f"Private endpoint '{pe.resource_type}.{pe.resource_name}' targeting "
                            f"'{primary_resource.resource_name}' lacks a 'private_dns_zone_group' block linked to Hub Private DNS."
                        ),
                        attribute_name="private_dns_zone_group",
                        expected_value="private_dns_zone_group { ... }",
                        actual_value=None,
                        remediation_hint=(
                            f"Add 'private_dns_zone_group' block in {pe.file_path} referencing the corporate Hub Private DNS zone data source."
                        ),
                    )
                )

    return violations

