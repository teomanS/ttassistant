"""Pure domain service for comment-preserving surgical HCL text patching (AD-2, AD-5)."""

import re
from typing import Optional

from ttassistant.domain.catalog import (
    get_paas_default_dns_zone,
    get_paas_subresource_names,
)


def _strip_strings_and_comments(line: str) -> str:
    """Strip string literals and single-line comments for reliable brace counting."""
    # Strip double quoted strings
    no_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    # Strip inline block comments
    no_block = re.sub(r'/\*.*?\*/', '', no_strings)
    # Strip single-line comments (# and //)
    no_comments = re.sub(r'(?:#|//).*$', '', no_block)
    return no_comments


def find_resource_block_lines(
    lines: list[str],
    resource_type: str,
    resource_name: str,
) -> Optional[tuple[int, int]]:
    """Locate the starting and ending line indices of a resource block.

    Accurately tracks braces, string literals, and multi-line comments.

    Args:
        lines: File lines.
        resource_type: Azure resource type (e.g. azurerm_storage_account).
        resource_name: Terraform block label (e.g. main).

    Returns:
        Tuple of (start_idx, end_idx) 0-indexed inclusive, or None if not found.
    """
    pattern = re.compile(
        rf'^\s*resource\s+["\']?{re.escape(resource_type)}["\']?\s+["\']?{re.escape(resource_name)}["\']?\s*\{{'
    )

    start_idx: Optional[int] = None
    brace_depth = 0
    in_block_comment = False

    for idx, line in enumerate(lines):
        cleaned_line = line
        if in_block_comment:
            if "*/" in cleaned_line:
                cleaned_line = cleaned_line.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue

        while "/*" in cleaned_line:
            before, after = cleaned_line.split("/*", 1)
            if "*/" in after:
                after = after.split("*/", 1)[1]
                cleaned_line = before + after
            else:
                cleaned_line = before
                in_block_comment = True
                break

        if start_idx is None:
            if pattern.search(cleaned_line):
                start_idx = idx
                cleaned = _strip_strings_and_comments(cleaned_line)
                brace_depth += cleaned.count("{") - cleaned.count("}")
                if brace_depth == 0:
                    return (start_idx, idx)
        else:
            cleaned = _strip_strings_and_comments(cleaned_line)
            brace_depth += cleaned.count("{") - cleaned.count("}")
            if brace_depth <= 0:
                return (start_idx, idx)

    return None


def _expand_single_line_resource(
    lines: list[str],
    start_idx: int,
) -> tuple[list[str], int, int]:
    """Expand a single-line resource declaration into a multi-line block."""
    line = lines[start_idx]
    m = re.match(r"^(\s*resource\s+[^{]+\{)\s*(.*?)\s*\}(.*)$", line)
    if not m:
        return lines, start_idx, start_idx

    prefix = m.group(1)
    body = m.group(2).strip()
    suffix = m.group(3).strip()
    suffix_comment = f" {suffix}" if suffix else ""
    line_ending = "\r\n" if line.endswith("\r\n") else "\n"

    expanded_lines = [f"{prefix}{suffix_comment}{line_ending}"]
    if body:
        expanded_lines.append(f"  {body}{line_ending}")
    expanded_lines.append(f"}}{line_ending}")

    new_lines = lines[:start_idx] + expanded_lines + lines[start_idx + 1:]
    new_end_idx = start_idx + len(expanded_lines) - 1
    return new_lines, start_idx, new_end_idx


def patch_public_network_access(
    content: str,
    resource_type: str,
    resource_name: str,
    enabled: bool = False,
) -> str:
    """Surgically enforce public_network_access_enabled on a resource block.

    If the attribute already exists, updates its value in-place, preserving exact
    indentation and any trailing comments. If missing, inserts the attribute with
    proper block indentation. All existing comments and formatting are 100% preserved.

    Args:
        content: Original HCL file text.
        resource_type: Azure resource type.
        resource_name: Terraform block label.
        enabled: Boolean value to set (defaults to False for compliance).

    Returns:
        Surgically updated HCL file content.
    """
    lines = content.splitlines(keepends=True)
    block_span = find_resource_block_lines(lines, resource_type, resource_name)
    if block_span is None:
        return content

    start_idx, end_idx = block_span

    # Handle single-line resource declaration
    if start_idx == end_idx:
        lines, start_idx, end_idx = _expand_single_line_resource(lines, start_idx)

    target_val_str = str(enabled).lower()

    # 1. Search for existing public_network_access_enabled within block
    pna_pattern = re.compile(r"^(\s*)public_network_access_enabled\s*=\s*(.*?)(?:\s*(#.*|//.*|/\*.*))?$")
    for idx in range(start_idx, end_idx + 1):
        m = pna_pattern.match(lines[idx])
        if m:
            indent = m.group(1)
            raw_comment = m.group(3)
            comment_suffix = f" {raw_comment.strip()}" if raw_comment and raw_comment.strip() else ""
            line_ending = "\r\n" if lines[idx].endswith("\r\n") else "\n"
            lines[idx] = f"{indent}public_network_access_enabled = {target_val_str}{comment_suffix}{line_ending}"
            return "".join(lines)

    # 2. Attribute is omitted: insert it into the block
    interior_indent = "  "
    if start_idx + 1 <= end_idx:
        next_line = lines[start_idx + 1]
        m_indent = re.match(r"^(\s+)\S", next_line)
        if m_indent:
            interior_indent = m_indent.group(1)

    line_ending = "\r\n" if lines[start_idx].endswith("\r\n") else "\n"
    new_line = f"{interior_indent}public_network_access_enabled = {target_val_str}{line_ending}"

    # Insert right after the resource declaration line
    lines.insert(start_idx + 1, new_line)
    return "".join(lines)


def patch_tags(
    content: str,
    resource_type: str,
    resource_name: str,
    missing_tags: dict[str, str],
) -> str:
    """Surgically append or update missing mandatory tags to a resource block.

    If a tags = { ... } block exists, appends the missing keys inside before the
    closing brace matching the interior indentation. If tag keys already exist
    with empty/invalid values, updates them in-place preserving trailing comments
    and commas. If no tags block exists, synthesizes and inserts a clean tags block
    before the resource closing brace.
    All existing comments and tags are 100% preserved.

    Args:
        content: Original HCL file text.
        resource_type: Azure resource type.
        resource_name: Terraform block label.
        missing_tags: Dict of tag keys and values to add.

    Returns:
        Surgically updated HCL file content.
    """
    if not missing_tags:
        return content

    lines = content.splitlines(keepends=True)
    block_span = find_resource_block_lines(lines, resource_type, resource_name)
    if block_span is None:
        return content

    start_idx, end_idx = block_span

    # Handle single-line resource declaration
    if start_idx == end_idx:
        lines, start_idx, end_idx = _expand_single_line_resource(lines, start_idx)

    # Guard: check if tags is assigned dynamically via variable or function (e.g. tags = var.tags)
    for idx in range(start_idx, end_idx + 1):
        if re.search(r"^\s*tags\s*=\s*(?!\{)\S+", lines[idx]):
            # Dynamic tag assignment detected - avoid injecting duplicate conflicting tags block
            return content

    line_ending = "\r\n" if (lines and lines[0].endswith("\r\n")) else "\n"

    # Search for existing tags = { ... } within resource block
    tags_start_idx: Optional[int] = None
    tags_end_idx: Optional[int] = None
    tags_pattern = re.compile(r"^\s*tags\s*=\s*\{")

    for idx in range(start_idx, end_idx + 1):
        if tags_start_idx is None:
            if tags_pattern.search(lines[idx]):
                tags_start_idx = idx
                cleaned = _strip_strings_and_comments(lines[idx])
                depth = cleaned.count("{") - cleaned.count("}")
                if depth == 0:
                    tags_end_idx = idx
                    break
        else:
            cleaned = _strip_strings_and_comments(lines[idx])
            depth += cleaned.count("{") - cleaned.count("}")
            if depth <= 0:
                tags_end_idx = idx
                break

    if tags_start_idx is not None and tags_end_idx is not None:
        if tags_start_idx == tags_end_idx:
            # Single-line tags block, e.g. tags = {} or tags = { Env = "dev" }
            line = lines[tags_start_idx]
            m_single = re.match(r"^(\s*)tags\s*=\s*\{\s*(.*?)\s*\}(.*)$", line)
            if m_single:
                indent = m_single.group(1)
                inside = m_single.group(2).strip()
                trailing = m_single.group(3).strip()
                trailing_comment = f" {trailing}" if trailing else ""
                tag_indent = indent + "  "

                existing_pairs: dict[str, str] = {}
                if inside:
                    for part in re.finditer(r'([A-Za-z0-9_-]+)\s*=\s*("[^"]*"|\S+)', inside):
                        existing_pairs[part.group(1)] = part.group(2)

                merged_tags: dict[str, str] = {}
                for k, v in existing_pairs.items():
                    merged_tags[k] = v
                for k, v in missing_tags.items():
                    merged_tags[k] = f'"{v or "..."}"'

                tag_lines = "".join(f"{tag_indent}{k} = {val}{line_ending}" for k, val in merged_tags.items())
                lines[tags_start_idx] = f"{indent}tags = {{{trailing_comment}{line_ending}{tag_lines}{indent}}}{line_ending}"
                return "".join(lines)

        # Multi-line tags block: determine interior tag indentation
        tag_indent = "    "
        for idx in range(tags_start_idx + 1, tags_end_idx):
            m_indent = re.match(r"^(\s+)\S", lines[idx])
            if m_indent:
                tag_indent = m_indent.group(1)
                break

        # Check for any keys that already exist on a line in the block (supporting quoted and unquoted keys)
        remaining_missing = dict(missing_tags)
        for idx in range(tags_start_idx + 1, tags_end_idx):
            line_str = lines[idx]
            for k in list(remaining_missing.keys()):
                m_key = re.match(rf"^(\s*)([\"']?){re.escape(k)}([\"']?)\s*=\s*(.*?)(?:\s*(#.*|//.*|/\*.*))?$", line_str)
                if m_key:
                    k_indent = m_key.group(1)
                    q_pre = m_key.group(2)
                    q_post = m_key.group(3)
                    k_val_part = m_key.group(4).strip()
                    k_comment = m_key.group(5)
                    has_comma = k_val_part.endswith(",")
                    comma_suffix = "," if has_comma else ""
                    comment_suffix = f" {k_comment.strip()}" if k_comment and k_comment.strip() else ""
                    val = remaining_missing.pop(k)
                    lines[idx] = f'{k_indent}{q_pre}{k}{q_post} = "{val or "..."}"{comma_suffix}{comment_suffix}{line_ending}'

        # Format remaining missing tags
        new_tag_lines = [
            f'{tag_indent}{k} = "{v or "..."}"{line_ending}'
            for k, v in remaining_missing.items()
        ]
        # Insert before closing brace of tags block
        for offset, tag_line in enumerate(new_tag_lines):
            lines.insert(tags_end_idx + offset, tag_line)

        return "".join(lines)

    # No tags block exists: inject new tags = { ... } block
    # Determine resource interior indentation
    interior_indent = "  "
    for idx in range(start_idx + 1, end_idx):
        m_indent = re.match(r"^(\s+)\S", lines[idx])
        if m_indent:
            interior_indent = m_indent.group(1)
            break

    tag_indent = interior_indent + "  "
    tag_entries = "".join(
        f'{tag_indent}{k} = "{v or "..."}"{line_ending}'
        for k, v in missing_tags.items()
    )
    new_tags_block = (
        f"{line_ending}{interior_indent}tags = {{{line_ending}"
        f"{tag_entries}"
        f"{interior_indent}}}{line_ending}"
    )

    # Insert right before resource block closing brace
    lines.insert(end_idx, new_tags_block)
    return "".join(lines)


def generate_companion_private_endpoint(
    resource_type: str,
    resource_name: str,
    location: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    subnet_id: Optional[str] = None,
    tags: Optional[dict[str, str]] = None,
) -> str:
    """Generate a syntactically valid companion azurerm_private_endpoint block.

    Includes private_service_connection linked to the primary resource and
    private_dns_zone_group configured for Hub Private DNS.

    Args:
        resource_type: Target PaaS resource type.
        resource_name: Target PaaS block name.
        location: Azure region (defaults to westeurope).
        resource_group_name: Target resource group name.
        subnet_id: Target candidate subnet ID.
        tags: Optional resource tags.

    Returns:
        Formatted HCL block string ready for appending.
    """
    pe_name = f"pe-{resource_name}"
    pe_res_label = f"pe_{resource_name}".replace("-", "_")

    loc = location or "westeurope"
    loc_val = f'"{loc}"' if not (loc.startswith("var.") or loc.startswith("local.") or "." in loc) else loc

    rg = resource_group_name or f"rg-{resource_name}"
    rg_val = f'"{rg}"' if not (rg.startswith("var.") or rg.startswith("local.") or "." in rg) else rg
    rg_dns_ref = f"${{{rg}}}" if (rg.startswith("var.") or rg.startswith("local.") or "." in rg) else rg

    snet = subnet_id or "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet/subnets/snet-pe"

    subresources = get_paas_subresource_names(resource_type)
    subres_str = ", ".join(f'"{s}"' for s in subresources) if subresources else '"blob"'

    dns_zone = get_paas_default_dns_zone(resource_type) or "privatelink.blob.core.windows.net"

    tags_block = ""
    if tags:
        tag_lines = "\n".join(f'    {k} = "{v}"' for k, v in sorted(tags.items()))
        tags_block = f"""
  tags = {{
{tag_lines}
  }}"""

    return f"""

resource "azurerm_private_endpoint" "{pe_res_label}" {{
  name                = "{pe_name}"
  location            = {loc_val}
  resource_group_name = {rg_val}
  subnet_id           = "{snet}"{tags_block}

  private_service_connection {{
    name                           = "psc-{resource_name}"
    private_connection_resource_id = {resource_type}.{resource_name}.id
    subresource_names              = [{subres_str}]
    is_manual_connection           = false
  }}

  private_dns_zone_group {{
    name                 = "default"
    private_dns_zone_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/{rg_dns_ref}/providers/Microsoft.Network/privateDnsZones/{dns_zone}"]
  }}
}}
"""
