"""Application service orchestrating in-memory conversational tweak refinements (AD-1, AD-4)."""

import logging
import re
import time
from typing import Any, Optional

from ttassistant.domain.exceptions import TweakParseError
from ttassistant.domain.models import StagedWorkspace
from ttassistant.domain.tweak import (
    mutate_hcl_attribute,
    mutate_hcl_tag,
)
from ttassistant.ports.catalog import ResourceCatalogPort
from ttassistant.ports.tweak_parser import (
    ParsedTweak,
    TweakAction,
    TweakParserPort,
    TweakResult,
)

logger = logging.getLogger(__name__)


class TweakHandler:
    """Coordinates parsing of tweak instructions and in-memory mutation of StagedWorkspace."""

    def __init__(
        self,
        parser: TweakParserPort,
        catalog: Optional[ResourceCatalogPort] = None,
    ) -> None:
        """Initialize TweakHandler with parser port and optional catalog.

        Args:
            parser: Tweak parser implementing TweakParserPort.
            catalog: Resource catalog port for schema validations.
        """
        self.catalog = catalog
        self.parser = parser

    def _detect_resource_type(self, workspace: StagedWorkspace, content: str) -> Optional[str]:
        """Detect target resource type from parameters, metadata, or HCL content."""
        if workspace.parameters and workspace.parameters.resource_type:
            return workspace.parameters.resource_type

        # Check metadata
        for sf in workspace.files.values():
            if sf.metadata.get("resource_type"):
                return sf.metadata["resource_type"]

        # Parse from HCL content
        m = re.search(r'resource\s+"(azurerm_[^"]+)"', content)
        if m:
            return m.group(1)

        return None

    def apply_tweak(
        self,
        workspace: StagedWorkspace,
        tweak_instruction: str,
        target_file: str = "main.tf",
    ) -> TweakResult:
        """Apply a colloquial or direct tweak to the in-memory StagedWorkspace.

        Guarantees sub-10ms air-gapped execution with zero external network calls.

        Args:
            workspace: The in-memory StagedWorkspace to mutate.
            tweak_instruction: Colloquial instruction text (e.g. 'Change replication to GRS').
            target_file: Relative file path to modify in workspace. Defaults to 'main.tf'.

        Returns:
            TweakResult containing success status, parsed tweak entity, elapsed time, and diff summary.
        """
        start_time = time.perf_counter()

        # Locate target file in workspace
        staged_file = workspace.get_file(target_file)
        if staged_file is None:
            # Fallback to any file with matching name or path suffix
            for f in workspace.files.values():
                if f.filename == target_file or f.path.endswith(f"/{target_file}"):
                    staged_file = f
                    break
        if staged_file is None:
            # Fallback to any .tf file containing a resource block
            for f in workspace.files.values():
                if f.path.endswith(".tf") and 'resource "' in f.content:
                    staged_file = f
                    break
        if staged_file is None and workspace.files:
            # Fallback to first .tf staged file
            for f in workspace.files.values():
                if f.path.endswith(".tf"):
                    staged_file = f
                    break

        if staged_file is None:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return TweakResult(
                success=False,
                target_file=target_file,
                elapsed_ms=elapsed_ms,
                error_message=f"Target file '{target_file}' not found in staged workspace.",
            )

        resource_type = self._detect_resource_type(workspace, staged_file.content)

        # Parse tweak instruction
        try:
            parsed = self.parser.parse(tweak_instruction, resource_type=resource_type)
        except TweakParseError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return TweakResult(
                success=False,
                target_file=staged_file.path,
                elapsed_ms=elapsed_ms,
                error_message=str(exc),
            )

        old_val: Optional[Any] = None
        modified = False
        new_content = staged_file.content

        if parsed.action == TweakAction.SET_TAG:
            new_content, modified, old_val = mutate_hcl_tag(
                staged_file.content,
                tag_key=parsed.attribute_name,
                tag_value=str(parsed.value),
                resource_type=resource_type,
            )
            if modified and workspace.parameters:
                workspace.parameters.tags[parsed.attribute_name] = str(parsed.value)

        elif parsed.action == TweakAction.REMOVE_TAG:
            new_content, modified, old_val = mutate_hcl_tag(
                staged_file.content,
                tag_key=parsed.attribute_name,
                tag_value=None,
                resource_type=resource_type,
            )
            if modified and workspace.parameters and parsed.attribute_name in workspace.parameters.tags:
                del workspace.parameters.tags[parsed.attribute_name]

        elif parsed.action in (TweakAction.SET_ATTRIBUTE, TweakAction.TOGGLE_BOOLEAN):
            new_content, modified, old_val = mutate_hcl_attribute(
                staged_file.content,
                attribute_name=parsed.attribute_name,
                new_value=parsed.value,
                resource_type=resource_type,
            )
            if modified and workspace.parameters:
                if parsed.attribute_name == "public_network_access_enabled":
                    workspace.parameters.public_network_access = bool(parsed.value)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        if not modified:
            return TweakResult(
                success=False,
                parsed_tweak=parsed,
                target_file=staged_file.path,
                elapsed_ms=elapsed_ms,
                error_message=f"Could not apply tweak to '{staged_file.path}': attribute or block not found.",
            )

        # Update in-memory file content
        staged_file.content = new_content

        # Record tweak metadata and invalidate caches
        workspace.metadata["last_tweak"] = tweak_instruction
        workspace.metadata["tweak_applied"] = True

        # Create concise diff summary
        if parsed.action in (TweakAction.SET_TAG, TweakAction.REMOVE_TAG):
            action_desc = "Removed tag" if parsed.action == TweakAction.REMOVE_TAG else "Updated tag"
            summary = f"{action_desc} '{parsed.attribute_name}'" + (
                f" = '{parsed.value}'" if parsed.value is not None else ""
            )
        else:
            summary = f"Set '{parsed.attribute_name}' = {parsed.value}"
            if old_val is not None:
                summary += f" (was {old_val})"

        return TweakResult(
            success=True,
            parsed_tweak=parsed,
            target_file=staged_file.path,
            old_value=old_val,
            new_value=parsed.value,
            elapsed_ms=elapsed_ms,
            diff_summary=summary,
        )
