"""Pure-Python HCL serialization and formatting utilities."""

import re
from typing import Any, Optional


class HclReference:
    """An unquoted HCL expression or resource/data attribute reference."""

    def __init__(self, expr: str) -> None:
        self.expr = expr.strip()

    def __str__(self) -> str:
        return self.expr

    def __repr__(self) -> str:
        return f"HclReference({self.expr!r})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, HclReference):
            return self.expr == other.expr
        return False


def escape_hcl_string(value: str) -> str:
    """Escape special characters in HCL string literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("${", "$${")
        .replace("%{", "%%{")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def is_valid_hcl_identifier(name: str) -> bool:
    """Check if a string is a valid HCL bare identifier (can be unquoted in map keys)."""
    return bool(re.fullmatch(r"^[a-zA-Z_][a-zA-Z0-9_-]*$", name))


def format_hcl_value(value: Any, indent_level: int = 0) -> str:
    """Format a Python value into canonical HCL syntax.

    Args:
        value: The Python object (str, int, float, bool, dict, list, tuple, set, HclReference).
        indent_level: Current indentation level (number of 2-space indents).

    Returns:
        Formatted HCL representation.
    """
    if isinstance(value, HclReference):
        return value.expr

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        return f'"{escape_hcl_string(value)}"'

    if isinstance(value, dict):
        if not value:
            return "{}"
        base_indent = "  " * indent_level
        inner_indent = "  " * (indent_level + 1)
        formatted_items: list[tuple[str, Any]] = []
        for k in sorted(value.keys()):
            key_str = str(k)
            fmt_k = key_str if is_valid_hcl_identifier(key_str) else f'"{escape_hcl_string(key_str)}"'
            formatted_items.append((fmt_k, value[k]))
        max_key_len = max(len(fmt_k) for fmt_k, _ in formatted_items)
        lines = ["{"]
        for fmt_k, v in formatted_items:
            padded_key = fmt_k.ljust(max_key_len)
            formatted_val = format_hcl_value(v, indent_level=indent_level + 1)
            lines.append(f"{inner_indent}{padded_key} = {formatted_val}")
        lines.append(f"{base_indent}}}")
        return "\n".join(lines)

    if isinstance(value, (list, tuple, set)):
        items = sorted(value, key=lambda x: str(x)) if isinstance(value, set) else list(value)
        if not items:
            return "[]"
        if len(items) <= 3 and all(
            isinstance(x, (str, int, float, bool, HclReference)) and len(str(x)) < 30
            for x in items
        ):
            return "[" + ", ".join(format_hcl_value(x, indent_level) for x in items) + "]"
        base_indent = "  " * indent_level
        inner_indent = "  " * (indent_level + 1)
        lines = ["["]
        for item in items:
            lines.append(f"{inner_indent}{format_hcl_value(item, indent_level + 1)},")
        lines.append(f"{base_indent}]")
        return "\n".join(lines)

    if value is None:
        return "null"

    return f'"{escape_hcl_string(str(value))}"'


class HclBlock:
    """A Terraform HCL block (e.g. resource, data, terraform, backend)."""

    def __init__(
        self,
        block_type: str,
        labels: Optional[list[str]] = None,
        attributes: Optional[dict[str, Any]] = None,
        nested_blocks: Optional[list["HclBlock"]] = None,
    ) -> None:
        self.block_type = block_type
        self.labels = labels or []
        self.attributes = attributes or {}
        self.nested_blocks = nested_blocks or []

    def add_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_nested_block(self, block: "HclBlock") -> None:
        self.nested_blocks.append(block)

    def render(self, indent_level: int = 0) -> str:
        """Render this block to HCL with standard 2-space indentation."""
        indent = "  " * indent_level
        inner_indent = "  " * (indent_level + 1)

        # Header: block_type "label1" "label2" {
        labels_str = " ".join(f'"{escape_hcl_string(l)}"' for l in self.labels)
        header = f"{self.block_type} {labels_str}".strip() + " {"

        lines = [f"{indent}{header}"]

        # Separate simple scalar attributes from complex dict/map attributes for clean layout
        scalar_attrs: dict[str, Any] = {}
        complex_attrs: dict[str, Any] = {}
        for k, v in self.attributes.items():
            if isinstance(v, dict):
                complex_attrs[k] = v
            else:
                scalar_attrs[k] = v

        # Render scalar attributes with aligned equals
        if scalar_attrs:
            max_key_len = max(len(k) for k in scalar_attrs.keys())
            for k, v in scalar_attrs.items():
                padded_key = k.ljust(max_key_len)
                val_str = format_hcl_value(v, indent_level=indent_level + 1)
                lines.append(f"{inner_indent}{padded_key} = {val_str}")

        # Render complex attributes (e.g. tags = { ... }) with blank line separation
        for k, v in complex_attrs.items():
            if scalar_attrs or lines[-1] != f"{indent}{header}":
                lines.append("")
            val_str = format_hcl_value(v, indent_level=indent_level + 1)
            lines.append(f"{inner_indent}{k} = {val_str}")

        # Render nested blocks with blank line separation
        for block in self.nested_blocks:
            if len(lines) > 1 and lines[-1] != "":
                lines.append("")
            lines.append(block.render(indent_level=indent_level + 1))

        lines.append(f"{indent}}}")
        return "\n".join(lines)


def render_hcl_document(blocks: list[HclBlock]) -> str:
    """Render a list of top-level HCL blocks into a document string with trailing newline."""
    if not blocks:
        return ""
    rendered_blocks = [b.render(0) for b in blocks]
    return "\n\n".join(rendered_blocks) + "\n"


def build_resource_block(
    resource_type: str,
    name: str,
    attributes: Optional[dict[str, Any]] = None,
) -> HclBlock:
    """Convenience factory for a Terraform resource block."""
    return HclBlock(
        block_type="resource",
        labels=[resource_type, name],
        attributes=attributes or {},
    )


def build_data_block(
    data_type: str,
    name: str,
    attributes: Optional[dict[str, Any]] = None,
) -> HclBlock:
    """Convenience factory for a Terraform data block."""
    return HclBlock(
        block_type="data",
        labels=[data_type, name],
        attributes=attributes or {},
    )


def build_backend_block(
    backend_type: str = "azurerm",
    **config: Any,
) -> HclBlock:
    """Convenience factory for a terraform { backend "..." { ... } } block."""
    backend_inner = HclBlock(
        block_type="backend",
        labels=[backend_type],
        attributes=config,
    )
    return HclBlock(
        block_type="terraform",
        nested_blocks=[backend_inner],
    )
