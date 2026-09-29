# Epic 1 Context: CLI Foundation, Dynamic Standards & Governed Scaffolding Flow

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Provide infrastructure engineers with a cross-platform CLI tool (`ttassistant`) executable inside VSCode terminals across Linux and Windows without requiring local `terraform` or `az` binaries. It dynamically loads corporate Markdown standards (naming conventions, mandatory tags, Azure Blob backend mappings), guides users through interactive provisioning prompts, previews color-coded unified diffs, and commits scaffolding atomically to disk upon human confirmation with zero live apply.

## Stories

- Story 1.1: Project Skeleton, Hexagonal Architecture & Typer CLI Entrypoint
- Story 1.2: Dynamic Markdown Standards Engine & Fail-Fast Policy
- Story 1.3: Guided Provisioning Dialogue & Parameter Collection
- Story 1.4: Standards-Governed Greenfield Scaffolding & State Backend Synthesis
- Story 1.5: Unified Terminal Diff Preview, Human Confirmation Gate & Atomic Disk Writes

## Requirements & Constraints

- **Zero Local Binaries**: No invocation of external `terraform`, `az`, or shell binaries. Scaffolding, parsing, and HCL2 generation happen entirely in-memory.
- **Fail-Fast Standards Ingestion**: Dynamic discovery and parsing of `common_standards/*.md` at startup. If missing or invalid, fail immediately with exit code 1 and actionable error messages.
- **Standards Enforcement**: Corporate naming prefix/suffix schemas, mandatory tagging baseline, and isolated Azure Blob storage backend configuration applied automatically.
- **Governed Human Gate**: Mandatory interactive confirmation ([Y] Commit / [N] Cancel) with color-coded diff preview before any disk writes. Strictly no `terraform apply`.
- **Atomic Operations**: Atomic disk writes across directories via temporary sibling files and `os.replace` swaps, with full rollback on failure. Idempotent output.
- **Performance Budgets**: Cold CLI boot under 1.5s; process memory footprint under 150 MB RSS.

## Technical Decisions

- **Hexagonal Architecture (AD-1)**:
  - `ttassistant.domain`: Pure business models and validation rules, zero I/O, zero terminal UI imports.
  - `ttassistant.ports`: Python `Protocol` definitions (`TerminalUIPort`, `FileSystemPort`, `StandardsSourcePort`).
  - `ttassistant.adapters`: Concrete implementations (`RichTerminalUIAdapter`, `DiskFileSystemAdapter`, `CommonMarkStandardsAdapter`).
  - `ttassistant.application`: Use case orchestrators (`ScaffoldingOrchestrator`).
- **Packaging**: Standard PEP 621 `pyproject.toml` with Hatchling build system, targeting Python 3.10+.
- **Standards Parsing (AD-6)**: `markdown-it-py` and `PyYAML` parsing Markdown tables, lists, and YAML frontmatter into typed Pydantic models.
- **In-Memory Workspace & Atomic Writes (AD-5)**: `StagedWorkspace` memory staging, writing to sibling `.tmp` files with `os.fsync` and atomic `os.replace`.

## UX & Interaction Patterns

- Interactive CLI rendered with Rich and Questionary.
- Clean ANSI formatting with automatic ASCII fallback for legacy code pages, and plain-text line-oriented fallback for non-TTY / `TERM=dumb`.
- Keyboard navigation (arrows, Enter, tab-completion, clean Esc/Ctrl+C exit).
- Visual color-coded unified diff (green additions, red removals) matching exact bytes to be written.

## Cross-Story Dependencies

- **Story 1.1** scaffolds the package layout, dependencies, CLI entrypoint, and hexagonal boundaries.
- **Story 1.2** introduces the domain models, ports, and adapter for reading `common_standards/`.
- **Story 1.3** implements the interactive UI prompts relying on Story 1.1 (entrypoint) and Story 1.2 (standards validation).
- **Story 1.4** synthesizes the HCL2 files in memory using collected parameters and standards.
- **Story 1.5** wraps the workflow with the diff viewer, confirmation gate, and atomic writer.

