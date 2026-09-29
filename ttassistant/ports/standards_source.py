"""StandardsSourcePort protocol defining standards loader contract."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ttassistant.domain.models import StandardsBundle


@runtime_checkable
class StandardsSourcePort(Protocol):
    """Abstract port defining interface for loading standards specifications."""

    def load_standards(self, directory: Path) -> StandardsBundle:
        """Load and parse standards specifications from the given directory into a StandardsBundle.

        Args:
            directory: Directory containing corporate standards Markdown files.

        Returns:
            StandardsBundle containing strongly-typed domain rules.

        Raises:
            MissingStandardsError: If directory does not exist, is empty, or required files are missing.
            InvalidStandardsError: If standards files contain syntax or schema errors.
        """
        ...
