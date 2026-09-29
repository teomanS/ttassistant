---
title: 'Story 1.2: Dynamic Markdown Standards Engine & Fail-Fast Policy'
type: 'feature'
created: '2026-09-22'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md'
  - '_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Infrastructure teams suffer from configuration drift and non-compliant Terraform deployments when corporate naming conventions, tagging baselines, and remote state backend mappings are hardcoded or manually maintained across monorepo subscriptions.

**Approach:** Implement a dynamic Standards Engine in `ttassistant` that discovers and ingests Markdown specification files (`common_standards/*.md`) at startup using `markdown-it-py` and `PyYAML`, parses them into strongly-typed Pydantic domain models, validates compliance with instant feedback, and enforces a strict fail-fast policy (exit code 1) when standards are missing, empty, or syntactically invalid.

## Boundaries & Constraints

**Always:**
- Keep pure business domain packages (`ttassistant.domain.standards`, `ttassistant.domain.models`) strictly free of terminal UI (`rich`, `questionary`, `typer`) and direct filesystem I/O dependencies (AD-1).
- Define `StandardsSourcePort` abstract protocol in `ttassistant.ports.standards_source` to decouple standards parsing from physical disk reads.
- Implement `MarkdownStandardsAdapter` in `ttassistant.adapters.standards_adapter` using `markdown-it-py` (for CommonMark tables/lists) and `PyYAML` (for YAML frontmatter).
- Terminate with exit code 1 and actionable error message when `common_standards/` directory is missing, empty, or contains invalid syntax.
- Support runtime discovery of standards by searching from current directory up to repository root, with `--standards-dir` option and `TT_STANDARDS_DIR` environment variable override for testing and flexible workspaces.
- Ensure standards engine initialization and parsing overhead remains <= 200ms to preserve the <= 1.5s cold boot budget.

**Never:**
- Never import UI packages or adapter packages inside `ttassistant.domain`.
- Never execute external CLI binaries (`terraform`, `az`, `git`) to retrieve or validate standards.
- Never silently ignore missing or corrupted standards files; fail-fast is mandatory.
- Never write or modify files in `common_standards/` during CLI execution; standards are strictly read-only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Valid standards directory | `common_standards/` with valid Markdown tables and frontmatter | Strongly-typed `StandardsBundle` domain object populated in memory | N/A |
| Missing standards directory | `common_standards/` not found in workspace or ancestor paths | Exit code 1, error message pointing user to pull corporate standards | `TTAssistantError` caught by CLI, friendly banner printed to stderr |
| Empty standards directory | `common_standards/` exists but contains zero `.md` files | Exit code 1, error message indicating standards folder is empty | `TTAssistantError` caught by CLI |
| Missing required standard file | Directory missing `naming_conventions.md`, `tagging_baseline.md`, or `backend_mapping.md` | Exit code 1, error message indicating specific missing standard file | `TTAssistantError` caught by CLI |
| Malformed Markdown table | `naming_conventions.md` has missing headers or corrupted columns | Exit code 1, diagnostic message identifying file, table, and parse error | `TTAssistantError` with file path & syntax details |
| Pydantic schema validation error | Invalid integer for `Max Length` or invalid regex in naming pattern | Exit code 1, validation error message showing field name and expected type | `TTAssistantError` with Pydantic error details |
| Dynamic updates reflected | User adds a new mandatory tag to `tagging_baseline.md` | Next CLI invocation validates new tag without code changes or rebuilds | N/A |
| CLI `--standards-dir` flag | `ttassistant --standards-dir /custom/path ...` | Engine loads standards from specified custom path | If custom path invalid, exit code 1 with path error |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/models.py` -- Strongly-typed Pydantic domain models: `NamingRule`, `TagRule`, `BackendMappingRule`, `NetworkingPolicyRule`, `StandardsBundle`.
- `ttassistant/domain/standards.py` -- Pure business logic `StandardsEngine` verifying resource names against patterns/lengths, validating tag dictionaries against mandatory rules, and resolving backend configurations.
- `ttassistant/ports/standards_source.py` -- Abstract `StandardsSourcePort` Protocol defining `load_standards(directory: Path) -> StandardsBundle`.
- `ttassistant/adapters/standards_adapter.py` -- Concrete `MarkdownStandardsAdapter` parsing Markdown tables and YAML frontmatter via `markdown-it-py` and `PyYAML`.
- `ttassistant/domain/exceptions.py` -- Specific domain exceptions: `StandardsError`, `MissingStandardsError`, `InvalidStandardsError`, subclassing `TTAssistantError`.
- `ttassistant/cli.py` -- Add `--standards-dir` option, inject `StandardsEngine` resolution during CLI invocation with fail-fast exit code 1 handling.
- `common_standards/` -- Canonical baseline standards files for the repository: `naming_conventions.md`, `tagging_baseline.md`, `backend_mapping.md`, `networking_policy.md`.
- `tests/test_standards_models.py` -- Unit tests for Pydantic models, validation rules, regex compilation, and constraints.
- `tests/test_standards_adapter.py` -- Unit tests for `MarkdownStandardsAdapter` table parsing, frontmatter extraction, and malformed Markdown error handling.
- `tests/test_standards_engine.py` -- Unit tests for `StandardsEngine` business logic (naming verification, tag checking, backend resolution).
- `tests/test_standards_cli.py` -- Integration tests testing CLI fail-fast behavior with missing, empty, invalid, and valid standards directories.
- `tests/test_architecture.py` -- Boundary test updates ensuring new domain and port modules comply with AD-1.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/exceptions.py` -- Add domain exceptions `StandardsError`, `MissingStandardsError`, and `InvalidStandardsError` inheriting from `TTAssistantError`.
- [x] `ttassistant/domain/models.py` -- Implement Pydantic models for naming conventions, tag baselines, backend mappings, and networking policies.
- [x] `ttassistant/domain/standards.py` -- Implement pure `StandardsEngine` domain service for rule evaluation and naming/tagging/backend verification.
- [x] `ttassistant/ports/standards_source.py` -- Define `StandardsSourcePort` abstract Protocol with `load_standards` method.
- [x] `ttassistant/adapters/standards_adapter.py` -- Implement `MarkdownStandardsAdapter` using `markdown-it-py` and `PyYAML` to parse CommonMark tables, lists, and frontmatter into domain models.
- [x] `common_standards/*.md` -- Create reference enterprise standards files (`naming_conventions.md`, `tagging_baseline.md`, `backend_mapping.md`, `networking_policy.md`).
- [x] `ttassistant/cli.py` -- Wire standards discovery and validation into CLI lifecycle with `--standards-dir` option and fail-fast handling.
- [x] `tests/test_standards_models.py` & `tests/test_standards_adapter.py` & `tests/test_standards_engine.py` -- Comprehensive unit test suite for models, adapter, and engine logic.
- [x] `tests/test_standards_cli.py` -- CLI integration tests for missing, empty, invalid, and updated standards.
- [x] `tests/test_architecture.py` -- Ensure new domain and port modules strictly adhere to AD-1 isolation.

**Acceptance Criteria:**
- Given a repository root containing `common_standards/` with Markdown specification files (`naming_conventions.md`, `tagging_baseline.md`, `backend_mapping.md`), when `StandardsEngine` initializes, then it parses Markdown tables, bullet lists, and YAML frontmatter into strongly-typed Pydantic models in memory.
- Given an execution where `common_standards/` directory is missing or empty, when `ttassistant` runs, then the CLI terminates immediately with exit code 1 and a helpful error message guiding the engineer to pull corporate standards.
- Given a modification to a naming pattern or an added mandatory tag in `common_standards/*.md`, when the CLI is executed, then the new rule is immediately enforced without code modifications or binary rebuilds.

## Implementation Notes

- Added `StandardsError`, `MissingStandardsError`, and `InvalidStandardsError` in `ttassistant/domain/exceptions.py`.
- Created strongly-typed Pydantic domain models in `ttassistant/domain/models.py` (`NamingRule`, `TagRule`, `BackendMappingRule`, `NetworkingPolicyRule`, `StandardsBundle`).
- Implemented pure domain `StandardsEngine` in `ttassistant/domain/standards.py` enforcing naming patterns, mandatory tags, case-insensitive tag reconciliation, backend state mapping, and networking policies.
- Defined `StandardsSourcePort` abstract Protocol in `ttassistant/ports/standards_source.py`.
- Implemented `MarkdownStandardsAdapter` in `ttassistant/adapters/standards_adapter.py` parsing CommonMark tables and YAML frontmatter via `markdown-it-py` and `PyYAML`, with full syntax error detection and BOM stripping.
- Created enterprise baseline standards files in `common_standards/`: `naming_conventions.md`, `tagging_baseline.md`, `backend_mapping.md`, and `networking_policy.md`.
- Integrated standards discovery and fail-fast validation in `ttassistant/cli.py` with `--standards-dir` option, `TT_STANDARDS_DIR` environment variable, and ascending ancestor directory traversal.
- Added comprehensive unit and integration tests across `tests/test_standards_models.py`, `tests/test_standards_adapter.py`, `tests/test_standards_engine.py`, `tests/test_standards_cli.py`, and updated `tests/test_architecture.py`.

## Spec Change Log

## Review Triage Log

| Finding | Layer | Verdict | Evidence | Route |
| :--- | :--- | :--- | :--- | :--- |
| Upward ancestor directory discovery of common_standards/ is unverified | verification-gap | medium | Tests ran with cwd at root or isolated dir without covering parent traversal. Patched with integration test `test_cli_upward_ancestor_standards_discovery`. | patch |
| Table cell inline parser strips wildcard asterisks in subnet_patterns | verification-gap | medium | Markdown-it parsed `*snet-paas*` as emphasis tokens; cell extractor updated to preserve asterisks, verified with assertion. | patch |
| Malformed networking_policy.md silently ignored without fail-fast verification | verification-gap | medium | Parser previously skipped header/column mismatches; updated to raise `InvalidStandardsError`, covered by unit tests. | patch |
| Delimiter check trips on escaped pipes or pipes inside inline code | edge-case-hunter | medium | Column count check updated to ignore escaped pipes and code spans, avoiding false `InvalidStandardsError`. | patch |
| Bullet list parser in tagging_baseline could parse prose as tags | edge-case-hunter | low | Guarded list item parsing strictly to bullet items under Tagging sections. | patch |
| Backend key_pattern formatting unhandled ValueError | edge-case-hunter | low | Wrapped template formatting in `try...except (KeyError, ValueError, IndexError)` raising diagnostic `StandardsError`. | patch |
| Optional tag with allowed_values rejected on empty string | edge-case-hunter | medium | Delegated validation to `TagRule.validate_tag` permitting empty values for optional tags. | patch |
| apply_default_tags duplicate keys on differing case | edge-case-hunter | medium | Filtered defaults case-insensitively before merging user tags so user casing overrides default. | patch |
| ValidationError in networking policy escapes unhandled | edge-case-hunter | low | Wrapped Pydantic validation to raise `InvalidStandardsError`. | patch |
| TT_STANDARDS_DIR empty string handling | edge-case-hunter | low | Guarded empty or whitespace string check to fall back to directory traversal. | patch |
| NamingRule.validate_name uses re.search allowing partial match | blind-hunter | high | Changed to `re.fullmatch(self.pattern, name)` to enforce complete string match. | patch |
| StandardsBundle.get_backend_rule lacks wildcard glob support | blind-hunter | low | Added `fnmatch.fnmatch(subscription, rule.subscription)` support for subscription globs. | patch |
| Naming conventions parser ignores min_length column | blind-hunter | medium | Added `min_length` column extraction and parsing. | patch |
| Frontmatter detection fails on UTF-8 BOM | blind-hunter | low | Stripped leading `\ufeff` in frontmatter parser. | patch |
| Hardcoded DNS Zone ID placeholder substitution | blind-hunter | false | DNS Zone ID is read as defined or data source in Tier 1; templating is out of scope for Story 1.2. | rejected |
| Short resource type aliases not mapped | blind-hunter | false | Standards specify canonical Terraform resource types; short aliases belong to Story 1.3 / Story 4.1. | rejected |

## Design Notes

- Markdown parsing uses `markdown-it-py` AST traversal to extract tables without regex fragility.
- Table headers are normalized (case-insensitive, trimmed) to match schema fields reliably.
- Optional YAML frontmatter between `---` fences is parsed with `yaml.safe_load`.
- Fail-fast checks ensure missing files or malformed tables halt early before user interaction begins.

## Verification

**Commands:**
- `./.venv/bin/pytest` -- expected: All unit, integration, and architecture tests pass (100% pass rate).
- `./.venv/bin/python -m ttassistant --help` -- expected: CLI boots cleanly and shows `--standards-dir` option.
- `./.venv/bin/python -m ttassistant` (with missing standards) -- expected: Terminates with exit code 1 and actionable error banner.

