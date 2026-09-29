---
title: Corporate Tagging Baseline
version: "1.0.0"
---

# Tagging Baseline Policy

Mandatory and optional resource tags required on all Azure resources.

| Tag Key | Required | Allowed Values | Default Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| Environment | Yes | dev, test, stage, prod | dev | Target deployment environment |
| Owner | Yes | | cloud-platform@corporate.com | Team or individual responsible |
| Project | Yes | | CorePlatform | Project or workload designation |
| CostCenter | Yes | | CC-1001 | Financial cost center code |
| ManagedBy | No | terraform, manual | terraform | Deployment automation tool |
