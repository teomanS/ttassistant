"""Domain exceptions for ttassistant."""


class TTAssistantError(Exception):
    """Base exception for all ttassistant errors."""

    def __init__(self, message: str, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class SecurityPolicyViolationError(TTAssistantError):
    """Raised when an operation violates corporate infrastructure security policy."""
    pass


class StandardsError(TTAssistantError):
    """Base exception for standards validation and loading errors."""
    pass


class MissingStandardsError(StandardsError):
    """Raised when common_standards directory or required standard files are missing or empty."""
    pass


class InvalidStandardsError(StandardsError):
    """Raised when standards specification files are malformed or fail schema validation."""
    pass


class FileSystemError(TTAssistantError):
    """Raised when filesystem operations or atomic workspace commitments fail."""
    pass


class CatalogError(TTAssistantError):
    """Base exception for provider schema catalog errors."""
    pass


class MissingCatalogError(CatalogError):
    """Raised when the offline schema catalog file is missing or cannot be located."""
    pass


class InvalidCatalogError(CatalogError):
    """Raised when the offline schema catalog file contains invalid or corrupt JSON."""
    pass


class ResourceNotFoundError(CatalogError):
    """Raised when a requested resource is not present in the catalog."""
    pass


class TweakError(TTAssistantError):
    """Base exception for in-session tweak engine errors."""
    pass


class TweakParseError(TweakError):
    """Raised when a colloquial tweak instruction cannot be parsed or resolved to a known attribute."""
    pass


class UnsupportedTweakError(TweakError):
    """Raised when an operation requested by a tweak is not supported for the target resource."""
    pass

