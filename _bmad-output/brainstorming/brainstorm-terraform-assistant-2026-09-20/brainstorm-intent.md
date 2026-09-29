# Brainstorm Intent: Smart Terraform Assistant CLI

## 1. Product Summary & Goal
An interactive, conversational CLI assistant designed to accelerate and standardize Terraform script authoring across development teams. Its primary goal is to help engineers write high-quality, secure, and compliant Terraform configurations with increased speed and safety while eliminating manual boilerplate and configuration drift.

## 2. Core Capabilities & Value Proposition
- **Markdown Gold Standards as Ground Truth**: Ingests company-defined Markdown specification files as ground-truth rules to enforce naming standards, resource tagging, and backend configurations.
- **Private Endpoint Auto-Wiring**: Automatically detects and integrates private endpoint configurations by default for all supported cloud resources, ensuring secure-by-default architecture.
- **Network Topology & Boundary Validation**: Enforces strict CIDR, subnet, and environment isolation (e.g., preventing dev/test resources from provisioning into production subnets).
- **Pattern Inference & Repository Archaeology**: Scans existing repository scripts to infer proven architectural patterns, conventions, and style, aligning new infrastructure code with established company standards.
- **Standard Drift Detection**: Compares new and existing scripts against gold standard specifications to propose targeted improvements.

## 3. Non-Negotiables & Guardrails
- **Suggestion-Only on Existing Files**: The assistant must NEVER directly modify or overwrite existing files without explicit user confirmation and review.
- **Zero Auto-Apply**: Execution remains strictly human-in-the-loop; the assistant must NEVER automatically invoke or execute `terraform apply`.
- **No Destruction Protection in Core Scope**: Explicitly out of scope for the MVP/core release (no complex AST `prevent_destroy` or forced replacement interceptors required initially).
- **No Security Bypasses**: Never inject insecure defaults (e.g., open `0.0.0.0/0` access) to bypass errors.

## 4. User Personas & Workflows
- **Platform Lead**:
  - *Needs*: Standardize infrastructure practices, maintain security boundaries, and ensure compliance without becoming a PR bottleneck.
  - *Workflow*: Defines gold standards in Markdown; relies on the assistant to enforce naming conventions, backend setups, and private endpoint wiring across developer submissions.
- **Junior Developer**:
  - *Needs*: Guided authoring of infrastructure without deep expertise in complex networking, naming rules, or Terraform idiosyncrasies.
  - *Workflow*: Engages in a conversational CLI session to scaffold new resources; receives compliant, pre-wired configurations adhering to team standards.

## 5. Technical Scope & Architecture Overview
- **Interface**: Interactive, conversational CLI tool for developer workstations and local workflows.
- **Knowledge & Policy Ingestion**: Parser and validator for Markdown-based gold standard specifications.
- **Code Analysis & Generation Engine**: AST/HCL parsing, pattern extraction from repository scripts, and compliant code generation.
- **Validation Pipeline**: Pre-generation and post-generation checks for subnet boundaries, CIDR allocations, and private endpoint connectivity prior to presenting suggestions.
