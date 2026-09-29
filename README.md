# `ttassistant`

> **Enterprise Terminal CLI Copilot for Azure Terraform Development**

`ttassistant` is an air-gapped terminal copilot designed for platform and cloud engineering teams managing large-scale Azure Terraform monorepos. It ensures corporate compliance at creation time, discovers network topologies, enables interactive configuration tweaking, and provides surgical in-place compliance remediation.

---

## Key Highlights

- **Air-Gapped & Zero Dependencies**: Runs completely offline without invoking `terraform`, `az` CLI, or remote provider endpoints.
- **Enterprise Security Triad**: Enforces `public_network_access_enabled = false`, companion Private Endpoints, and Hub Private DNS Zone Group bundling by default.
- **Dynamic Corporate Standards Engine**: Ingests markdown corporate specifications (`naming_conventions.md`, `tagging_baseline.md`, `networking_policy.md`, `backend_mapping.md`) with a fail-fast policy.
- **Monorepo Topology Scanning**: Fast lexical regex scanning (<500ms for 10k LOC) with Phase 2 HCL AST extraction for candidate subnets and VNets.
- **Interactive Tweak Engine**: Natural attribute aliasing (`sku = Standard_GRS`, `tier = Premium`, `tags.CostCenter = CC-1001`) with dynamic colorized unified diff previews.
- **Surgical In-Place Remediation**: Comment-preserving (`#`, `//`, `/* ... */`) HCL patcher with CI/CD audit gating (`--check` exits code 1 on non-compliance).

---

## Installation

### From Distribution Wheel
```bash
pip install dist/ttassistant-0.1.0-py3-none-any.whl
```

### Local Development Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Quickstart

### 1. Scaffold a Secure Storage Account
```bash
ttassistant new \
  --subscription workload-prod \
  --resource-type azurerm_storage_account \
  --workload appdata \
  --env prod \
  --subnet snet-paas \
  --yes
```

### 2. Discover Monorepo Network Topology
```bash
ttassistant scan . --ast
```

### 3. Explore Bundled Schema Catalog Offline
```bash
ttassistant catalog list --tier 1
ttassistant catalog info azurerm_key_vault
```

### 4. Audit & Surgically Remediate Legacy Code
```bash
# CI Audit gate (exits code 1 on violations)
ttassistant remediate ./workloads/legacy --check

# Surgical in-place fix with comment preservation
ttassistant remediate ./workloads/legacy --yes
```

---

## Documentation

- 📖 [**User Guide**](docs/user-guide.md): Step-by-step developer workflows, recipes, and best practices.
- 🛠️ [**CLI Reference**](docs/cli-reference.md): Full flag specifications and architectural details for `new`, `scan`, `catalog`, and `remediate`.

---

## Running Tests

```bash
pytest
```
- **511 unit, integration, and E2E tests** passing across 28 test modules.
- End-to-end integration tests located at [`tests/e2e/test_cli_e2e_workflows.py`](tests/e2e/test_cli_e2e_workflows.py).

---

## License

MIT
