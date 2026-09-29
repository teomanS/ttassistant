"""Abstract port definition for read-only HCL AST parsing (AD-1, AD-2)."""

from collections.abc import Iterable
from pathlib import Path
from typing import Optional, Protocol, Union, runtime_checkable

from ttassistant.domain.compliance import ParsedResource
from ttassistant.domain.topology import CandidateFile, DiscoveredTopology


@runtime_checkable
class HCLParserPort(Protocol):
    """Abstract interface for read-only HCL AST parsing."""

    def parse_topology_candidates(
        self,
        candidates: Union[Iterable[CandidateFile], Iterable[Union[Path, str]]],
    ) -> DiscoveredTopology:
        """Parse identified candidate files into structured domain topology entities.

        Args:
            candidates: Discovered CandidateFile objects or file paths to parse.

        Returns:
            DiscoveredTopology containing extracted Subnets, VNets, and Resource Groups.
        """
        ...

    def parse_hcl_string(
        self,
        content: str,
        filename: str = "<string>",
        subscription: Optional[str] = None,
    ) -> DiscoveredTopology:
        """Parse raw HCL string content in-memory into structured domain topology entities.

        Args:
            content: Raw HCL code string.
            filename: Virtual or source filename for origin tracking.
            subscription: Optional subscription identifier.

        Returns:
            DiscoveredTopology containing extracted entities.
        """
        ...

    def parse_hcl_file(
        self,
        file_path: Union[Path, str],
        subscription: Optional[str] = None,
    ) -> DiscoveredTopology:
        """Read and parse a single HCL file into DiscoveredTopology entities.

        Args:
            file_path: File path to read and parse.
            subscription: Optional subscription identifier.

        Returns:
            DiscoveredTopology containing extracted entities.
        """
        ...

    def parse_resources(
        self,
        content: str,
        filename: str = "<string>",
    ) -> tuple[list[ParsedResource], list[str]]:
        """Extract declared resource blocks and their attributes from HCL content.

        Args:
            content: Raw HCL code string.
            filename: Virtual or source filename.

        Returns:
            Tuple of (list of ParsedResource, list of parse warning strings).
        """
        ...

    def parse_resources_from_file(
        self,
        file_path: Union[Path, str],
    ) -> tuple[list[ParsedResource], list[str]]:
        """Read and extract declared resource blocks from an HCL file.

        Args:
            file_path: File path to read and parse.

        Returns:
            Tuple of (list of ParsedResource, list of parse warning strings).
        """
        ...

