"""Deterministic, air-gapped tweak parser adapter using rule-based grammar and alias dictionary (AD-1, AD-4)."""

import re
from typing import Any, Optional

from ttassistant.domain.exceptions import TweakParseError
from ttassistant.domain.tweak import (
    normalize_attribute_value,
    resolve_attribute_alias,
)
from ttassistant.ports.catalog import ResourceCatalogPort
from ttassistant.ports.tweak_parser import (
    ParsedTweak,
    TweakAction,
    TweakParserPort,
)


class DeterministicTweakParserAdapter(TweakParserPort):
    """Air-gapped rule-based parser that maps colloquial phrases to canonical AzureRM attributes."""

    def __init__(self, catalog: Optional[ResourceCatalogPort] = None) -> None:
        """Initialize parser adapter with optional catalog for schema validation."""
        self.catalog = catalog

    def parse(
        self,
        instruction: str,
        resource_type: Optional[str] = None,
    ) -> ParsedTweak:
        """Parse colloquial developer tweak instruction into structured ParsedTweak.

        Args:
            instruction: Raw text command or refinement phrase.
            resource_type: Target AzureRM resource type if known.

        Returns:
            ParsedTweak containing action, canonical attribute name, and normalized value.

        Raises:
            TweakParseError: If instruction is empty, malformed, or cannot be resolved.
        """
        if not instruction or not instruction.strip():
            raise TweakParseError("Tweak instruction cannot be empty.")

        text = instruction.strip()

        # 1. Parse tag removal: e.g. "Remove tag ManagedBy", "delete tag team", "drop tag CostCenter"
        m_remove_tag = re.match(
            r"^(?:remove|delete|drop|unset)\s+tag\s+([a-zA-Z0-9_-]+)$",
            text,
            re.IGNORECASE,
        )
        if m_remove_tag:
            tag_key = m_remove_tag.group(1).strip()
            return ParsedTweak(
                action=TweakAction.REMOVE_TAG,
                attribute_name=tag_key,
                value=None,
                raw_instruction=text,
                target_resource_type=resource_type,
            )

        # 2. Parse tag addition / update:
        # "Add tag team=core", "Set tag Environment=staging", "Tag team = core", "tags.team = core"
        m_set_tag = re.match(
            r"^(?:add\s+tag|set\s+tag|tag|tags\.([a-zA-Z0-9_-]+))\s*(?:to|=)?\s*([a-zA-Z0-9_-]+)?\s*=\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        if m_set_tag:
            prefix_key = m_set_tag.group(1)
            mid_key = m_set_tag.group(2)
            raw_val = m_set_tag.group(3).strip()

            tag_key = prefix_key or mid_key
            if tag_key:
                clean_val = raw_val.strip("\"'")
                return ParsedTweak(
                    action=TweakAction.SET_TAG,
                    attribute_name=tag_key,
                    value=clean_val,
                    raw_instruction=text,
                    target_resource_type=resource_type,
                )

        # Alternative tag format: "Add tag team to core"
        m_tag_to = re.match(
            r"^(?:add\s+tag|set\s+tag)\s+([a-zA-Z0-9_-]+)\s+(?:to|=)\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        if m_tag_to:
            tag_key = m_tag_to.group(1).strip()
            clean_val = m_tag_to.group(2).strip().strip("\"'")
            return ParsedTweak(
                action=TweakAction.SET_TAG,
                attribute_name=tag_key,
                value=clean_val,
                raw_instruction=text,
                target_resource_type=resource_type,
            )

        # 3. Parse boolean toggles:
        # "Disable public network access", "deny public access", "enable public access", "allow public network"
        m_toggle_public = re.match(
            r"^(disable|deny|turn off|enable|allow|turn on)\s+(public\s+network(?:\s+access)?|public\s+access)(?:\s+enabled)?$",
            text,
            re.IGNORECASE,
        )
        if m_toggle_public:
            verb = m_toggle_public.group(1).lower()
            enabled = verb in ("enable", "allow", "turn on")
            return ParsedTweak(
                action=TweakAction.TOGGLE_BOOLEAN,
                attribute_name="public_network_access_enabled",
                value=enabled,
                raw_instruction=text,
                target_resource_type=resource_type,
            )

        # Generic boolean toggle: "Enable purge protection", "Disable rbac", "Enable datalake"
        m_toggle_generic = re.match(
            r"^(enable|disable|turn on|turn off|allow|deny)\s+(.*?)$",
            text,
            re.IGNORECASE,
        )
        if m_toggle_generic:
            verb = m_toggle_generic.group(1).lower()
            term = m_toggle_generic.group(2).strip()
            enabled = verb in ("enable", "turn on", "allow")
            try:
                attr = resolve_attribute_alias(term, resource_type=resource_type)
                return ParsedTweak(
                    action=TweakAction.TOGGLE_BOOLEAN,
                    attribute_name=attr,
                    value=enabled,
                    raw_instruction=text,
                    target_resource_type=resource_type,
                )
            except TweakParseError:
                pass

        # 4. Standard attribute assignment or colloquial change
        # "Set minimum TLS version to 1.2", "Change replication to GRS", "account_replication_type = GRS"
        m_assign = re.match(
            r"^(?:set|change|update|configure|switch|modify)?\s*(?:the\s+)?(.*?)\s*(?:to|=)\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        if m_assign:
            raw_attr = m_assign.group(1).strip()
            raw_val = m_assign.group(2).strip()

            if not raw_attr:
                raise TweakParseError(f"Could not extract attribute name from instruction: '{text}'")

            # Check if this is a tag assignment: e.g. "team = core" when user typed without "tag" keyword?
            # No, keep attributes as attributes unless explicitly tags.

            canonical_attr = resolve_attribute_alias(raw_attr, resource_type=resource_type)

            # If catalog is available, validate against resource schema
            if self.catalog and resource_type:
                schema = self.catalog.get_resource_schema(resource_type)
                if schema and canonical_attr not in schema.arguments and canonical_attr != "tags":
                    # Check if it was a known global alias that might not apply to this resource
                    raise TweakParseError(
                        f"Attribute '{canonical_attr}' (from '{raw_attr}') is not a valid argument for '{resource_type}'."
                    )

            normalized_val = normalize_attribute_value(
                canonical_attr, raw_val, resource_type=resource_type
            )

            action = (
                TweakAction.TOGGLE_BOOLEAN
                if isinstance(normalized_val, bool)
                else TweakAction.SET_ATTRIBUTE
            )

            return ParsedTweak(
                action=action,
                attribute_name=canonical_attr,
                value=normalized_val,
                raw_instruction=text,
                target_resource_type=resource_type,
            )

        raise TweakParseError(
            f"Could not parse tweak instruction: '{text}'. "
            "Supported formats include: 'Set <attribute> to <value>', 'Change <attribute> to <value>', "
            "'Add tag <key>=<value>', or 'Disable/Enable <feature>'."
        )
