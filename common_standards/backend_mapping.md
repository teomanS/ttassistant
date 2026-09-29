---
title: Remote State Backend Mapping
version: "1.0.0"
default_container: tfstate
---

# Remote State Backend Mapping

Azure Blob Storage backend mappings for Terraform remote state isolation across subscriptions.

| Subscription | Resource Group | Storage Account | Container | Key Pattern |
| :--- | :--- | :--- | :--- | :--- |
| core-networking | rg-tfstate-mgmt | sttfstatenetworking | tfstate | networking/{resource_type}.tfstate |
| core-shared | rg-tfstate-mgmt | sttfstateshared | tfstate | shared/{resource_type}.tfstate |
| workload-dev | rg-tfstate-dev | sttfstatedev | tfstate | dev/{resource_type}.tfstate |
| workload-prod | rg-tfstate-prod | sttfstateprod | tfstate | prod/{resource_type}.tfstate |
| * | rg-tfstate-default | sttfstatedefault | tfstate | {subscription}/{resource_type}.tfstate |
