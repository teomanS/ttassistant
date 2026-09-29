"""Adapters layer for ttassistant.

Concrete implementations of ports connecting ttassistant to external
systems (terminal, filesystem, HCL parser, markdown standards reader).
"""

from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.adapters.tweak_adapter import DeterministicTweakParserAdapter

__all__ = [
    "DeterministicTweakParserAdapter",
    "DiskFileSystemAdapter",
    "JsonResourceCatalogAdapter",
    "MarkdownStandardsAdapter",
    "ReadOnlyHclAdapter",
    "RichTerminalAdapter",
]

