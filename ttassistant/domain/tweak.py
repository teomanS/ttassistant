"""Pure-domain AzureRM Attribute Alias Dictionary and comment-preserving HCL mutator (AD-1, AD-4)."""

import re
from typing import Any, Optional

from ttassistant.domain.exceptions import TweakParseError
from ttassistant.domain.hcl import HclReference, escape_hcl_string, is_valid_hcl_identifier


# General colloquial aliases mapping terms to target AzureRM attribute names
GLOBAL_ATTRIBUTE_ALIASES: dict[str, str] = {
    # TLS configuration
    "tls": "min_tls_version",
    "tls_version": "min_tls_version",
    "min_tls": "min_tls_version",
    "min_tls_version": "min_tls_version",
    "minimum_tls_version": "minimum_tls_version",
    "minimum tls version": "min_tls_version",
    "min tls version": "min_tls_version",
    "min tls": "min_tls_version",
    "tls version": "min_tls_version",
    # Replication
    "replication": "account_replication_type",
    "replication_type": "account_replication_type",
    "account_replication_type": "account_replication_type",
    "account replication type": "account_replication_type",
    "account replication": "account_replication_type",
    "repl": "account_replication_type",
    # Tier
    "tier": "account_tier",
    "account_tier": "account_tier",
    "account tier": "account_tier",
    "storage_tier": "account_tier",
    "storage tier": "account_tier",
    # SKU
    "sku": "sku_name",
    "sku_name": "sku_name",
    "sku name": "sku_name",
    "tier_sku": "sku",
    # Public network access
    "public_access": "public_network_access_enabled",
    "public access": "public_network_access_enabled",
    "public_network_access": "public_network_access_enabled",
    "public network access": "public_network_access_enabled",
    "public_network_access_enabled": "public_network_access_enabled",
    "public network": "public_network_access_enabled",
    # Access tier
    "access_tier": "access_tier",
    "access tier": "access_tier",
    # Kind
    "kind": "account_kind",
    "account_kind": "account_kind",
    "account kind": "account_kind",
    # Hierarchical Namespace (ADLS Gen2)
    "hns": "is_hns_enabled",
    "is_hns_enabled": "is_hns_enabled",
    "hierarchical_namespace": "is_hns_enabled",
    "hierarchical namespace": "is_hns_enabled",
    "datalake": "is_hns_enabled",
    # Key Vault security attributes
    "purge_protection": "purge_protection_enabled",
    "purge_protection_enabled": "purge_protection_enabled",
    "purge protection": "purge_protection_enabled",
    "soft_delete": "soft_delete_retention_days",
    "soft_delete_retention_days": "soft_delete_retention_days",
    "soft delete retention days": "soft_delete_retention_days",
    "soft delete": "soft_delete_retention_days",
    "retention_days": "soft_delete_retention_days",
    "rbac_authorization": "enable_rbac_authorization",
    "enable_rbac_authorization": "enable_rbac_authorization",
    "rbac": "enable_rbac_authorization",
    # Container Registry
    "admin_enabled": "admin_enabled",
    "admin": "admin_enabled",
    # Service Plan / App Service
    "os_type": "os_type",
    "os": "os_type",
    # Database / Server version
    "version": "version",
    "server_version": "version",
}

# Resource-specific overrides where the AzureRM provider uses distinct attribute names
RESOURCE_SPECIFIC_ALIASES: dict[str, dict[str, str]] = {
    "azurerm_storage_account": {
        "tls": "min_tls_version",
        "tls_version": "min_tls_version",
        "minimum_tls_version": "min_tls_version",
        "minimum tls version": "min_tls_version",
        "min_tls_version": "min_tls_version",
        "min tls": "min_tls_version",
        "sku": "account_tier",
        "kind": "account_kind",
    },
    "azurerm_mssql_server": {
        "tls": "minimum_tls_version",
        "tls_version": "minimum_tls_version",
        "min_tls_version": "minimum_tls_version",
        "minimum_tls_version": "minimum_tls_version",
        "minimum tls version": "minimum_tls_version",
        "min tls": "minimum_tls_version",
    },
    "azurerm_redis_cache": {
        "tls": "minimum_tls_version",
        "tls_version": "minimum_tls_version",
        "min_tls_version": "minimum_tls_version",
        "minimum_tls_version": "minimum_tls_version",
        "minimum tls version": "minimum_tls_version",
    },
    "azurerm_container_registry": {
        "sku": "sku",
        "sku_name": "sku",
        "sku name": "sku",
    },
    "azurerm_search_service": {
        "sku": "sku",
        "sku_name": "sku",
        "sku name": "sku",
    },
    "azurerm_servicebus_namespace": {
        "sku": "sku",
        "sku_name": "sku",
        "sku name": "sku",
    },
    "azurerm_cognitive_account": {
        "kind": "kind",
    },
}

# Sets of valid enum values for common attributes
VALID_REPLICATIONS = {"LRS", "GRS", "RAGRS", "ZRS", "GZRS", "RAGZRS"}
VALID_TIERS = {"Standard", "Premium"}
VALID_ACCESS_TIERS = {"Hot", "Cool"}


def resolve_attribute_alias(raw_term: str, resource_type: Optional[str] = None) -> str:
    """Resolve a colloquial term or direct attribute name to canonical AzureRM attribute name.

    Args:
        raw_term: User-provided term (e.g. 'replication', 'minimum TLS version', 'sku').
        resource_type: Target resource type for contextual disambiguation.

    Returns:
        Canonical attribute name (e.g. 'account_replication_type', 'min_tls_version').

    Raises:
        TweakParseError: If term is empty or completely unresolvable.
    """
    clean = raw_term.strip().lower()
    clean = re.sub(r"[\s_-]+", " ", clean)

    norm_key = clean.replace(" ", "_")

    # 1. Check resource-specific overrides
    if resource_type:
        rt_norm = resource_type.strip().lower()
        if rt_norm in RESOURCE_SPECIFIC_ALIASES:
            res_map = RESOURCE_SPECIFIC_ALIASES[rt_norm]
            if clean in res_map:
                return res_map[clean]
            if norm_key in res_map:
                return res_map[norm_key]

    # 2. Check global alias map
    if clean in GLOBAL_ATTRIBUTE_ALIASES:
        return GLOBAL_ATTRIBUTE_ALIASES[clean]
    if norm_key in GLOBAL_ATTRIBUTE_ALIASES:
        return GLOBAL_ATTRIBUTE_ALIASES[norm_key]

    # 3. Direct identifier pass-through if valid snake_case
    if is_valid_hcl_identifier(norm_key):
        return norm_key

    raise TweakParseError(
        f"Unable to resolve tweak term '{raw_term}' to a recognized AzureRM resource attribute."
    )


def normalize_attribute_value(
    attribute_name: str,
    raw_val: Any,
    resource_type: Optional[str] = None,
) -> Any:
    """Normalize and type an attribute value based on AzureRM provider conventions.

    Args:
        attribute_name: Canonical attribute name.
        raw_val: Raw value parsed from instruction.
        resource_type: Target resource type for contextual typing.

    Returns:
        Normalized value (bool, int, str, etc.).
    """
    if raw_val is None:
        return None

    # Handle boolean conversion
    if isinstance(raw_val, bool):
        return raw_val

    val_str = str(raw_val).strip()

    # Strip surrounding quotes if present
    if (val_str.startswith('"') and val_str.endswith('"')) or (
        val_str.startswith("'") and val_str.endswith("'")
    ):
        val_str = val_str[1:-1].strip()

    val_lower = val_str.lower()

    # Boolean normalization
    if attribute_name.endswith("_enabled") or attribute_name.startswith("enable_") or attribute_name == "public_network_access":
        if val_lower in ("true", "yes", "enable", "enabled", "on", "1"):
            return True
        if val_lower in ("false", "no", "disable", "disabled", "off", "0"):
            return False

    # TLS version normalization
    if attribute_name in ("min_tls_version", "minimum_tls_version"):
        # Storage accounts use "TLS1_2", "TLS1_0", "TLS1_1"
        is_storage = resource_type and "storage" in resource_type.lower()
        if is_storage or attribute_name == "min_tls_version":
            if val_lower in ("1.2", "1_2", "tls1.2", "tls1_2"):
                return "TLS1_2"
            if val_lower in ("1.1", "1_1", "tls1.1", "tls1_1"):
                return "TLS1_1"
            if val_lower in ("1.0", "1_0", "tls1.0", "tls1_0"):
                return "TLS1_0"
            return val_str.upper()
        else:
            # SQL, Redis typically use "1.2", "1.0", etc.
            if val_lower in ("tls1_2", "tls1.2", "1_2"):
                return "1.2"
            if val_lower in ("tls1_1", "tls1.1", "1_1"):
                return "1.1"
            if val_lower in ("tls1_0", "tls1.0", "1_0"):
                return "1.0"
            return val_str

    # Replication normalization
    if attribute_name == "account_replication_type":
        upper_rep = val_str.upper()
        if upper_rep in VALID_REPLICATIONS:
            return upper_rep
        return val_str

    # Tier normalization
    if attribute_name == "account_tier":
        for t in VALID_TIERS:
            if val_lower == t.lower():
                return t
        return val_str.capitalize()

    # Access tier normalization
    if attribute_name == "access_tier":
        for at in VALID_ACCESS_TIERS:
            if val_lower == at.lower():
                return at
        return val_str.capitalize()

    # Integer retention days
    if attribute_name == "soft_delete_retention_days":
        try:
            return int(val_str)
        except ValueError:
            return val_str

    return val_str


def _format_hcl_attr_val(val: Any) -> str:
    """Format scalar attribute value for insertion into HCL."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, HclReference):
        return str(val)
    return f'"{escape_hcl_string(str(val))}"'


def _find_resource_block_spans(hcl_content: str, resource_type: Optional[str] = None) -> Optional[tuple[int, int, str]]:
    """Locate start index, end index, and resource block type of primary resource in HCL text."""
    if resource_type:
        pattern = re.compile(
            rf'(resource\s+"{re.escape(resource_type)}"\s+"[^"]+"\s*\{{)',
            re.MULTILINE,
        )
    else:
        pattern = re.compile(r'(resource\s+"[^"]+"\s+"[^"]+"\s*\{)', re.MULTILINE)

    match = pattern.search(hcl_content)
    if not match:
        return None

    start_idx = match.start()
    header = match.group(1)

    # Find matching closing brace
    brace_count = 0
    in_quote = False
    quote_char = ""
    i = match.end() - 1  # points to the '{'

    while i < len(hcl_content):
        c = hcl_content[i]
        if in_quote:
            if c == quote_char and hcl_content[i - 1] != "\\":
                in_quote = False
        else:
            if c in ('"', "'"):
                in_quote = True
                quote_char = c
            elif c == "{":
                brace_count += 1
            elif c == "}":
                brace_count -= 1
                if brace_count == 0:
                    return (start_idx, i + 1, header)
        i += 1

    return None


def mutate_hcl_attribute(
    hcl_content: str,
    attribute_name: str,
    new_value: Any,
    resource_type: Optional[str] = None,
) -> tuple[str, bool, Optional[Any]]:
    """Non-destructively mutate or insert an attribute in the primary HCL resource block.

    Preserves 100% of surrounding comments, formatting, and other resource blocks.

    Args:
        hcl_content: Raw HCL text.
        attribute_name: Canonical attribute name.
        new_value: New Python value to apply.
        resource_type: Optional resource type to locate specific resource block.

    Returns:
        Tuple of (modified_hcl_content, was_modified, old_value).
    """
    span = _find_resource_block_spans(hcl_content, resource_type=resource_type)
    if not span:
        return (hcl_content, False, None)

    block_start, block_end, _ = span
    block_text = hcl_content[block_start:block_end]

    formatted_val = _format_hcl_attr_val(new_value)

    # 1. Search for existing attribute in this block
    # Pattern: ^([ \t]*){attribute_name}(\s*=\s*)(.*?)([\r\n]|$)
    attr_pattern = re.compile(
        rf"^([ \t]*){re.escape(attribute_name)}(\s*=\s*)([^\r\n#]*)(.*)$",
        re.MULTILINE,
    )

    match = attr_pattern.search(block_text)
    if match:
        indent = match.group(1)
        equals = match.group(2)
        old_val_raw = match.group(3).strip().strip('"')
        trailing = match.group(4)  # Preserve inline comments like # comment

        new_line = f"{indent}{attribute_name}{equals}{formatted_val}{trailing}"
        updated_block = block_text[: match.start()] + new_line + block_text[match.end() :]
        updated_content = hcl_content[:block_start] + updated_block + hcl_content[block_end:]
        return (updated_content, True, old_val_raw)

    # 2. Attribute does not exist in block: insert cleanly
    # Prefer inserting before "tags = {" or before the closing brace "}"
    lines = block_text.splitlines(keepends=True)
    insert_idx = len(lines) - 1  # Default right before last line ("}")

    for idx, line in enumerate(lines):
        if re.search(r"^[ \t]*tags\s*=\s*\{", line):
            insert_idx = idx
            break

    # Determine standard indentation from surrounding lines
    indent = "  "
    new_line = f"{indent}{attribute_name} = {formatted_val}\n"

    # Add spacing if inserting right before tags
    if insert_idx < len(lines) - 1 and re.search(r"^[ \t]*tags\s*=\s*\{", lines[insert_idx]):
        lines.insert(insert_idx, new_line)
    else:
        # Check if previous line has newline
        lines.insert(insert_idx, new_line)

    updated_block = "".join(lines)
    updated_content = hcl_content[:block_start] + updated_block + hcl_content[block_end:]
    return (updated_content, True, None)


def mutate_hcl_tag(
    hcl_content: str,
    tag_key: str,
    tag_value: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> tuple[str, bool, Optional[str]]:
    """Non-destructively add, update, or remove a tag within tags = { ... } in the HCL resource block.

    Args:
        hcl_content: Raw HCL text.
        tag_key: Tag key name (e.g. 'Environment', 'team').
        tag_value: Tag value string, or None if removing the tag.
        resource_type: Optional resource type to locate specific resource block.

    Returns:
        Tuple of (modified_hcl_content, was_modified, old_tag_value).
    """
    span = _find_resource_block_spans(hcl_content, resource_type=resource_type)
    if not span:
        return (hcl_content, False, None)

    block_start, block_end, _ = span
    block_text = hcl_content[block_start:block_end]

    # Look for tags = { ... } inside the resource block
    tags_match = re.search(r"([ \t]*tags\s*=\s*\{)([\s\S]*?)(\n[ \t]*\})", block_text)

    tag_fmt_key = tag_key if is_valid_hcl_identifier(tag_key) else f'"{escape_hcl_string(tag_key)}"'

    if tags_match:
        tags_open = tags_match.group(1)
        tags_body = tags_match.group(2)
        tags_close = tags_match.group(3)

        # Search for tag_key inside tags_body
        tag_line_pattern = re.compile(
            rf"^([ \t]*)(?:{re.escape(tag_key)}|\"{re.escape(tag_key)}\")(\s*=\s*)([^\r\n#]*)(.*)$",
            re.MULTILINE,
        )

        match = tag_line_pattern.search(tags_body)

        if tag_value is not None:
            # Add or update tag
            formatted_val = f'"{escape_hcl_string(tag_value)}"'
            if match:
                # Update existing tag
                indent = match.group(1)
                equals = match.group(2)
                old_val = match.group(3).strip().strip('"')
                trailing = match.group(4)
                new_line = f"{indent}{tag_fmt_key}{equals}{formatted_val}{trailing}"
                updated_body = tags_body[: match.start()] + new_line + tags_body[match.end() :]
            else:
                # Append new tag inside tags
                indent = "    "
                new_line = f"{indent}{tag_fmt_key} = {formatted_val}\n"
                if tags_body.strip():
                    if not tags_body.endswith("\n"):
                        tags_body += "\n"
                    updated_body = tags_body + new_line
                else:
                    updated_body = "\n" + new_line
                old_val = None
        else:
            # Remove tag
            if match:
                old_val = match.group(3).strip().strip('"')
                # Delete the line
                start_l = match.start()
                end_l = match.end()
                if end_l < len(tags_body) and tags_body[end_l] == "\n":
                    end_l += 1
                updated_body = tags_body[:start_l] + tags_body[end_l:]
            else:
                # Tag is already absent - idempotent no-op
                return (hcl_content, True, None)

        updated_tags_block = f"{tags_open}{updated_body}{tags_close}"
        updated_resource_block = (
            block_text[: tags_match.start()] + updated_tags_block + block_text[tags_match.end() :]
        )
        updated_content = (
            hcl_content[:block_start] + updated_resource_block + hcl_content[block_end:]
        )
        return (updated_content, True, old_val)

    else:
        # tags block does not exist yet: create it if tag_value is provided
        if tag_value is None:
            # Tag is already absent - idempotent no-op
            return (hcl_content, True, None)

        formatted_val = f'"{escape_hcl_string(tag_value)}"'
        new_tags_block = f"\n  tags = {{\n    {tag_fmt_key} = {formatted_val}\n  }}\n"

        lines = block_text.splitlines(keepends=True)
        insert_idx = len(lines) - 1
        lines.insert(insert_idx, new_tags_block)

        updated_resource_block = "".join(lines)
        updated_content = (
            hcl_content[:block_start] + updated_resource_block + hcl_content[block_end:]
        )
        return (updated_content, True, None)
