"""Markdown and YAML standards source adapter using markdown-it-py and PyYAML."""

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from markdown_it import MarkdownIt
from pydantic import ValidationError

from ttassistant.domain.exceptions import (
    InvalidStandardsError,
    MissingStandardsError,
)
from ttassistant.domain.models import (
    BackendMappingRule,
    NamingRule,
    NetworkingPolicyRule,
    StandardsBundle,
    TagRule,
)
from ttassistant.ports.standards_source import StandardsSourcePort

REQUIRED_STANDARD_FILES = [
    "naming_conventions.md",
    "tagging_baseline.md",
    "backend_mapping.md",
]


class MarkdownStandardsAdapter(StandardsSourcePort):
    """Concrete adapter loading corporate standards from Markdown and YAML specification files."""

    def __init__(self) -> None:
        self._md = MarkdownIt().enable("table")

    def load_standards(self, directory: Path) -> StandardsBundle:
        """Load and parse standards specifications from the given directory.

        Args:
            directory: Path to standards directory.

        Returns:
            Populated StandardsBundle domain object.

        Raises:
            MissingStandardsError: If directory does not exist, is empty, or required files are missing.
            InvalidStandardsError: If standards files are malformed or fail schema validation.
        """
        dir_path = Path(directory).resolve()

        if not dir_path.exists():
            raise MissingStandardsError(
                f"Standards directory not found: '{dir_path}'",
                details="Please ensure 'common_standards/' exists or specify a valid path with --standards-dir.",
            )

        if not dir_path.is_dir():
            raise MissingStandardsError(
                f"Standards path is not a directory: '{dir_path}'",
                details="Expected a directory containing corporate standards markdown files.",
            )

        md_files = list(dir_path.glob("*.md"))
        if not md_files:
            raise MissingStandardsError(
                f"Standards directory '{dir_path}' is empty.",
                details="No markdown specification files (.md) were found in the standards directory.",
            )

        # Check required files
        for req_name in REQUIRED_STANDARD_FILES:
            req_file = dir_path / req_name
            if not req_file.is_file():
                raise MissingStandardsError(
                    f"Missing required standard file: '{req_name}' in '{dir_path}'",
                    details=f"The standards directory must contain '{req_name}'.",
                )

        combined_metadata: dict[str, Any] = {}

        # 1. Parse naming_conventions.md
        naming_file = dir_path / "naming_conventions.md"
        naming_meta, naming_rules = self._parse_naming_conventions(naming_file)
        combined_metadata["naming_conventions"] = naming_meta

        # 2. Parse tagging_baseline.md
        tagging_file = dir_path / "tagging_baseline.md"
        tagging_meta, tag_rules = self._parse_tagging_baseline(tagging_file)
        combined_metadata["tagging_baseline"] = tagging_meta

        # 3. Parse backend_mapping.md
        backend_file = dir_path / "backend_mapping.md"
        backend_meta, backend_rules = self._parse_backend_mapping(backend_file)
        combined_metadata["backend_mapping"] = backend_meta

        # 4. Parse networking_policy.md (optional)
        networking_rules: dict[str, NetworkingPolicyRule] = {}
        networking_file = dir_path / "networking_policy.md"
        if networking_file.is_file():
            net_meta, networking_rules = self._parse_networking_policy(networking_file)
            combined_metadata["networking_policy"] = net_meta

        return StandardsBundle(
            naming_rules=naming_rules,
            tag_rules=tag_rules,
            backend_rules=backend_rules,
            networking_rules=networking_rules,
            metadata=combined_metadata,
        )

    def _parse_frontmatter_and_body(
        self, file_path: Path
    ) -> tuple[dict[str, Any], str]:
        """Extract optional YAML frontmatter and markdown body from file."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise InvalidStandardsError(
                f"Failed to read standards file '{file_path}': {exc}"
            ) from exc

        content = content.lstrip("\ufeff")

        if not content.strip():
            raise InvalidStandardsError(
                f"Standards file '{file_path}' is empty.",
                details="The file must contain markdown tables or specifications.",
            )

        if content.startswith("---"):
            # Look for closing delimiter on its own line
            pattern = re.compile(r"^---\s*$", re.MULTILINE)
            matches = list(pattern.finditer(content))
            if len(matches) < 2:
                raise InvalidStandardsError(
                    f"Malformed YAML frontmatter in '{file_path}': unclosed '---' delimiter",
                    details="Frontmatter started with '---' but no closing '---' was found.",
                )

            fm_start = matches[0].end()
            fm_end = matches[1].start()
            yaml_text = content[fm_start:fm_end]
            body = content[matches[1].end() :]

            try:
                metadata = yaml.safe_load(yaml_text) or {}
            except yaml.YAMLError as exc:
                raise InvalidStandardsError(
                    f"Malformed YAML frontmatter in '{file_path}': {exc}",
                    details=str(exc),
                ) from exc

            if not isinstance(metadata, dict):
                raise InvalidStandardsError(
                    f"Malformed YAML frontmatter in '{file_path}': expected mapping, got {type(metadata).__name__}",
                    details="Frontmatter must be a YAML dictionary of key-value pairs.",
                )

            return metadata, body

        return {}, content

    def _extract_tables(
        self, markdown_text: str, file_path: Path
    ) -> list[tuple[list[str], list[list[str]]]]:
        """Extract all markdown tables as (headers, rows) tuples using markdown-it-py AST traversal.

        Performs syntax integrity checks on table structure.
        """
        # Check raw markdown for obviously corrupted table rows
        lines = markdown_text.splitlines()
        in_table_block = False
        header_pipe_count = 0
        for line_num, line in enumerate(lines, start=1):
            sline = line.strip()
            if sline.startswith("|") and sline.endswith("|"):
                # Delimiter line |---|---|
                if re.match(r"^\|(\s*:?-+:?\s*\|)+$", sline):
                    continue
                # Normalize line for pipe counting: ignore escaped pipes \| and pipes inside code spans `...`
                clean_line = re.sub(r"\\\|", "", sline)
                clean_line = re.sub(r"`[^`]*`", "", clean_line)
                pipes = clean_line.count("|")
                if not in_table_block:
                    in_table_block = True
                    header_pipe_count = pipes
                else:
                    if pipes != header_pipe_count:
                        raise InvalidStandardsError(
                            f"Malformed Markdown table in '{file_path}': corrupted column count on line {line_num}",
                            details=f"Header row has {header_pipe_count - 1} columns, but line {line_num} has {pipes - 1} columns: '{sline}'",
                        )
            else:
                in_table_block = False
                header_pipe_count = 0

        tokens = self._md.parse(markdown_text)
        tables: list[tuple[list[str], list[list[str]]]] = []

        headers: list[str] = []
        rows: list[list[str]] = []
        current_row: list[str] = []
        in_cell = False
        cell_content = ""
        in_thead = False

        for t in tokens:
            if t.type == "table_open":
                headers = []
                rows = []
            elif t.type == "thead_open":
                in_thead = True
            elif t.type == "thead_close":
                in_thead = False
            elif t.type in ("th_open", "td_open"):
                in_cell = True
                cell_content = ""
            elif t.type in ("th_close", "td_close"):
                in_cell = False
                current_row.append(cell_content.strip())
            elif in_cell and t.type == "inline":
                if t.children:
                    reconstructed = ""
                    for c in t.children:
                        if c.type in ("em_open", "em_close", "strong_open", "strong_close"):
                            reconstructed += c.markup
                        elif c.content:
                            reconstructed += c.content
                    cell_content = reconstructed
                else:
                    cell_content = t.content
            elif t.type == "tr_open":
                current_row = []
            elif t.type == "tr_close":
                if in_thead:
                    headers = current_row
                else:
                    if current_row:
                        rows.append(current_row)
            elif t.type == "table_close":
                if headers:
                    tables.append((headers, rows))

        return tables

    def _normalize_header(self, header: str) -> str:
        """Normalize header string to lowercase snake_case."""
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", header.strip().lower())
        return cleaned.strip("_")

    def _parse_naming_conventions(
        self, file_path: Path
    ) -> tuple[dict[str, Any], dict[str, NamingRule]]:
        """Parse naming_conventions.md into NamingRule dictionary."""
        metadata, body = self._parse_frontmatter_and_body(file_path)
        tables = self._extract_tables(body, file_path)

        if not tables:
            raise InvalidStandardsError(
                f"Malformed Markdown table in '{file_path}': no table found",
                details="File must contain a markdown table specifying naming conventions.",
            )

        headers, rows = tables[0]
        norm_headers = [self._normalize_header(h) for h in headers]

        # Expected headers mapping
        res_idx = self._find_col_index(
            norm_headers, ["resource_type", "type", "resource"]
        )
        pattern_idx = self._find_col_index(
            norm_headers, ["naming_pattern", "pattern"]
        )
        chars_idx = self._find_col_index(
            norm_headers, ["allowed_characters", "characters", "allowed"]
        )
        length_idx = self._find_col_index(
            norm_headers, ["max_length", "length", "max"]
        )
        min_length_idx = self._find_col_index(
            norm_headers, ["min_length", "min"]
        )

        missing = []
        if res_idx is None:
            missing.append("Resource Type")
        if pattern_idx is None:
            missing.append("Naming Pattern")
        if length_idx is None:
            missing.append("Max Length")

        if missing:
            raise InvalidStandardsError(
                f"Malformed Markdown table in '{file_path}': missing required headers [{', '.join(missing)}]",
                details=f"Found headers: {headers}. Expected: Resource Type, Naming Pattern, Allowed Characters, Max Length.",
            )

        if not rows:
            raise InvalidStandardsError(
                f"Malformed Markdown table in '{file_path}': table is empty",
                details="The naming conventions table contains no rule entries.",
            )

        rules: dict[str, NamingRule] = {}
        for row_idx, row in enumerate(rows, start=1):
            if len(row) != len(headers):
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': row {row_idx} column count mismatch",
                    details=f"Expected {len(headers)} columns, got {len(row)}: {row}",
                )

            res_type = row[res_idx].strip()
            pattern = row[pattern_idx].strip()
            chars = row[chars_idx].strip() if chars_idx is not None else ""
            max_len_str = row[length_idx].strip()

            if not res_type:
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': row {row_idx} has empty Resource Type",
                    details=f"Row contents: {row}",
                )

            if not pattern:
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': row {row_idx} has empty Naming Pattern",
                    details=f"Row contents: {row}",
                )

            try:
                max_len = int(max_len_str)
            except ValueError:
                raise InvalidStandardsError(
                    f"Pydantic schema validation error in '{file_path}': invalid integer for 'Max Length': '{max_len_str}'",
                    details=f"Field 'max_length' must be an integer, got '{max_len_str}' for resource '{res_type}'.",
                )

            min_len = 1
            if min_length_idx is not None and row[min_length_idx].strip():
                min_len_str = row[min_length_idx].strip()
                try:
                    min_len = int(min_len_str)
                except ValueError:
                    raise InvalidStandardsError(
                        f"Pydantic schema validation error in '{file_path}': invalid integer for 'Min Length': '{min_len_str}'",
                        details=f"Field 'min_length' must be an integer, got '{min_len_str}' for resource '{res_type}'.",
                    )

            try:
                rule = NamingRule(
                    resource_type=res_type,
                    pattern=pattern,
                    allowed_characters=chars,
                    max_length=max_len,
                    min_length=min_len,
                )
            except (ValidationError, ValueError) as exc:
                raise InvalidStandardsError(
                    f"Pydantic schema validation error in '{file_path}': {exc}",
                    details=str(exc),
                ) from exc

            rules[res_type] = rule

        return metadata, rules

    def _parse_tagging_baseline(
        self, file_path: Path
    ) -> tuple[dict[str, Any], dict[str, TagRule]]:
        """Parse tagging_baseline.md into TagRule dictionary from table or bullet list."""
        metadata, body = self._parse_frontmatter_and_body(file_path)
        tables = self._extract_tables(body, file_path)
        rules: dict[str, TagRule] = {}

        if tables:
            headers, rows = tables[0]
            norm_headers = [self._normalize_header(h) for h in headers]

            key_idx = self._find_col_index(
                norm_headers, ["tag_key", "tag_name", "key", "name", "tag"]
            )
            req_idx = self._find_col_index(
                norm_headers, ["required", "mandatory"]
            )
            allowed_idx = self._find_col_index(
                norm_headers, ["allowed_values", "allowed", "values"]
            )
            default_idx = self._find_col_index(
                norm_headers, ["default_value", "default"]
            )
            desc_idx = self._find_col_index(
                norm_headers, ["description", "purpose", "desc"]
            )

            if key_idx is None:
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': missing required 'Tag Key' header",
                    details=f"Found headers: {headers}",
                )

            for row_idx, row in enumerate(rows, start=1):
                if len(row) != len(headers):
                    raise InvalidStandardsError(
                        f"Malformed Markdown table in '{file_path}': row {row_idx} column count mismatch",
                        details=f"Expected {len(headers)} columns, got {len(row)}: {row}",
                    )

                key = row[key_idx].strip()
                if not key:
                    continue

                req_str = row[req_idx].strip().lower() if req_idx is not None else "true"
                required = req_str in ("yes", "true", "1", "mandatory", "required")

                allowed_vals: list[str] = []
                if allowed_idx is not None and row[allowed_idx].strip():
                    raw_allowed = row[allowed_idx].strip()
                    if raw_allowed not in ("-", "none", "any", "n/a"):
                        parts = re.split(r"[,|;]", raw_allowed)
                        allowed_vals = [p.strip() for p in parts if p.strip()]

                default_val: Optional[str] = None
                if default_idx is not None and row[default_idx].strip():
                    raw_default = row[default_idx].strip()
                    if raw_default not in ("-", "none", "n/a"):
                        default_val = raw_default

                desc: Optional[str] = None
                if desc_idx is not None and row[desc_idx].strip():
                    desc = row[desc_idx].strip()

                try:
                    rule = TagRule(
                        key=key,
                        required=required,
                        allowed_values=allowed_vals,
                        default_value=default_val,
                        description=desc,
                    )
                except ValidationError as exc:
                    raise InvalidStandardsError(
                        f"Pydantic schema validation error in '{file_path}': {exc}",
                        details=str(exc),
                    ) from exc

                rules[key] = rule

        # If no table rules found, try parsing bullet lists
        if not rules:
            tokens = self._md.parse(body)
            for t in tokens:
                if t.type == "inline":
                    line = t.content.strip()
                    # e.g.: - `Environment` (Required): Allowed values: dev, test, prod. Default: dev.
                    match = re.match(
                        r"^(?:-\s*)?`?([A-Za-z0-9_-]+)`?\s*(?:\((Required|Mandatory|Optional)\))?:?\s*(.*)$",
                        line,
                        re.IGNORECASE,
                    )
                    if match:
                        key = match.group(1)
                        req_str = (match.group(2) or "Required").lower()
                        required = req_str in ("required", "mandatory")
                        rest = match.group(3) or ""

                        allowed_vals = []
                        allowed_match = re.search(
                            r"Allowed(?:\s+values)?:?\s*([^.]+)", rest, re.IGNORECASE
                        )
                        if allowed_match:
                            allowed_vals = [
                                p.strip()
                                for p in re.split(r"[,|;]", allowed_match.group(1))
                                if p.strip()
                            ]

                        default_val = None
                        default_match = re.search(
                            r"Default:?\s*([^\s.]+)", rest, re.IGNORECASE
                        )
                        if default_match:
                            default_val = default_match.group(1).strip()

                        try:
                            rule = TagRule(
                                key=key,
                                required=required,
                                allowed_values=allowed_vals,
                                default_value=default_val,
                                description=rest.strip() or None,
                            )
                            rules[key] = rule
                        except ValidationError:
                            pass

        if not rules:
            raise InvalidStandardsError(
                f"No valid tag rules found in '{file_path}'",
                details="File must contain a table or bullet list specifying tag baseline rules.",
            )

        return metadata, rules

    def _parse_backend_mapping(
        self, file_path: Path
    ) -> tuple[dict[str, Any], list[BackendMappingRule]]:
        """Parse backend_mapping.md into list of BackendMappingRule."""
        metadata, body = self._parse_frontmatter_and_body(file_path)
        tables = self._extract_tables(body, file_path)
        rules: list[BackendMappingRule] = []

        if tables:
            headers, rows = tables[0]
            norm_headers = [self._normalize_header(h) for h in headers]

            sub_idx = self._find_col_index(
                norm_headers, ["subscription", "subscription_id", "environment"]
            )
            sa_idx = self._find_col_index(
                norm_headers, ["storage_account", "storage_account_name"]
            )
            cnt_idx = self._find_col_index(
                norm_headers, ["container", "container_name"]
            )
            key_idx = self._find_col_index(
                norm_headers, ["key_pattern", "key"]
            )
            rg_idx = self._find_col_index(
                norm_headers, ["resource_group", "resource_group_name"]
            )

            missing = []
            if sub_idx is None:
                missing.append("Subscription")
            if sa_idx is None:
                missing.append("Storage Account")

            if missing:
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': missing required headers [{', '.join(missing)}]",
                    details=f"Found headers: {headers}. Expected Subscription, Storage Account, Container, Key Pattern.",
                )

            for row_idx, row in enumerate(rows, start=1):
                if len(row) != len(headers):
                    raise InvalidStandardsError(
                        f"Malformed Markdown table in '{file_path}': row {row_idx} column count mismatch",
                        details=f"Expected {len(headers)} columns, got {len(row)}: {row}",
                    )

                sub = row[sub_idx].strip()
                sa = row[sa_idx].strip()
                container = (
                    row[cnt_idx].strip()
                    if cnt_idx is not None and row[cnt_idx].strip()
                    else metadata.get("default_container", "tfstate")
                )
                key_pattern = (
                    row[key_idx].strip()
                    if key_idx is not None and row[key_idx].strip()
                    else metadata.get(
                        "default_key_pattern", "{subscription}/{resource_type}.tfstate"
                    )
                )
                rg = row[rg_idx].strip() if rg_idx is not None and row[rg_idx].strip() else None

                if not sub or not sa:
                    raise InvalidStandardsError(
                        f"Malformed Markdown table in '{file_path}': row {row_idx} missing subscription or storage account",
                        details=f"Row contents: {row}",
                    )

                try:
                    rule = BackendMappingRule(
                        subscription=sub,
                        storage_account_name=sa,
                        container_name=container,
                        key_pattern=key_pattern,
                        resource_group_name=rg,
                    )
                except ValidationError as exc:
                    raise InvalidStandardsError(
                        f"Pydantic schema validation error in '{file_path}': {exc}",
                        details=str(exc),
                    ) from exc

                rules.append(rule)

        if not rules:
            raise InvalidStandardsError(
                f"No backend mapping rules found in '{file_path}'",
                details="File must contain a markdown table specifying remote state backend mappings.",
            )

        return metadata, rules

    def _parse_networking_policy(
        self, file_path: Path
    ) -> tuple[dict[str, Any], dict[str, NetworkingPolicyRule]]:
        """Parse networking_policy.md into NetworkingPolicyRule dictionary."""
        metadata, body = self._parse_frontmatter_and_body(file_path)
        tables = self._extract_tables(body, file_path)
        rules: dict[str, NetworkingPolicyRule] = {}

        if not tables:
            raise InvalidStandardsError(
                f"Malformed Markdown table in '{file_path}': no table found",
                details="File must contain a markdown table specifying networking policy.",
            )

        headers, rows = tables[0]
        norm_headers = [self._normalize_header(h) for h in headers]

        res_idx = self._find_col_index(
            norm_headers, ["resource_type", "service", "type"]
        )
        dns_id_idx = self._find_col_index(
            norm_headers, ["private_dns_zone_id", "dns_zone_id", "zone_id"]
        )
        dns_name_idx = self._find_col_index(
            norm_headers, ["private_dns_zone_name", "private_dns_zone", "zone_name"]
        )
        subnet_idx = self._find_col_index(
            norm_headers, ["subnet_patterns", "subnets", "candidate_subnets"]
        )
        public_idx = self._find_col_index(
            norm_headers, ["allow_public_access", "public_access"]
        )

        if res_idx is None:
            raise InvalidStandardsError(
                f"Malformed Markdown table in '{file_path}': missing required 'Resource Type' header",
                details=f"Found headers: {headers}. Expected 'Resource Type'.",
            )

        if not rows:
            raise InvalidStandardsError(
                f"Malformed Markdown table in '{file_path}': table is empty",
                details="The networking policy table contains no data rows.",
            )

        for row_idx, row in enumerate(rows, start=1):
            if len(row) != len(headers):
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': row {row_idx} column count mismatch",
                    details=f"Expected {len(headers)} columns, got {len(row)}: {row}",
                )

            res_type = row[res_idx].strip()
            if not res_type:
                raise InvalidStandardsError(
                    f"Malformed Markdown table in '{file_path}': row {row_idx} has empty Resource Type",
                    details=f"Row contents: {row}",
                )

            dns_id = (
                row[dns_id_idx].strip()
                if dns_id_idx is not None and row[dns_id_idx].strip()
                else None
            )
            dns_name = (
                row[dns_name_idx].strip()
                if dns_name_idx is not None and row[dns_name_idx].strip()
                else None
            )

            subnets: list[str] = []
            if subnet_idx is not None and row[subnet_idx].strip():
                subnets = [
                    s.strip()
                    for s in re.split(r"[,|;]", row[subnet_idx].strip())
                    if s.strip()
                ]

            allow_pub = False
            if public_idx is not None and row[public_idx].strip():
                pub_str = row[public_idx].strip().lower()
                allow_pub = pub_str in ("true", "yes", "1")

            try:
                rule = NetworkingPolicyRule(
                    resource_type=res_type,
                    private_dns_zone_id=dns_id,
                    private_dns_zone_name=dns_name,
                    subnet_patterns=subnets,
                    allow_public_access=allow_pub,
                )
            except (ValidationError, ValueError) as exc:
                raise InvalidStandardsError(
                    f"Pydantic schema validation error in '{file_path}': {exc}",
                    details=str(exc),
                ) from exc

            rules[res_type] = rule

        return metadata, rules

    def _find_col_index(
        self, norm_headers: list[str], candidates: list[str]
    ) -> Optional[int]:
        """Find the index of the first matching candidate header name."""
        for candidate in candidates:
            cand_norm = self._normalize_header(candidate)
            for idx, h in enumerate(norm_headers):
                if h == cand_norm:
                    return idx
        return None
