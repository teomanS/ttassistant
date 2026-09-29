# Epic 2 Context: Monorepo Topology Discovery & Decoupled Networking Archaeology

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Enable infrastructure engineers to discover and bind existing cloud networking dependencies across complex monorepo directory structures without hardcoding IDs or using brittle remote state coupling. ttassistant automatically traverses the repository, identifies candidate subnets and parent Resource Groups via a fast two-phase lexical and read-only AST pipeline, guides interactive subnet selection (or scaffolds missing subnet definitions), and emits decoupled `data "azurerm_*"` blocks directly into `data.tf`.

## Stories

- Story 2.1: Monorepo Topology Traversal & Lexical Candidate Indexer (Phase 1)
- Story 2.2: Targeted Read-Only HCL AST Extraction for Networking & Resource Groups (Phase 2)
- Story 2.3: Collaborative Subnet Selection & Missing Dependency Scaffolding
- Story 2.4: Decoupled Data Source Generator

## Requirements & Constraints

- **Monorepo Topology Traversal**: Recursively traverse the repository starting from the root to locate `<resource-type>/<subscription>/` directories, accommodating non-uniform and legacy folder naming (e.g., `resource-groups/sub-prod/` vs `rg/sub_prod/`).
- **Scan Performance & Footprint**: Complete discovery and indexing across monorepos with up to 10,000 files in <= 3.0 seconds, maintaining a memory footprint under 150 MB RSS. Exclude `.git`, `.terraform`, `.venv`, and binary/build directories.
- **Subnet & Resource Group Discovery**: Inspect existing `.tf` files across networking and foundation folders to discover declared subnets (names, address prefixes, tags), Virtual Networks, and parent Resource Groups in the target subscription. Detect subnets designated for Private Endpoints using attributes, tags, and standards heuristics.
- **Read-Only AST Parsing**: AST parsing via pure-Python `python-hcl2` must be strictly read-only. Round-trip serialization or dumping (`hcl2.dump()`) is prohibited to prevent formatting disruption and comment stripping.
- **Collaborative Subnet Selection & Scaffolding**: Present discovered candidate subnets in an interactive selection menu. If no candidate subnets exist in the subscription, provide options to scaffold the missing subnet/VNet definition in its designated networking folder or configure a cross-subscription shared network lookup.
- **Decoupled Data Source Scaffolding**: Emit clean Terraform `data "azurerm_*"` blocks in `data.tf` referencing upstream resources by name and resource group. Avoid hardcoded resource IDs and enforce strictly zero `terraform_remote_state` data blocks.
- **Zero Local Binaries & Air-Gapped Operation**: Execute all topology scanning and AST extraction purely in Python without external `terraform` or `az` CLI binaries, credentials, or cloud API calls.

## Technical Decisions

- **Two-Phase Discovery Pipeline (AD-2)**:
  - *Phase 1 (Lexical Indexer)*: Fast streaming regex and keyword pre-filtering across `.tf` files to identify candidate files containing `azurerm_subnet`, `azurerm_virtual_network`, or `azurerm_resource_group` blocks.
  - *Phase 2 (Targeted AST Extraction)*: Pure-Python AST parsing with `python-hcl2` executed exclusively on the candidate files indexed in Phase 1.
- **Hexagonal Architecture Boundaries (AD-1)**:
  - `ttassistant.domain.topology`: Domain models (`SubnetCandidate`, `ResourceGroupCandidate`, `VNetCandidate`, `TopologyIndex`) and discovery logic, completely isolated from terminal UI and filesystem I/O.
  - `ttassistant.ports`: Abstract interfaces for filesystem scanning and HCL parsing.
  - `ttassistant.adapters.hcl_adapter`: Concrete read-only parser adapter wrapping `python-hcl2`.
  - `ttassistant.domain.scaffold`: Synthesis of decoupled `data.tf` blocks (`azurerm_resource_group`, `azurerm_subnet`, `azurerm_virtual_network`).
  - `ttassistant.application.provisioning_flow`: Flow orchestration integrating discovery results into the interactive wizard.
- **Decoupled Data Architecture (AD-3)**:
  - Upstream dependencies are emitted in `data.tf` as `data "azurerm_*"` blocks (`data.azurerm_resource_group.<name>.name`, `data.azurerm_subnet.<name>.id`), maintaining modular isolation without remote state coupling.
- **Multi-Directory Atomic Staging (AD-5)**:
  - When scaffolding missing subnets in shared networking directories alongside target workload resources, all modified directories are staged in `StagedWorkspace` and committed as a single atomic transaction.

## UX & Interaction Patterns

- **Interactive Subnet Menu**: Numbered interactive prompt displaying subnet names, CIDR blocks, and intended purpose.
- **Standards Recommendations**: Subnets matching `common_standards/` recommendations are highlighted as `(Recommended)` and set as the default option.
- **Missing Dependency Prompting**: Guided dialogue prompting the engineer when dependencies are absent, offering to scaffold missing definitions or wire cross-subscription lookups.
- **Terminal Fallback**: Terminal interactions gracefully degrade to standard line-by-line indexed text input in non-TTY or `TERM=dumb` environments.

## Cross-Story Dependencies

- **Story 2.1** provides the repository traversal walker and lexical candidate indexer.
- **Story 2.2** consumes candidate files from Story 2.1 to extract structured AST metadata using `python-hcl2`.
- **Story 2.3** hooks the discovered subnets into the interactive provisioning dialogue (built in Story 1.3), presenting selection prompts and handling missing subnet scaffolding in `StagedWorkspace`.
- **Story 2.4** consumes the selected networking and Resource Group entities from Story 2.3 to synthesize decoupled `data.tf` blocks via the scaffolding engine (built in Story 1.4).
