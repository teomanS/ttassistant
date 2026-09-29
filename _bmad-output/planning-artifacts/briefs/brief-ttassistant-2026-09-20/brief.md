---
title: Product Brief - ttassistant (Terraform Smart Code Assistant)
status: complete
created: 2026-09-20
updated: 2026-09-21
---

# Product Brief: ttassistant

## Executive Summary

**ttassistant** is an enterprise-wide conversational CLI assistant designed to eliminate friction, configuration drift, and human error in Azure Terraform development. Operating directly within developer terminal workflows, ttassistant acts as an intelligent architectural co-pilot that navigates complex, multi-subscription Bitbucket repositories, enforces company "gold standards" codified in Markdown, and automates the tedious, error-prone wiring of enterprise cloud infrastructure.

By marrying conversational intent with deep repository archaeology, ttassistant understands where resources belong, how subscriptions and backend state are partitioned, and how cross-resource dependencies—such as Resource Groups, Private Endpoints, and Private DNS Zones—must be structured. It shifts compliance and architectural integrity left, transforming what was once an hour-long, frustrating review cycle per pull request into an instantaneous, guided authoring experience.

## The Problem

At enterprise scale, managing infrastructure across numerous Azure subscriptions in a single repository leads to severe cognitive load, organizational bottlenecks, and hidden architectural risks:

1. **Folder Fragmentation & Dependency Misplacement:** The Bitbucket repository organizes infrastructure by resource type and subscription (e.g., `storage-account/dev-subs`), but lacks strict naming or structural consistency. When provisioning a resource like an Azure Storage Account, developers often do not know where its dependent Resource Group lives, leading to misplaced resources or brittle, hardcoded strings instead of properly decoupled `data` source lookups.
2. **The "Copy-Paste" Antipattern & Incomplete Glue:** Lacking automated guidance, engineers hunt through existing folders, copy older `.tf` files, and manually edit them. In this manual process, essential enterprise requirements—specifically **Private Endpoint** connections and **Private DNS Zone** links—are routinely forgotten, exposing services or failing security audits.
3. **Severe Review Bottlenecks:** Platform and DevOps engineers spend roughly **one hour per pull request** manually catching basic structural errors, folder placement mistakes, incorrect Azure Blob backend keys, and omitted networking components.
4. **The Cost of the Status Quo:** Infrastructure delivery is slow, developer onboarding is intimidating, and the Platform team is forced into the role of gatekeeping linter rather than enabling platform innovation.

## The Solution

**ttassistant** is a terminal-native conversational CLI invoked from the repository root that bridges developer intent with the organization's existing codebase and architecture rules.

### Core Experience & Workflow
- **Repository-Aware Orchestration:** When invoked, `ttassistant` prompts the engineer for the target resource and subscription. It recursively traverses the repository's child folders (`<resource-type>/<subscription>`) to understand the active landscape.
- **Smart Dependency Resolution:** It analyzes existing Terraform scripts in the subscription. If existing resources consistently use a specific Resource Group or Subnet, `ttassistant` automatically selects them without asking redundant questions. If multiple or divergent configurations exist, it prompts the user to select the appropriate existing resource or offers to scaffold the missing dependency in its proper folder.
- **Automated Architectural Wiring:** When scaffolding a resource that supports private networking, `ttassistant` automatically generates the full networking glue: the Azure resource itself, its Private Endpoint, and the associated Private DNS Zone link.
- **Iterative Direct-to-Disk Authoring:** Rather than overwhelming the user with pages of raw HCL in the terminal prompt, `ttassistant` writes the generated `.tf` files directly into the correct destination folder and allows the developer to conversationally iterate on, tweak, and refine the code during the active session.

## What Makes This Different

Unlike generic AI code assistants (GitHub Copilot, Cursor, ChatGPT) that operate in single-file isolation and rely on public training data:

1. **Repository Topology & Cross-Folder Intelligence:** `ttassistant` is uniquely built to understand non-standard, multi-folder repository structures. It knows where parent and dependent resources live and automatically generates cross-folder references and `data` blocks.
2. **Ground Truth from Markdown Gold Standards:** Instead of relying on LLM guesswork or static linter rules, it treats company-maintained `.md` specification files as living law—ensuring naming conventions, tags, and Azure Blob backend configurations conform 100% to internal standards.
3. **Automated Enterprise Glue:** Generic assistants routinely generate naked resources; `ttassistant` automatically wires the intricate, enterprise-critical security glue (Private Endpoints, Private DNS Zones) by default.
4. **Governed Agency:** It empowers developers to move rapidly while respecting strict operational boundaries: suggestion-only for existing files, no silent overwrites, and zero auto-apply.

## Who This Serves

- **Application & Infrastructure Engineers (Primary):** Developers tasked with provisioning infrastructure for services and applications. They need to move quickly without getting bogged down by repository folder structures, missing private endpoint configurations, or cryptic Azure naming constraints.
- **Platform & DevOps Leads (Primary):** Owners of the infrastructure repository, cloud architecture standards, and CI/CD pipelines. They need automated guardrails that prevent configuration drift and eliminate the 1-hour manual review burden per PR.
- **Cloud Security & Compliance Teams (Secondary):** Governance stakeholders who require strict network boundaries, zero public IP exposures on backend services, and automated alignment with internal compliance baselines.

## Success Criteria & Measurable Impact

- **PR Review Time:** Average time spent by Platform/DevOps reviewing a Terraform PR drops from **~60 minutes down to under 15 minutes**.
- **100% Private Endpoint Compliance:** Zero production-bound resources with missing Private Endpoints or Private DNS Zone integrations.
- **First-Pass Authoring Accuracy:** At least **90% of newly generated resources** pass CI linting, validation, and review without requiring manual structural rework or folder repositioning.
- **Onboarding Acceleration:** Time for a new engineer to write and submit their first compliant Terraform module reduced by **>50%**.

## Scope Boundaries

### In Scope (v1 MVP)
- **Root-Level Conversational CLI:** Command-line tool invoked from the root of the Bitbucket repository.
- **Interactive Scaffolding Workflow:** Prompts for target resource and Azure subscription; analyzes repository structure and discovers existing child folders (`<resource-type>/<subscription>`).
- **Automated Dependency Discovery & Resolution:** Automatically detects and reuses standard Resource Groups and Subnets; prompts when configurations diverge and offers to scaffold missing dependencies.
- **End-to-End Enterprise Wiring:** Automatic generation of Private Endpoints and Private DNS Zone links for supported Azure resources.
- **Markdown Gold Standards Engine:** Ingestion of company `.md` specification files to drive naming conventions, resource tagging, and Azure Blob backend configuration.
- **Direct File Generation & Active In-Session Editing:** Writes files directly to target folders and allows conversational refinement in the active session.
- **Suggestion-Only for Existing Code:** Proposes diffs and recommendations for existing scripts; never mutates existing files without explicit user confirmation.

### Explicitly Out of Scope (v1 MVP)
- **Automatic `terraform apply`:** Execution remains strictly human-in-the-loop; the assistant will never execute `apply`.
- **Destruction / Replacement Interception:** Advanced AST plan destruction prevention (`prevent_destroy` parsing) is deferred to future releases.
- **Multi-Cloud Support:** Dedicated 100% to Microsoft Azure; AWS and GCP are out of scope.
- **Autonomous In-Place Overwrites:** The tool will not silently rewrite existing repository code.

## Vision

Over the next 1–2 years, **ttassistant** evolves from a guided authoring assistant into an autonomous **Platform Engineering Engine**:
- **Continuous Repository Modernization:** Expanding beyond new code authoring to run automated batch scans across all historical subscription folders, generating clean PRs to bring legacy infrastructure up to evolving `.md` gold standards.
- **Policy-as-Code Synchronization:** Bi-directional sync where architecture rules defined in Markdown automatically generate both CLI authoring guardrails and CI/CD policy-as-code enforcement rules (e.g., OPA/Checkov).
- **Multi-Environment Self-Service Portal:** Serving as the core intelligence engine behind internal developer portals (IDP), enabling one-click compliant cloud infrastructure provisioning across the entire enterprise.




