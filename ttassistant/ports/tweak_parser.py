"""Protocol port interface for the air-gapped deterministic tweak engine (AD-1, AD-4)."""

from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable
from pydantic import BaseModel, Field


class TweakAction(str, Enum):
    """Enumeration of supported tweak operations."""

    SET_ATTRIBUTE = "set_attribute"
    SET_TAG = "set_tag"
    REMOVE_TAG = "remove_tag"
    TOGGLE_BOOLEAN = "toggle_boolean"


class ParsedTweak(BaseModel):
    """Structured result of parsing a conversational or direct tweak instruction."""

    action: TweakAction = Field(..., description="Action type to perform")
    attribute_name: str = Field(..., description="Canonical target attribute name or tag key")
    value: Any = Field(default=None, description="Resolved and normalized attribute/tag value")
    raw_instruction: str = Field(..., description="Original raw instruction text provided by user")
    target_resource_type: Optional[str] = Field(
        default=None, description="Target resource type context used during resolution"
    )
    confidence: float = Field(default=1.0, description="Resolution confidence score between 0.0 and 1.0")


class TweakResult(BaseModel):
    """Outcome of applying a parsed tweak to an in-memory workspace."""

    success: bool = Field(..., description="Whether the tweak mutation succeeded")
    parsed_tweak: Optional[ParsedTweak] = Field(default=None, description="The parsed tweak that was applied")
    target_file: str = Field(default="main.tf", description="Relative path of file modified in workspace")
    old_value: Optional[Any] = Field(default=None, description="Previous attribute value if available")
    new_value: Optional[Any] = Field(default=None, description="New attribute value applied")
    elapsed_ms: float = Field(default=0.0, description="Total execution time in milliseconds")
    diff_summary: Optional[str] = Field(default=None, description="Human-readable summary of modification")
    error_message: Optional[str] = Field(default=None, description="Error message if mutation failed")


@runtime_checkable
class TweakParserPort(Protocol):
    """Abstract port for interpreting colloquial or direct tweak instructions."""

    def parse(
        self,
        instruction: str,
        resource_type: Optional[str] = None,
    ) -> ParsedTweak:
        """Parse a tweak instruction string into a structured ParsedTweak.

        Args:
            instruction: User-entered tweak command or phrase (e.g. "Change replication to GRS").
            resource_type: Optional target Azure resource type (e.g. 'azurerm_storage_account').

        Returns:
            ParsedTweak containing action, canonical attribute name, and normalized value.

        Raises:
            TweakParseError: If the instruction cannot be resolved to a valid attribute or action.
        """
        ...
