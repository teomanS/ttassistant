"""Domain models and pure lexical indexing heuristics for repository topology (AD-1, AD-2)."""

from collections.abc import Iterable
import fnmatch
from pathlib import Path
import re
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# Target resource types for Phase 1 candidate discovery
DEFAULT_TARGET_RESOURCE_TYPES: frozenset[str] = frozenset({
    "azurerm_subnet",
    "azurerm_virtual_network",
    "azurerm_resource_group",
})

# Streaming pre-filter regex for candidate resource/data blocks
CANDIDATE_RESOURCE_REGEX = re.compile(
    r'(?:resource|data)\s+"(azurerm_subnet|azurerm_virtual_network|azurerm_resource_group)"'
)

# Common directory tokens representing resource types or non-subscription categories
RESOURCE_DIR_TOKENS: frozenset[str] = frozenset({
    "azurerm_resource_group",
    "azurerm_subnet",
    "azurerm_virtual_network",
    "azurerm_storage_account",
    "azurerm_private_endpoint",
    "resource-groups",
    "resource_groups",
    "resourcegroups",
    "resourcegroup",
    "virtual-networks",
    "virtual_networks",
    "virtualnetwork",
    "virtualnetworks",
    "rg",
    "rgs",
    "networking",
    "network",
    "networks",
    "vnet",
    "vnets",
    "subnet",
    "subnets",
    "storage",
    "keyvault",
    "compute",
    "database",
    "aks",
    "dns",
    "workloads",
    "workload",
    "services",
    "modules",
    "infra",
    "infrastructure",
    "terraform",
    "src",
})

SYSTEM_DIR_TOKENS: frozenset[str] = frozenset({
    "home",
    "users",
    "usr",
    "var",
    "tmp",
    "etc",
    "opt",
    "workspace",
    "workspaces",
    "repo",
    "repository",
    "root",
})


def infer_subscription(
    path: Path | str,
    content_hints: Optional[str] = None,
    root_dir: Optional[Path | str] = None,
) -> Optional[str]:
    """Pure heuristic function to infer target Azure subscription from path segments and content hints.

    Evaluation hierarchy:
    1. Inline content hints (e.g. subscription = "..." or subscription_id = "..."), ignoring comments
    2. Segment following 'subscriptions/' or 'subscription/' folder tokens
    3. Directory names matching explicit subscription naming patterns (sub-*, sub_*, *-sub, workload-*)
    4. Child directory under recognized resource type directories (<resource-type>/<subscription>/)
    5. Parent directory fallback (if not a generic resource type token or system root directory)
    """
    if content_hints:
        # Strip comment lines (# and //) before matching regex
        clean_hints = "\n".join(
            line for line in content_hints.splitlines()
            if not line.lstrip().startswith(("#", "//"))
        )
        # Check explicit subscription name first
        sub_name_match = re.search(r'(?<!\w)subscription\s*=\s*["\']([^"\']+)["\']', clean_hints)
        if sub_name_match:
            sub = sub_name_match.group(1).strip()
            if sub:
                return sub

        # Fallback to subscription_id
        sub_id_match = re.search(r'(?<!\w)subscription_id\s*=\s*["\']([^"\']+)["\']', clean_hints)
        if sub_id_match:
            sub = sub_id_match.group(1).strip()
            if sub:
                return sub

    p = Path(path)
    if root_dir is not None:
        try:
            p = p.resolve().relative_to(Path(root_dir).resolve())
        except ValueError:
            pass
    elif p.is_absolute():
        try:
            p = p.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            pass

    parts = [part for part in p.parts if part not in (".", "/", "\\")]
    if not parts:
        return None

    # Ignore filename if present
    if parts[-1].endswith((".tf", ".tf.json")):
        dirs = parts[:-1]
    else:
        dirs = parts

    if not dirs:
        return None

    # Pattern 1: Directory following subscriptions/ or subscription/
    for i, d in enumerate(dirs):
        if d.lower() in ("subscriptions", "subscription", "subs") and i + 1 < len(dirs):
            return dirs[i + 1]

    # Pattern 2: Explicit subscription naming tokens (searching deepest directory first)
    sub_pattern = re.compile(
        r'^(?:sub[-_]|workload[-_])[\w-]+$|^[\w-]+[-_](?:sub|subscription)$',
        re.IGNORECASE,
    )
    for d in reversed(dirs):
        if sub_pattern.match(d):
            return d

    # Pattern 3: <resource-type>/<subscription>/ convention
    for i, d in enumerate(dirs):
        if d.lower() in RESOURCE_DIR_TOKENS and i + 1 < len(dirs):
            candidate = dirs[i + 1]
            if candidate.lower() not in RESOURCE_DIR_TOKENS and candidate.lower() not in SYSTEM_DIR_TOKENS:
                return candidate

    # Pattern 4: Parent directory fallback if not in resource tokens or system tokens
    for d in reversed(dirs):
        if d.lower() not in RESOURCE_DIR_TOKENS and d.lower() not in SYSTEM_DIR_TOKENS:
            return d

    return None


def extract_candidate_types(
    content: str,
    target_types: Optional[frozenset[str] | set[str]] = None,
) -> set[str]:
    """Pure lexical extractor to identify candidate resource/data types in file content.

    Streams line-by-line, skipping full-line comments (# or //), and uses pre-filter
    keyword checks before applying regex for optimal execution performance.
    """
    targets = target_types if target_types is not None else DEFAULT_TARGET_RESOURCE_TYPES
    if not any(target in content for target in targets):
        return set()

    detected: set[str] = set()
    regex = CANDIDATE_RESOURCE_REGEX if targets == DEFAULT_TARGET_RESOURCE_TYPES else re.compile(
        rf'(?:resource|data)\s+"({"|".join(re.escape(t) for t in sorted(targets))})"'
    )

    for line in content.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        match = regex.search(line)
        if match:
            detected.add(match.group(1))

    return detected


class CandidateFile(BaseModel):
    """Domain representation of a discovered Terraform file containing candidate dependency blocks."""

    path: str = Field(..., description="Normalized relative or absolute file path")
    subscription: Optional[str] = Field(
        default=None,
        description="Inferred or explicitly mapped Azure subscription identifier",
    )
    detected_types: set[str] = Field(
        default_factory=set,
        description="Set of discovered AzureRM candidate block types (e.g. azurerm_subnet)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional discovery metadata or line matches",
    )

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, v: Any) -> str:
        """Ensure path is stored as a normalized POSIX string."""
        if v is None:
            raise ValueError("path cannot be None")
        s = str(v).replace("\\", "/")
        return Path(s).as_posix()

    @property
    def filename(self) -> str:
        """Extract filename from path."""
        return Path(self.path).name


class TopologyIndex(BaseModel):
    """In-memory index of discovered candidate files mapped to subscriptions across a monorepo."""

    candidates: list[CandidateFile] = Field(
        default_factory=list,
        description="List of discovered candidate files",
    )
    total_files_scanned: int = Field(
        default=0,
        description="Total number of .tf files traversed during discovery",
    )
    duration_seconds: float = Field(
        default=0.0,
        description="Execution duration for the repository traversal in seconds",
    )

    def add_candidate(self, candidate: CandidateFile) -> None:
        """Add a discovered candidate file to the index."""
        self.candidates.append(candidate)

    @property
    def candidate_count(self) -> int:
        """Return the number of candidate files indexed."""
        return len(self.candidates)

    @property
    def subscriptions(self) -> set[str]:
        """Return all distinct non-empty subscription identifiers indexed."""
        return {c.subscription for c in self.candidates if c.subscription}

    @property
    def by_subscription(self) -> dict[str, list[CandidateFile]]:
        """Group candidate files by their inferred subscription identifier."""
        grouped: dict[str, list[CandidateFile]] = {}
        for c in self.candidates:
            sub = c.subscription or "unassigned"
            grouped.setdefault(sub, []).append(c)
        return grouped

    def get_candidates_for_subscription(self, subscription: str) -> list[CandidateFile]:
        """Retrieve all candidate files associated with a specific subscription.

        If subscription is 'unassigned', returns candidates where subscription is None or 'unassigned'.
        """
        if subscription.lower() == "unassigned":
            return [c for c in self.candidates if not c.subscription or c.subscription.lower() == "unassigned"]
        return [c for c in self.candidates if c.subscription == subscription]

    def get_candidates_by_type(self, resource_type: str) -> list[CandidateFile]:
        """Retrieve all candidate files containing a specific resource or data block type."""
        return [c for c in self.candidates if resource_type in c.detected_types]

    def __len__(self) -> int:
        return len(self.candidates)

    def __iter__(self):
        return iter(self.candidates)

    def __getitem__(self, index: int) -> CandidateFile:
        return self.candidates[index]


# Common naming tokens designating private endpoint subnets (AD-2)
DEFAULT_PE_NAME_TOKENS: frozenset[str] = frozenset({
    "pe",
    "private",
    "privatelink",
    "paas",
})

# Subnet glob patterns for Private Endpoint classification
DEFAULT_PE_PATTERNS: tuple[str, ...] = (
    "*snet-paas*",
    "*private*",
    "*pe-*",
    "*-pe",
    "*-pe-*",
    "*snet-pe*",
    "*privatelink*",
    "*paas*",
)


class SubnetCandidate(BaseModel):
    """Domain model representing an extracted AzureRM Subnet declaration."""

    name: str = Field(..., description="Subnet name")
    address_prefixes: list[str] = Field(
        default_factory=list,
        description="CIDR address prefixes allocated to the subnet",
    )
    virtual_network_name: Optional[str] = Field(
        default=None,
        description="Parent Virtual Network name",
    )
    resource_group_name: Optional[str] = Field(
        default=None,
        description="Parent Resource Group name",
    )
    is_inline: bool = Field(
        default=False,
        description="Whether declared inline within an azurerm_virtual_network resource",
    )
    is_data_source: bool = Field(
        default=False,
        description="Whether extracted from a data source block rather than managed resource",
    )
    is_private_endpoint_candidate: bool = Field(
        default=False,
        description="Whether classified as candidate for hosting Private Endpoints",
    )
    private_endpoint_network_policies_enabled: Optional[bool] = Field(
        default=None,
        description="Raw boolean value of private_endpoint_network_policies_enabled attribute if set",
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Tags associated with the subnet",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="File path where this subnet was discovered",
    )
    subscription: Optional[str] = Field(
        default=None,
        description="Inferred or mapped subscription identifier",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional extraction metadata",
    )

    @field_validator("file_path", mode="before")
    @classmethod
    def normalize_file_path(cls, v: Any) -> Optional[str]:
        """Ensure file path is normalized POSIX string."""
        if v is None:
            return None
        return Path(str(v).replace("\\", "/")).as_posix()


class VirtualNetworkCandidate(BaseModel):
    """Domain model representing an extracted AzureRM Virtual Network declaration."""

    name: str = Field(..., description="Virtual Network name")
    resource_group_name: Optional[str] = Field(
        default=None,
        description="Parent Resource Group name",
    )
    location: Optional[str] = Field(
        default=None,
        description="Azure region / location",
    )
    address_space: list[str] = Field(
        default_factory=list,
        description="CIDR address space allocations",
    )
    subnets: list[SubnetCandidate] = Field(
        default_factory=list,
        description="Nested or associated Subnet candidates",
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Tags associated with the virtual network",
    )
    is_data_source: bool = Field(
        default=False,
        description="Whether extracted from a data source block",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="File path where this VNet was discovered",
    )
    subscription: Optional[str] = Field(
        default=None,
        description="Inferred or mapped subscription identifier",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional extraction metadata",
    )

    @field_validator("file_path", mode="before")
    @classmethod
    def normalize_file_path(cls, v: Any) -> Optional[str]:
        """Ensure file path is normalized POSIX string."""
        if v is None:
            return None
        return Path(str(v).replace("\\", "/")).as_posix()


class ResourceGroupCandidate(BaseModel):
    """Domain model representing an extracted AzureRM Resource Group declaration."""

    name: str = Field(..., description="Resource Group name")
    location: Optional[str] = Field(
        default=None,
        description="Azure region / location",
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Tags associated with the resource group",
    )
    is_data_source: bool = Field(
        default=False,
        description="Whether extracted from a data source block",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="File path where this Resource Group was discovered",
    )
    subscription: Optional[str] = Field(
        default=None,
        description="Inferred or mapped subscription identifier",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional extraction metadata",
    )

    @field_validator("file_path", mode="before")
    @classmethod
    def normalize_file_path(cls, v: Any) -> Optional[str]:
        """Ensure file path is normalized POSIX string."""
        if v is None:
            return None
        return Path(str(v).replace("\\", "/")).as_posix()


class DiscoveredTopology(BaseModel):
    """Aggregated domain model representing discovered infrastructure topology."""

    subnets: list[SubnetCandidate] = Field(
        default_factory=list,
        description="Discovered Subnet candidates (both standalone and inline)",
    )
    virtual_networks: list[VirtualNetworkCandidate] = Field(
        default_factory=list,
        description="Discovered Virtual Network candidates",
    )
    resource_groups: list[ResourceGroupCandidate] = Field(
        default_factory=list,
        description="Discovered Resource Group candidates",
    )
    parse_errors: list[str] = Field(
        default_factory=list,
        description="List of parse errors or warnings encountered during AST extraction",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )

    def get_subnets_for_subscription(self, subscription: str) -> list[SubnetCandidate]:
        """Filter subnets by target subscription."""
        if subscription.lower() == "unassigned":
            return [s for s in self.subnets if not s.subscription or s.subscription.lower() == "unassigned"]
        return [s for s in self.subnets if s.subscription == subscription]

    def get_private_endpoint_subnets(self, subscription: Optional[str] = None) -> list[SubnetCandidate]:
        """Filter subnets designated as Private Endpoint candidates."""
        candidates = self.subnets if subscription is None else self.get_subnets_for_subscription(subscription)
        return [s for s in candidates if s.is_private_endpoint_candidate]

    def get_resource_groups_for_subscription(self, subscription: str) -> list[ResourceGroupCandidate]:
        """Filter resource groups by target subscription."""
        if subscription.lower() == "unassigned":
            return [rg for rg in self.resource_groups if not rg.subscription or rg.subscription.lower() == "unassigned"]
        return [rg for rg in self.resource_groups if rg.subscription == subscription]

    def get_virtual_networks_for_subscription(self, subscription: str) -> list[VirtualNetworkCandidate]:
        """Filter virtual networks by target subscription."""
        if subscription.lower() == "unassigned":
            return [vn for vn in self.virtual_networks if not vn.subscription or vn.subscription.lower() == "unassigned"]
        return [vn for vn in self.virtual_networks if vn.subscription == subscription]

    def __len__(self) -> int:
        return len(self.subnets) + len(self.virtual_networks) + len(self.resource_groups)


def is_private_endpoint_subnet(
    subnet_or_name: SubnetCandidate | str,
    *,
    network_policies_enabled: Optional[bool] = None,
    tags: Optional[dict[str, str]] = None,
    standards_patterns: Optional[Iterable[str]] = None,
) -> bool:
    """Pure heuristic classifier to identify whether a subnet is designated for Private Endpoints.

    Multi-factor evaluation:
    1. Explicit attributes: private_endpoint_network_policies_enabled is True
    2. Standards globs: matching common_standards/networking_policy.md subnet patterns
    3. Naming tokens: name contains 'pe', 'private', 'privatelink', 'paas'
    4. Tag tokens: tag keys or values indicate private endpoint or paas usage
    """
    if isinstance(subnet_or_name, SubnetCandidate):
        name = subnet_or_name.name
        if network_policies_enabled is None:
            network_policies_enabled = subnet_or_name.private_endpoint_network_policies_enabled
        if tags is None:
            tags = subnet_or_name.tags
    else:
        name = str(subnet_or_name)

    # 1. Attribute heuristic
    if network_policies_enabled is True:
        return True

    name_lower = name.lower()

    # 2. Standards pattern globs
    patterns = list(standards_patterns) if standards_patterns is not None else list(DEFAULT_PE_PATTERNS)
    for pattern in patterns:
        if pattern and fnmatch.fnmatch(name_lower, pattern.lower()):
            return True

    # 3. Naming tokens (pe, private, privatelink, paas)
    tokens = {t for t in re.split(r'[^a-z0-9]+', name_lower) if t}
    if any(tok in DEFAULT_PE_NAME_TOKENS for tok in tokens):
        return True
    for tok in DEFAULT_PE_NAME_TOKENS:
        if tok in ("privatelink", "private", "paas") and tok in name_lower:
            return True
        if tok == "pe" and (
            re.search(r'(^|[-_])pe([-_0-9]|$)', name_lower)
            or name_lower == "pe"
            or name_lower.startswith("pe-")
            or name_lower.endswith("-pe")
        ):
            return True

    # 4. Tag tokens
    if tags:
        for k, v in tags.items():
            k_lower = str(k).lower()
            v_lower = str(v).lower()
            k_tokens = set(re.split(r'[^a-z0-9]+', k_lower))
            v_tokens = set(re.split(r'[^a-z0-9]+', v_lower))
            all_tokens = k_tokens | v_tokens
            if any(tok in DEFAULT_PE_NAME_TOKENS for tok in all_tokens):
                return True
            for tok in ("privatelink", "private", "paas", "private_endpoint"):
                if tok in k_lower or tok in v_lower:
                    return True

    return False

