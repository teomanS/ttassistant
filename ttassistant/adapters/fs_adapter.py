from collections.abc import Iterable, Iterator
import os
from pathlib import Path
import shutil
import time
from typing import Optional
import uuid

from ttassistant.domain.exceptions import FileSystemError
from ttassistant.domain.models import StagedWorkspace
from ttassistant.domain.topology import (
    DEFAULT_TARGET_RESOURCE_TYPES,
    CandidateFile,
    TopologyIndex,
    extract_candidate_types,
    infer_subscription,
)
from ttassistant.ports.filesystem import FileSystemPort

DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset({
    ".git",
    ".terraform",
    ".venv",
    "venv",
    ".env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".bin",
    "bin",
    ".idea",
    ".vscode",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
})


class DiskFileSystemAdapter:
    """Concrete filesystem adapter providing atomic multi-file disk writes and rollbacks."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def file_exists(self, path: Path | str) -> bool:
        """Return True if the file exists on disk."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p.is_file()

    def dir_exists(self, path: Path | str) -> bool:
        """Return True if the directory exists on disk."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p.is_dir()

    def read_file(self, path: Path | str) -> str:
        """Read and return file text content from disk."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        try:
            return p.read_text(encoding="utf-8")
        except Exception as exc:
            raise FileSystemError(f"Failed to read file '{p}': {exc}", details=str(exc)) from exc

    def read_workspace_existing_files(
        self,
        workspace: StagedWorkspace,
        base_dir: Path | None = None,
    ) -> dict[str, str]:
        """Read existing content for all files matching staged files in workspace."""
        target_base = Path(base_dir).resolve() if base_dir else self.base_dir
        existing_files: dict[str, str] = {}
        target_dir = workspace.target_dir.rstrip("/")

        # Check if files span multiple target directories to prevent filename collisions
        target_dirs = set()
        for sf in workspace.files.values():
            if sf.path.startswith(target_dir):
                target_dirs.add(target_dir)
            elif "/" in sf.path or "\\" in sf.path:
                target_dirs.add(str(Path(sf.path).parent))
            elif target_dir:
                target_dirs.add(target_dir)
        is_single_dir = len(target_dirs) <= 1

        for key, staged_file in workspace.files.items():
            if staged_file.path.startswith(target_dir):
                rel_path = staged_file.path
            elif "/" in staged_file.path or "\\" in staged_file.path:
                rel_path = staged_file.path
            elif target_dir:
                rel_path = f"{target_dir}/{staged_file.filename}"
            else:
                rel_path = staged_file.filename

            dest_path = (target_base / rel_path).resolve()
            if not dest_path.is_relative_to(target_base):
                raise FileSystemError(f"Path traversal detected: {dest_path}")
            if dest_path.is_file():
                try:
                    content = dest_path.read_text(encoding="utf-8")
                    existing_files[rel_path] = content
                    existing_files[key] = content
                    existing_files[staged_file.path] = content
                    if is_single_dir:
                        existing_files[staged_file.filename] = content
                except Exception as exc:
                    raise FileSystemError(
                        f"Failed to read existing file '{dest_path}': {exc}",
                        details=str(exc),
                    ) from exc
        return existing_files

    def commit_workspace(
        self,
        workspace: StagedWorkspace,
        base_dir: Path | None = None,
    ) -> list[Path]:
        """Atomically commit all files in workspace to disk.

        Each file is written to a hidden sibling .tmp file, flushed, fsynced,
        and atomically swapped via os.replace.
        If any failure occurs, all swapped files and created directories are rolled back.
        """
        target_base = Path(base_dir).resolve() if base_dir else self.base_dir
        target_base.mkdir(parents=True, exist_ok=True)
        target_dir = workspace.target_dir.rstrip("/")

        created_dirs: list[Path] = []
        temp_files: list[Path] = []
        backup_files: list[Path] = []
        swapped_files: list[tuple[Path, Optional[Path]]] = []
        committed_paths: list[Path] = []

        def ensure_dir(dir_path: Path) -> None:
            current = dir_path
            to_create: list[Path] = []
            while current != target_base and not current.exists():
                to_create.append(current)
                if current.parent == current:
                    break
                current = current.parent
            for d in reversed(to_create):
                d.mkdir(parents=False, exist_ok=True)
                if d not in created_dirs:
                    created_dirs.append(d)

        plan: list[tuple[Path, str]] = []
        for key, staged_file in sorted(workspace.files.items()):
            if staged_file.path.startswith(target_dir):
                rel_path = staged_file.path
            elif "/" in staged_file.path or "\\" in staged_file.path:
                rel_path = staged_file.path
            elif target_dir:
                rel_path = f"{target_dir}/{staged_file.filename}"
            else:
                rel_path = staged_file.filename
            dest_path = (target_base / rel_path).resolve()
            if not dest_path.is_relative_to(target_base):
                raise FileSystemError(f"Path traversal detected: {dest_path}")
            plan.append((dest_path, staged_file.content))

        tx_id = uuid.uuid4().hex

        try:
            # Phase 1: Write all sibling .tmp files and os.fsync
            stage_plan: list[tuple[Path, Path]] = []  # (temp_path, dest_path)
            for dest_path, content in plan:
                dest_dir = dest_path.parent
                ensure_dir(dest_dir)

                temp_path = dest_dir / f".{dest_path.name}.{tx_id}.tmp"
                temp_files.append(temp_path)

                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

                if dest_path.exists():
                    shutil.copymode(dest_path, temp_path)

                stage_plan.append((temp_path, dest_path))

            # Phase 2: Atomic Swap with os.replace
            for temp_path, dest_path in stage_plan:
                dest_dir = dest_path.parent
                backup_path: Optional[Path] = None

                if dest_path.exists():
                    backup_path = dest_dir / f".{dest_path.name}.{tx_id}.bak"
                    try:
                        shutil.copy2(dest_path, backup_path)
                    except Exception:
                        if backup_path.exists():
                            backup_path.unlink()
                        raise
                    backup_files.append(backup_path)

                os.replace(temp_path, dest_path)
                swapped_files.append((dest_path, backup_path))
                committed_paths.append(dest_path)

                # Sync directory entry on POSIX systems if supported
                try:
                    dir_fd = os.open(str(dest_dir), os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except (OSError, AttributeError):
                    pass

        except Exception as exc:
            # Rollback Phase: Restore swapped files and remove newly created files
            for dest_path, backup_path in reversed(swapped_files):
                try:
                    if backup_path and backup_path.exists():
                        os.replace(backup_path, dest_path)
                    elif dest_path.exists():
                        dest_path.unlink()
                except Exception:
                    pass

            # Clean up all backups
            for bf in backup_files:
                try:
                    if bf.exists():
                        bf.unlink()
                except Exception:
                    pass

            # Clean up all temp files
            for tf in temp_files:
                try:
                    if tf.exists():
                        tf.unlink()
                except Exception:
                    pass

            # Clean up empty created directories in reverse order
            for d in reversed(created_dirs):
                try:
                    if d.exists() and not any(d.iterdir()):
                        d.rmdir()
                except Exception:
                    pass

            raise FileSystemError(
                f"Disk write failure during atomic workspace commit: {exc}",
                details=str(exc),
            ) from exc

        # Success: Clean up all backups
        for bf in backup_files:
            try:
                if bf.exists():
                    bf.unlink()
            except Exception:
                pass

        return committed_paths

    def scan_tf_files(
        self,
        root_dir: Path | str,
        ignored_dirs: Optional[Iterable[str]] = None,
    ) -> Iterator[Path]:
        """Streamingly traverse directory tree using os.scandir, skipping ignored directories and cyclic symlinks.

        Adheres to NFR-2 (<3.0s / 10k files) and NFR-3 (<150MB RSS) via non-recursive stack iteration.
        """
        root_path = Path(root_dir)
        if not root_path.is_absolute():
            root_path = (self.base_dir / root_path).resolve()
        else:
            root_path = root_path.resolve()

        if not root_path.is_dir():
            return

        ignored = frozenset(ignored_dirs) if ignored_dirs is not None else DEFAULT_IGNORED_DIRS
        stack = [str(root_path)]
        visited_realpaths: set[str] = {os.path.realpath(str(root_path))}

        while stack:
            curr = stack.pop()
            try:
                with os.scandir(curr) as it:
                    for entry in it:
                        try:
                            if entry.name in ignored:
                                continue

                            # Detect directory (including symlinks pointing to directories)
                            if entry.is_dir(follow_symlinks=True):
                                real_p = os.path.realpath(entry.path)
                                if real_p in visited_realpaths:
                                    continue  # Skip cyclic or already traversed directory symlinks
                                visited_realpaths.add(real_p)
                                stack.append(entry.path)
                            elif entry.name.endswith(".tf") and entry.is_file(follow_symlinks=True):
                                yield Path(entry.path)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

    def _inspect_tf_file(
        self,
        tf_path: Path,
        targets: frozenset[str],
        root_path: Path,
    ) -> Optional[CandidateFile]:
        """Streamingly inspect a .tf file in 64KB chunks to detect candidate resource/data blocks."""
        try:
            detected_types: set[str] = set()
            first_chunk: str = ""
            with open(tf_path, "r", encoding="utf-8", errors="replace") as f:
                chunk_idx = 0
                tail = ""
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    if chunk_idx == 0:
                        first_chunk = chunk
                    chunk_idx += 1

                    data = tail + chunk
                    tail = chunk[-256:] if len(chunk) >= 256 else chunk

                    if any(t in data for t in targets):
                        matched = extract_candidate_types(data, target_types=targets)
                        detected_types.update(matched)

            if detected_types:
                inferred_sub = infer_subscription(tf_path, content_hints=first_chunk, root_dir=root_path)
                return CandidateFile(
                    path=str(tf_path),
                    subscription=inferred_sub,
                    detected_types=detected_types,
                )
        except (PermissionError, OSError):
            pass
        return None

    def scan_candidates(
        self,
        root_dir: Path | str,
        target_types: Optional[Iterable[str]] = None,
        ignored_dirs: Optional[Iterable[str]] = None,
        stats: Optional[dict[str, int]] = None,
    ) -> Iterator[CandidateFile]:
        """Streamingly scan .tf files in root_dir, applying streaming lexical keyword and regex matching."""
        targets = frozenset(target_types) if target_types is not None else DEFAULT_TARGET_RESOURCE_TYPES
        root_path = Path(root_dir)
        if not root_path.is_absolute():
            root_path = (self.base_dir / root_path).resolve()
        else:
            root_path = root_path.resolve()

        for tf_path in self.scan_tf_files(root_dir, ignored_dirs=ignored_dirs):
            if stats is not None:
                stats["scanned"] = stats.get("scanned", 0) + 1
            cand = self._inspect_tf_file(tf_path, targets, root_path)
            if cand is not None:
                yield cand

    def build_topology_index(
        self,
        root_dir: Path | str,
        target_types: Optional[Iterable[str]] = None,
        ignored_dirs: Optional[Iterable[str]] = None,
    ) -> TopologyIndex:
        """Scan repository topology and compile an in-memory TopologyIndex of candidates and execution metrics."""
        start_time = time.perf_counter()
        stats = {"scanned": 0}
        candidates = list(
            self.scan_candidates(
                root_dir=root_dir,
                target_types=target_types,
                ignored_dirs=ignored_dirs,
                stats=stats,
            )
        )
        duration = time.perf_counter() - start_time
        return TopologyIndex(
            candidates=candidates,
            total_files_scanned=stats["scanned"],
            duration_seconds=duration,
        )
