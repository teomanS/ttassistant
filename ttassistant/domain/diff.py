"""Pure domain logic for computing unified diffs between disk files and in-memory StagedWorkspace."""

import difflib
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from ttassistant.domain.models import StagedFile, StagedWorkspace


class FileDiff(BaseModel):
    """Unified diff result for an individual file."""

    path: str = Field(..., description="Target file path relative to workspace or repository")
    diff_text: str = Field(..., description="Unified diff formatted text")
    is_new: bool = Field(default=True, description="Whether this is a newly created file")
    has_changes: bool = Field(default=True, description="Whether there are changes to be applied")


class WorkspaceDiff(BaseModel):
    """Aggregated unified diff result across all workspace files."""

    files: list[FileDiff] = Field(default_factory=list, description="List of individual file diffs")
    diff_text: str = Field(default="", description="Combined unified diff across all files")
    has_changes: bool = Field(default=False, description="Whether any file has changes")

    @property
    def changed_file_count(self) -> int:
        """Count of files with changes."""
        return sum(1 for f in self.files if f.has_changes)


def compute_file_diff(
    file_path: str,
    new_content: str,
    existing_content: Optional[str] = None,
    is_new: Optional[bool] = None,
) -> FileDiff:
    """Compute unified diff for a single file.

    Args:
        file_path: Relative path to display in diff header.
        new_content: Staged in-memory content.
        existing_content: Optional existing file content on disk.
        is_new: Whether file is greenfield (defaults to existing_content is None).

    Returns:
        FileDiff containing diff text and metadata.
    """
    if existing_content is not None and not isinstance(existing_content, str):
        existing_content = None

    if is_new is None:
        file_is_new = existing_content is None
    else:
        file_is_new = is_new

    if file_is_new or existing_content is None:
        from_lines = []
    else:
        from_lines = existing_content.splitlines(keepends=True)
    to_lines = new_content.splitlines(keepends=True) if new_content is not None else []

    if not file_is_new and existing_content is not None and existing_content == new_content:
        return FileDiff(
            path=file_path,
            diff_text="",
            is_new=file_is_new,
            has_changes=False,
        )

    from_file = "/dev/null" if file_is_new else file_path
    to_file = file_path

    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=from_file,
            tofile=to_file,
        )
    )

    if not diff_lines:
        return FileDiff(
            path=file_path,
            diff_text="",
            is_new=file_is_new,
            has_changes=False,
        )

    diff_text = "".join(diff_lines)
    if not diff_text.endswith("\n"):
        diff_text += "\n"

    return FileDiff(
        path=file_path,
        diff_text=diff_text,
        is_new=file_is_new,
        has_changes=True,
    )


def compute_workspace_diff(
    workspace: StagedWorkspace,
    existing_files: Optional[dict[str, str]] = None,
) -> WorkspaceDiff:
    """Compute unified diff across all staged files in a workspace.

    Args:
        workspace: In-memory StagedWorkspace.
        existing_files: Optional mapping of filename or path to existing disk content.

    Returns:
        WorkspaceDiff containing all file diffs and combined diff text.
    """
    file_diffs: list[FileDiff] = []
    combined_parts: list[str] = []
    has_any_changes = False

    if existing_files is not None and not isinstance(existing_files, dict):
        existing_files = {}

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

    # Sort files deterministically
    sorted_files = sorted(workspace.files.items(), key=lambda item: item[0])

    for filename, staged_file in sorted_files:
        # Resolve display path
        if staged_file.path.startswith(target_dir):
            rel_path = staged_file.path
        elif "/" in staged_file.path or "\\" in staged_file.path:
            rel_path = staged_file.path
        elif target_dir:
            rel_path = f"{target_dir}/{staged_file.filename}"
        else:
            rel_path = staged_file.filename

        existing_content: Optional[str] = None
        has_existing = False
        if existing_files is not None:
            if rel_path in existing_files:
                existing_content = existing_files[rel_path]
                has_existing = True
            elif staged_file.path in existing_files:
                existing_content = existing_files[staged_file.path]
                has_existing = True
            elif is_single_dir and staged_file.filename in existing_files:
                existing_content = existing_files[staged_file.filename]
                has_existing = True

        file_diff = compute_file_diff(
            file_path=rel_path,
            new_content=staged_file.content,
            existing_content=existing_content,
            is_new=staged_file.is_new if not has_existing else False,
        )
        file_diffs.append(file_diff)
        if file_diff.has_changes:
            has_any_changes = True
            combined_parts.append(file_diff.diff_text)

    combined_diff_text = "".join(combined_parts)

    return WorkspaceDiff(
        files=file_diffs,
        diff_text=combined_diff_text,
        has_changes=has_any_changes,
    )


def generate_workspace_diff(
    workspace: StagedWorkspace,
    existing_files: Optional[dict[str, str]] = None,
) -> str:
    """Helper returning the combined unified diff string for a workspace."""
    diff = compute_workspace_diff(workspace, existing_files)
    return diff.diff_text
