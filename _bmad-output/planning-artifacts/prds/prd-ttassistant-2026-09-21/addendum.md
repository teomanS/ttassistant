# PRD Addendum: ttassistant

*Downstream technical depth, architectural rationale, and implementation guidance supporting the PRD.*

---

## 1. Architectural Decisions & Rejected Alternatives

### 1.1 Decoupled Data Sources vs. `terraform_remote_state`
- **Decision:** Mandate `data "azurerm_*"` blocks for all cross-resource lookups (Resource Groups, Subnets, Virtual Networks).
- **Rejected Alternative:** `terraform_remote_state` blocks reading outputs from parent subscription state files.
- **Rationale:** Reading upstream `.tfstate` files introduces high coupling, requires broad read permissions across all subscription state containers, and causes downstream failures whenever an upstream output name changes. `data` blocks provide loose coupling and zero state lock contention.

### 1.2 Zero Local Binary Execution vs. Local CLI Wrapping
- **Decision:** Zero external binary dependency (`terraform` and `az` are not required locally).
- **Rejected Alternative:** Wrapping local `terraform fmt`, `terraform validate`, or `az account show`.
- **Rationale:** Ensures frictionless developer onboarding across heterogeneous developer machines (Windows PowerShell without WSL, minimal Linux environments) without debugging local binary versions, PATH issues, or Azure CLI authentication tokens.

### 1.3 `common_standards/` Dynamic Rulebook vs. Hardcoded CLI Schemas
- **Decision:** Ingest Markdown policies from `common_standards/*.md` dynamically at runtime.
- **Rejected Alternative:** Hardcoding naming regexes, tag policies, and storage account mappings inside CLI Python source code.
- **Rationale:** Platform and security teams can update corporate standards via standard Git pull requests without triggering a CLI rebuild or distributing a new Python package release.

### 1.4 Tiered Resource Catalog Architecture vs. Monolithic Schema Bundling
- **Decision:** Partition the AzureRM resource catalog into Tier 1 (guided conversational scaffolding with full Enterprise Security Triad bundling) and Tier 2 (universal long-tail scaffolding).
- **Rejected Alternative:** Bundling full static AST schemas and specialized interactive wizard dialogue trees for all 1,000+ AzureRM provider resources.
- **Rationale:** Keeps the CLI lightweight (<150 MB memory budget per NFR-3), guarantees maintainability, and focuses conversational depth on high-risk PaaS services where compliance errors actually happen.

---

## 2. Downstream Implementation & Technical Architecture Notes

### 2.1 Repository Archaeology & Subnet Discovery Heuristics
- **Topology Traversal:** Scan the repository root for directories matching `*/*` where the second element corresponds to known subscription keys (e.g. `payments-prod`, `core-shared`).
- **Subnet Extraction:** Scan existing networking modules (`virtual-network/`, `vnet/`, `networking/`) using Python HCL/AST or regex tokenizers to extract subnet resource names, address prefixes, and tags.
- **Recommendation Matching:** Cross-reference extracted subnets with heuristics in `common_standards/` (e.g. matching regex patterns `snet-pep-.*` or `.*private.*`).

### 2.2 Enterprise Python Package Distribution
- **Build Target:** Standard Python Wheel (`.whl`) targeting Python 3.10+.
- **CLI Framework:** Built using modern Python CLI frameworks (e.g., `Typer` / `Click` with `Rich` / `InquirerPy` or `prompt_toolkit` for interactive VT100/ANSI dialogue).
- **Distribution:** Hosted on corporate internal artifact repository (e.g., Azure Artifacts, JFrog Artifactory, or private PyPI). Installed via `pip install --index-url ... ttassistant` or run via `pipx run ttassistant`.

---

## 3. Post-MVP Technical Backlog (Future Initiatives)

1. **AST Plan Destruction Protection (v2):** Integration with CI plan JSON outputs to inspect resources flagged for `forces replacement` or missing `lifecycle { prevent_destroy = true }`.
2. **Batch Drift Remediation Engine (v2):** A platform-mode CLI scanner that audits legacy `<resource-type>/<subscription>` folders against `common_standards/` and automatically opens Bitbucket pull requests adding missing Private Endpoints and tagging baselines.
3. **Multi-Cloud Extensions (v3+):** Potential adaptation to AWS or GCP landing zones if the enterprise adopts multi-cloud architectures.
