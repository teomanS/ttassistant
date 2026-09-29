from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from ttassistant.domain.models import StagedWorkspace
from ttassistant.domain.topology import CandidateFile, TopologyIndex


@runtime_checkable
class FileSystemPort(Protocol):
    """Abstract port defining filesystem operations and atomic workspace commitments."""

    def file_exists(self, path: Path | str) -> bool:
        """Return True if the file exists on disk."""
        ...

    def dir_exists(self, path: Path | str) -> bool:
        """Return True if the directory exists on disk."""
        ...

    def read_file(self, path: Path | str) -> str:
        """Read and return file text content from disk."""
        ...

    def read_workspace_existing_files(
        self,
        workspace: StagedWorkspace,
        base_dir: Path | None = None,
    ) -> dict[str, str]:
        """Read existing content for all files matching staged files in workspace.

        Returns:
            Dictionary mapping relative file paths/names to existing content strings.
        """
        ...

    def commit_workspace(
        self,
        workspace: StagedWorkspace,
        base_dir: Path | None = None,
    ) -> list[Path]:
        """Atomically commit all files in workspace to disk.

        Writes hidden sibling .tmp files, calls os.fsync, and replaces atomically.
        Rolls back all changes on any error.

        Returns:
            List of successfully written Path objects.

        Raises:
            FileSystemError: If any I/O, OS, or permission error occurs during write.
        """
        ...

    def scan_tf_files(
        self,
        root_dir: Path | str,
        ignored_dirs: Optional[Iterable[str]] = None,
    ) -> Iterator[Path]:
        """Streamingly traverse root_dir and yield all discovered .tf file paths, skipping ignored directories."""
        ...

    def scan_candidates(
        self,
        root_dir: Path | str,
        target_types: Optional[Iterable[str]] = None,
        ignored_dirs: Optional[Iterable[str]] = None,
    ) -> Iterator[CandidateFile]:
        """Streamingly scan .tf files in root_dir and yield CandidateFile instances matching target resource types."""
        ...

    def build_topology_index(
        self,
        root_dir: Path | str,
        target_types: Optional[Iterable[str]] = None,
        ignored_dirs: Optional[Iterable[str]] = None,
    ) -> TopologyIndex:
        """Scan repository topology and compile an in-memory TopologyIndex of candidates and execution metrics."""
        ...
