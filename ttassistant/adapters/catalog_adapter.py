"""Concrete adapter for loading and querying the bundled offline AzureRM schema catalog."""

import importlib.resources
import json
from pathlib import Path
from typing import Any, Optional, Union

from ttassistant.domain.catalog import (
    CatalogSummary,
    ResourceArgumentSchema,
    ResourceSchema,
    ResourceTier,
    is_tier_1_resource,
)
from ttassistant.domain.exceptions import (
    InvalidCatalogError,
    MissingCatalogError,
)
from ttassistant.ports.catalog import ResourceCatalogPort


class JsonResourceCatalogAdapter(ResourceCatalogPort):
    """Concrete catalog adapter reading from bundled offline azurerm_schema.json."""

    def __init__(
        self,
        catalog_path: Optional[Union[Path, str]] = None,
        auto_load: bool = True,
    ) -> None:
        """Initialize the JSON resource catalog adapter.

        Args:
            catalog_path: Optional explicit path to catalog JSON file. If None, bundled resource is used.
            auto_load: Whether to load and index the catalog immediately upon initialization.
        """
        self._custom_path: Optional[Path] = Path(catalog_path).resolve() if catalog_path else None
        self._provider_version: Optional[str] = None
        self._schemas: dict[str, ResourceSchema] = {}
        self._loaded: bool = False

        if auto_load:
            self.load()

    def _resolve_catalog_path(self) -> Path:
        """Locate the catalog JSON file either from custom path, package resource, or local filesystem."""
        if self._custom_path is not None:
            return self._custom_path

        # Try importlib.resources
        try:
            package_data = importlib.resources.files("ttassistant.data")
            schema_file = package_data.joinpath("azurerm_schema.json")
            # In Python 3.11+, Traversable may not be a direct Path instance
            resolved_path = Path(str(schema_file))
            if resolved_path.is_file():
                return resolved_path
        except Exception:
            pass

        # Fallback to relative file path
        fallback = Path(__file__).resolve().parent.parent / "data" / "azurerm_schema.json"
        return fallback

    def load(self) -> None:
        """Load and parse the offline AzureRM catalog JSON into indexed domain models."""
        target_path = self._resolve_catalog_path()

        if not target_path.exists() or not target_path.is_file():
            raise MissingCatalogError(
                f"AzureRM schema catalog file not found at '{target_path}'.",
                details="Verify package data installation or specify a valid catalog_path.",
            )

        try:
            raw_text = target_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise InvalidCatalogError(
                f"Corrupt or malformed AzureRM schema catalog file at '{target_path}': {exc}",
                details="The catalog JSON contains invalid syntax or is corrupted.",
            ) from exc
        except Exception as exc:
            raise InvalidCatalogError(
                f"Failed to read AzureRM schema catalog at '{target_path}': {exc}",
                details=str(exc),
            ) from exc

        if not isinstance(data, dict) or "resources" not in data or not isinstance(data["resources"], dict):
            raise InvalidCatalogError(
                f"Invalid catalog structure in '{target_path}': root must be a dict containing 'resources' dict.",
                details="Expected top-level keys 'resources' and optional 'provider_version'.",
            )

        self._provider_version = data.get("provider_version")
        raw_resources = data["resources"]

        indexed_schemas: dict[str, ResourceSchema] = {}
        for res_type, res_data in raw_resources.items():
            if not isinstance(res_data, dict):
                raise InvalidCatalogError(
                    f"Invalid resource schema in '{target_path}': resource '{res_type}' must be an object.",
                    details="Each resource entry must be a dictionary.",
                )

            tier = ResourceTier.TIER_1 if is_tier_1_resource(res_type) else ResourceTier.TIER_2
            description = res_data.get("description", "")
            raw_arguments = res_data.get("arguments")
            if not isinstance(raw_arguments, dict):
                raise InvalidCatalogError(
                    f"Invalid arguments for resource '{res_type}' in '{target_path}': 'arguments' must be a dictionary.",
                    details="Expected 'arguments' to be a dict of argument specifications.",
                )

            args_map: dict[str, ResourceArgumentSchema] = {}
            for arg_name, arg_data in raw_arguments.items():
                if not isinstance(arg_data, dict):
                    raise InvalidCatalogError(
                        f"Invalid argument specification for '{res_type}.{arg_name}' in '{target_path}': must be an object.",
                        details="Expected argument entry to be a dictionary.",
                    )
                req = bool(arg_data.get("required", False))
                opt = bool(arg_data.get("optional", not req))
                args_map[arg_name] = ResourceArgumentSchema(
                    name=arg_name,
                    type=arg_data.get("type", "string"),
                    description=arg_data.get("description", ""),
                    required=req,
                    optional=opt,
                    computed=bool(arg_data.get("computed", False)),
                    default=arg_data.get("default"),
                    sensitive=bool(arg_data.get("sensitive", False)),
                    forces_new=bool(arg_data.get("forces_new", False)),
                )

            indexed_schemas[res_type.lower()] = ResourceSchema(
                resource_type=res_type,
                tier=tier,
                description=description,
                arguments=args_map,
            )

        self._schemas = indexed_schemas
        self._loaded = True

    def reload(self) -> None:
        """Force reload of the catalog from disk."""
        self._schemas.clear()
        self._loaded = False
        self.load()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get_resource_schema(self, resource_type: str) -> Optional[ResourceSchema]:
        """Retrieve schema definition for an AzureRM resource type, or None if unknown."""
        if not resource_type:
            return None
        self._ensure_loaded()
        return self._schemas.get(resource_type.strip().lower())

    def is_known_resource(self, resource_type: str) -> bool:
        """Check whether a resource type exists in the catalog."""
        if not resource_type:
            return False
        self._ensure_loaded()
        return resource_type.strip().lower() in self._schemas

    def is_tier_1(self, resource_type: str) -> bool:
        """Check whether a resource type is classified as Tier 1."""
        if not resource_type:
            return False
        return is_tier_1_resource(resource_type)

    def is_tier_2(self, resource_type: str) -> bool:
        """Check whether a resource type is classified as Tier 2."""
        if not resource_type:
            return False
        return self.is_known_resource(resource_type) and not is_tier_1_resource(resource_type)

    def list_resources(
        self,
        filter_prefix: Optional[str] = None,
        tier: Optional[Union[ResourceTier, int, str]] = None,
    ) -> list[str]:
        """List resource types matching optional filter prefix and tier."""
        self._ensure_loaded()
        target_tier: Optional[ResourceTier] = None
        if tier is not None:
            try:
                target_tier = ResourceTier(tier)
            except (ValueError, TypeError):
                return []

        prefix = filter_prefix.strip().lower() if filter_prefix else None

        results: list[str] = []
        for key, schema in self._schemas.items():
            if target_tier is not None and schema.tier != target_tier:
                continue
            if prefix is not None and not key.startswith(prefix):
                continue
            results.append(schema.resource_type)

        results.sort()
        return results

    def search(self, query: str) -> list[str]:
        """Search for resources where type name or description matches query substring."""
        if not query or not query.strip():
            return self.list_resources()
        self._ensure_loaded()
        q = query.strip().lower()
        matches = [
            schema.resource_type
            for schema in self._schemas.values()
            if q in schema.resource_type.lower() or q in schema.description.lower()
        ]
        matches.sort()
        return matches

    def get_required_arguments(self, resource_type: str) -> list[str]:
        """Retrieve required argument names for a resource type."""
        schema = self.get_resource_schema(resource_type)
        if schema is None:
            return []
        return schema.required_argument_names

    def get_optional_arguments(self, resource_type: str) -> list[str]:
        """Retrieve optional argument names for a resource type."""
        schema = self.get_resource_schema(resource_type)
        if schema is None:
            return []
        return schema.optional_argument_names

    def get_summary(self) -> CatalogSummary:
        """Retrieve summary statistics of the catalog."""
        self._ensure_loaded()
        all_types = sorted(self._schemas.keys())
        tier_1 = sum(1 for s in self._schemas.values() if s.is_tier_1)
        tier_2 = len(self._schemas) - tier_1

        return CatalogSummary(
            total_resources=len(self._schemas),
            tier_1_count=tier_1,
            tier_2_count=tier_2,
            provider_version=self._provider_version,
            resource_types=all_types,
        )
