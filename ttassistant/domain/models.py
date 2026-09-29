import fnmatch
from pathlib import Path
import re
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from ttassistant.domain.exceptions import StandardsError


class NamingRule(BaseModel):
    """Naming convention rule for an Azure resource type."""

    resource_type: str = Field(..., description="Azure resource type (e.g. azurerm_resource_group)")
    pattern: str = Field(..., description="Regex pattern the resource name must match")
    allowed_characters: str = Field(default="", description="Human-readable description of allowed characters")
    max_length: int = Field(..., description="Maximum allowed length for the resource name")
    min_length: int = Field(default=1, description="Minimum allowed length for the resource name")

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate that pattern is a valid regular expression."""
        if not v or not v.strip():
            raise ValueError("Naming pattern cannot be empty")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression pattern '{v}': {exc}") from exc
        return v

    @field_validator("max_length")
    @classmethod
    def validate_max_length(cls, v: int) -> int:
        """Validate max_length is positive."""
        if v <= 0:
            raise ValueError(f"max_length must be greater than 0, got {v}")
        return v

    @model_validator(mode="after")
    def validate_lengths(self) -> "NamingRule":
        """Validate min_length is valid relative to max_length."""
        if self.min_length <= 0:
            raise ValueError(f"min_length must be greater than 0, got {self.min_length}")
        if self.min_length > self.max_length:
            raise ValueError(
                f"min_length ({self.min_length}) cannot be greater than max_length ({self.max_length})"
            )
        return self

    def validate_name(self, name: str) -> tuple[bool, Optional[str]]:
        """Validate a resource name against this rule.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if len(name) > self.max_length:
            return (
                False,
                f"Resource name '{name}' exceeds maximum length of {self.max_length} characters (actual: {len(name)})",
            )
        if len(name) < self.min_length:
            return (
                False,
                f"Resource name '{name}' is shorter than minimum length of {self.min_length} characters (actual: {len(name)})",
            )
        if not re.fullmatch(self.pattern, name):
            desc = f" (Allowed: {self.allowed_characters})" if self.allowed_characters else ""
            return (
                False,
                f"Resource name '{name}' does not match naming pattern '{self.pattern}'{desc}",
            )
        return True, None


class TagRule(BaseModel):
    """Tagging standard rule for Azure resources."""

    key: str = Field(..., description="Tag key name (e.g. Environment, Owner)")
    required: bool = Field(default=True, description="Whether this tag is mandatory")
    allowed_values: list[str] = Field(default_factory=list, description="Allowed values for the tag, empty if any allowed")
    default_value: Optional[str] = Field(default=None, description="Default value if not provided")
    description: Optional[str] = Field(default=None, description="Explanation of tag purpose")

    def validate_tag(self, value: Optional[str]) -> tuple[bool, Optional[str]]:
        """Validate a tag value against this rule.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            if self.required:
                return False, f"Missing mandatory tag: '{self.key}'"
            return True, None

        if self.allowed_values and value not in self.allowed_values:
            allowed_str = ", ".join(self.allowed_values)
            return (
                False,
                f"Tag '{self.key}' value '{value}' is not allowed. Allowed values: [{allowed_str}]",
            )
        return True, None


class BackendMappingRule(BaseModel):
    """Azure Blob remote state backend mapping rule for a subscription."""

    subscription: str = Field(..., description="Subscription identifier, name, or wildcard (*)")
    storage_account_name: str = Field(..., description="Azure storage account for remote state")
    container_name: str = Field(default="tfstate", description="Blob container name")
    key_pattern: str = Field(
        default="{subscription}/{resource_type}.tfstate",
        description="Template for remote state blob key",
    )
    resource_group_name: Optional[str] = Field(
        default=None,
        description="Resource group containing the storage account",
    )

    def resolve_key(self, resource_type: str, subscription: Optional[str] = None, **kwargs: Any) -> str:
        """Format the state key template with subscription and resource_type values."""
        sub = subscription or self.subscription
        try:
            return self.key_pattern.format(
                subscription=sub,
                resource_type=resource_type,
                **kwargs,
            )
        except (KeyError, ValueError, IndexError) as exc:
            raise StandardsError(
                f"Invalid key_pattern template '{self.key_pattern}': {exc}",
                details=f"Failed resolving backend key for subscription='{sub}', resource_type='{resource_type}'.",
            ) from exc


class NetworkingPolicyRule(BaseModel):
    """Enterprise security triad networking and Private DNS policy."""

    resource_type: str = Field(..., description="Azure PaaS resource type or 'default'")
    private_dns_zone_id: Optional[str] = Field(default=None, description="Resource ID of Hub Private DNS Zone")
    private_dns_zone_name: Optional[str] = Field(default=None, description="FQDN of Private DNS Zone")
    subnet_patterns: list[str] = Field(
        default_factory=list,
        description="Candidate subnet naming patterns (e.g. ['*snet-paas*', '*private*'])",
    )
    allow_public_access: bool = Field(default=False, description="Whether public network access is permitted")

    @property
    def hub_resource_group(self) -> Optional[str]:
        """Extract Hub Resource Group name from private_dns_zone_id if present."""
        if self.private_dns_zone_id:
            m = re.search(r"/resource[Gg]roups/([^/]+)(?:/|$)", self.private_dns_zone_id, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    @property
    def hub_subscription_id(self) -> Optional[str]:
        """Extract Hub Subscription ID from private_dns_zone_id if present."""
        if self.private_dns_zone_id:
            m = re.search(r"/subscriptions/([^/]+)(?:/|$)", self.private_dns_zone_id, re.IGNORECASE)
            if m:
                return m.group(1)
        return None


class StandardsBundle(BaseModel):
    """Aggregated corporate standards loaded from common_standards/."""

    naming_rules: dict[str, NamingRule] = Field(default_factory=dict)
    tag_rules: dict[str, TagRule] = Field(default_factory=dict)
    backend_rules: list[BackendMappingRule] = Field(default_factory=list)
    networking_rules: dict[str, NetworkingPolicyRule] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_naming_rule(self, resource_type: str) -> Optional[NamingRule]:
        """Look up naming rule for a specific resource type."""
        return self.naming_rules.get(resource_type)

    def get_tag_rule(self, key: str) -> Optional[TagRule]:
        """Look up tag rule by key name (case-insensitive fallback)."""
        if key in self.tag_rules:
            return self.tag_rules[key]
        for k, rule in self.tag_rules.items():
            if k.lower() == key.lower():
                return rule
        return None

    def get_backend_rule(self, subscription: str) -> Optional[BackendMappingRule]:
        """Find matching backend mapping rule for subscription, falling back to glob patterns or wildcard."""
        for rule in self.backend_rules:
            if rule.subscription == subscription:
                return rule
        for rule in self.backend_rules:
            if rule.subscription not in ("default", "*") and fnmatch.fnmatch(subscription, rule.subscription):
                return rule
        for rule in self.backend_rules:
            if rule.subscription in ("default", "*"):
                return rule
        return None

    def get_networking_rule(self, resource_type: str) -> Optional[NetworkingPolicyRule]:
        """Find networking policy rule for resource type, falling back to 'default' or '*'."""
        if resource_type in self.networking_rules:
            return self.networking_rules[resource_type]
        for fallback_key in ("default", "*"):
            if fallback_key in self.networking_rules:
                return self.networking_rules[fallback_key]
        return None


class ProvisioningParameters(BaseModel):
    """Parameters collected during the guided provisioning dialogue."""

    subscription: str = Field(..., description="Target Azure subscription identifier")
    resource_type: str = Field(..., description="Azure resource type (e.g. azurerm_storage_account)")
    workload_name: str = Field(..., description="Workload or application component name")
    environment: str = Field(..., description="Target deployment environment (e.g. dev, prod)")
    resource_name: str = Field(..., description="Computed corporate standards compliant resource name")
    tags: dict[str, str] = Field(default_factory=dict, description="Corporate compliant resource tags")
    public_network_access: bool = Field(
        default=False,
        description="Whether public network access is enabled for the resource",
    )
    selected_subnet: Optional[str] = Field(default=None, description="Selected or scaffolded subnet name")
    network_action: Optional[str] = Field(
        default=None,
        description="Network action taken: 'existing', 'scaffold', or 'cross_subscription'",
    )
    cross_sub_source: Optional[str] = Field(
        default=None,
        description="Source subscription for cross-subscription shared network lookup",
    )
    selected_vnet: Optional[str] = Field(
        default=None,
        description="Parent virtual network name for the selected subnet",
    )
    selected_subnet_rg: Optional[str] = Field(
        default=None,
        description="Resource group containing the selected virtual network and subnet",
    )

    @field_validator("selected_subnet", mode="before")
    @classmethod
    def validate_selected_subnet(cls, v: Optional[str]) -> Optional[str]:
        """Strip whitespace from selected_subnet if provided."""
        if v is not None:
            stripped = v.strip()
            return stripped if stripped else None
        return None

    @field_validator("subscription", "resource_type", "workload_name", "environment", "resource_name")
    @classmethod
    def validate_not_empty(cls, v: str, info) -> str:
        """Validate string fields are not empty."""
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} cannot be empty")
        return v.strip()


class StagedFile(BaseModel):
    """An in-memory staged file representing generated Terraform code."""

    path: str = Field(..., description="File path relative to target directory or workspace")
    content: str = Field(..., description="In-memory text content of the staged file")
    is_new: bool = Field(default=True, description="Whether this is a newly created file")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary file metadata")

    @property
    def line_count(self) -> int:
        """Count the number of lines in the file content."""
        if not self.content:
            return 0
        return len(self.content.splitlines())

    @property
    def filename(self) -> str:
        """Extract the filename component from the path."""
        return Path(self.path).name


class StagedWorkspace(BaseModel):
    """An in-memory workspace containing staged Terraform files targeting a directory."""

    target_dir: str = Field(
        ...,
        description="Target relative directory for the workspace, e.g. azurerm_storage_account/sub-prod/",
    )
    files: dict[str, StagedFile] = Field(
        default_factory=dict,
        description="Map of file path to StagedFile",
    )
    parameters: Optional[ProvisioningParameters] = Field(
        default=None,
        description="ProvisioningParameters used to generate this staged workspace",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary workspace metadata",
    )

    def add_file(self, staged_file: StagedFile) -> None:
        """Add or update a staged file in the workspace, keyed by staged_file.path."""
        self.files[staged_file.path] = staged_file

    def get_file(self, name: str) -> Optional[StagedFile]:
        """Retrieve a staged file by path, filename, or suffix."""
        if name in self.files:
            return self.files[name]
        for f in self.files.values():
            if f.path == name or f.filename == name:
                return f
        for f in self.files.values():
            if f.path.endswith(f"/{name}"):
                return f
        return None

    @property
    def total_lines(self) -> int:
        """Total line count across all staged files."""
        return sum(f.line_count for f in self.files.values())

    @property
    def file_count(self) -> int:
        """Total number of files in the workspace."""
        return len(self.files)

    def __getitem__(self, name: str) -> StagedFile:
        file = self.get_file(name)
        if file is None:
            raise KeyError(f"Staged file '{name}' not found in workspace.")
        return file

    def __contains__(self, name: str) -> bool:
        return self.get_file(name) is not None

    def __iter__(self):
        return iter(self.files.values())

    def __len__(self) -> int:
        return len(self.files)


