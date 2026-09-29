"""Ports layer for ttassistant.

Defines abstract interface protocols (TerminalUIPort, FileSystemPort,
StandardsSourcePort, TweakParserPort) that decouple domain and application
logic from concrete I/O adapters.
"""

from ttassistant.ports.catalog import ResourceCatalogPort
from ttassistant.ports.filesystem import FileSystemPort
from ttassistant.ports.hcl_parser import HCLParserPort
from ttassistant.ports.standards_source import StandardsSourcePort
from ttassistant.ports.terminal import TerminalUIPort
from ttassistant.ports.tweak_parser import (
    ParsedTweak,
    TweakAction,
    TweakParserPort,
    TweakResult,
)

__all__ = [
    "FileSystemPort",
    "HCLParserPort",
    "ParsedTweak",
    "ResourceCatalogPort",
    "StandardsSourcePort",
    "TerminalUIPort",
    "TweakAction",
    "TweakParserPort",
    "TweakResult",
]

