"""Application flow for existing directory compliance inspection and non-compliance diagnostics (AD-1, AD-7)."""

import logging
from pathlib import Path
from typing import Optional, Union

from ttassistant.domain.compliance import (
    ComplianceReport,
    ComplianceSeverity,
    ComplianceViolation,
    ComplianceViolationType,
    ParsedResource,
    audit_paas_security_triad,
    audit_resource_tags,
)
from ttassistant.domain.diff import compute_workspace_diff
from ttassistant.domain.models import StagedFile, StagedWorkspace
from ttassistant.domain.patcher import (
    generate_companion_private_endpoint,
    patch_public_network_access,
    patch_tags,
)
from ttassistant.domain.standards import StandardsEngine
from ttassistant.domain.topology import infer_subscription
from ttassistant.ports.filesystem import FileSystemPort
from ttassistant.ports.hcl_parser import HCLParserPort
from ttassistant.ports.terminal import TerminalUIPort

logger = logging.getLogger(__name__)

AUXILIARY_RESOURCE_TYPES = {
    "azurerm_resource_group",
    "azurerm_private_endpoint",
    "azurerm_subnet",
    "azurerm_virtual_network",
}

SEVERITY_ORDER = {
    ComplianceSeverity.CRITICAL: 0,
    ComplianceSeverity.HIGH: 1,
    ComplianceSeverity.MEDIUM: 2,
    ComplianceSeverity.LOW: 3,
}


class RemediationFlow:
    """Orchestrates non-destructive audit and diagnostic inspection of existing Terraform directories."""

    def __init__(
        self,
        terminal: TerminalUIPort,
        standards: StandardsEngine,
        fs: Optional[FileSystemPort] = None,
        hcl_parser: Optional[HCLParserPort] = None,
    ) -> None:
        """Initialize the remediation flow with terminal UI, standards engine, filesystem, and parser ports.

        Args:
            terminal: Terminal UI port implementation.
            standards: Standards engine domain service.
            fs: Optional filesystem port implementation.
            hcl_parser: Optional HCL parser port implementation.
        """
        self.terminal = terminal
        self.standards = standards
        self.fs = fs
        self.hcl_parser = hcl_parser

    def inspect_directory(self, target_dir: Union[Path, str]) -> ComplianceReport:
        """Inspect an existing directory and perform non-compliance diagnostic auditing.

        Args:
            target_dir: Directory path containing Terraform files to audit.

        Returns:
            ComplianceReport containing detected resources, inspected files, and violations.

        Raises:
            FileNotFoundError: If target_dir does not exist or is not a directory.
        """
        dir_path = Path(target_dir).resolve()
        if not dir_path.exists():
            raise FileNotFoundError(f"Target directory does not exist: '{dir_path}'")
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Target path is not a directory: '{dir_path}'")

        subscription = infer_subscription(dir_path)

        # Locate all .tf files in the directory
        tf_files: list[Path] = sorted(dir_path.glob("*.tf"))
        inspected_paths = [str(p) for p in tf_files]

        if not tf_files:
            return ComplianceReport(
                target_dir=str(target_dir),
                subscription=subscription,
                inspected_files=[],
                detected_resources=[],
                violations=[],
                parse_warnings=[f"No .tf files discovered in directory '{dir_path}'."],
            )

        all_resources: list[ParsedResource] = []
        parse_warnings: list[str] = []

        if self.hcl_parser is None:
            raise RuntimeError("HCL parser port is required for directory compliance inspection.")

        # Parse HCL resources across all .tf files
        for tf_path in tf_files:
            resources, warnings = self.hcl_parser.parse_resources_from_file(tf_path)
            all_resources.extend(resources)
            parse_warnings.extend(warnings)

        detected_resources = [f"{r.resource_type}.{r.resource_name}" for r in all_resources]

        # Identify taggable resources (exclude plumbing like subnets and private endpoints)
        taggable_resources = [
            r for r in all_resources if r.resource_type not in {"azurerm_subnet", "azurerm_private_endpoint"}
        ]

        # Resolve mandatory tagging rules from standards
        required_tags: list[str] = []
        standards_defaults: dict[str, str] = {}
        if self.standards and self.standards.bundle:
            for rule in self.standards.bundle.tag_rules.values():
                if rule.required:
                    required_tags.append(rule.key)
                if rule.default_value:
                    standards_defaults[rule.key] = rule.default_value

        if not required_tags:
            # Fallback baseline corporate tags per tagging_baseline.md
            required_tags = ["CostCenter", "Environment", "Owner", "Project"]

        violations: list[ComplianceViolation] = []

        # 1. Mandatory tags audit on taggable resources
        for resource in taggable_resources:
            tag_violations = audit_resource_tags(
                resource=resource,
                required_tags=required_tags,
                standards_defaults=standards_defaults,
            )
            violations.extend(tag_violations)

        # 2. Enterprise Security Triad audit on PaaS resources
        for resource in all_resources:
            security_violations = audit_paas_security_triad(
                primary_resource=resource,
                all_resources=all_resources,
            )
            violations.extend(security_violations)

        # 3. Naming convention validation from standards
        if self.standards:
            for resource in all_resources:
                # Use declared Azure 'name' attribute if present, otherwise Terraform resource block label
                azure_name = str(resource.attributes.get("name") or resource.resource_name)
                is_valid, err_msg = self.standards.validate_resource_name(
                    resource.resource_type, azure_name
                )
                if not is_valid and err_msg:
                    violations.append(
                        ComplianceViolation(
                            violation_type=ComplianceViolationType.INVALID_RESOURCE_NAME,
                            severity=ComplianceSeverity.MEDIUM,
                            resource_type=resource.resource_type,
                            resource_name=resource.resource_name,
                            file_path=resource.file_path,
                            message=err_msg,
                            attribute_name="name",
                            expected_value="<compliant_name>",
                            actual_value=azure_name,
                            remediation_hint=f"Rename resource '{azure_name}' in {resource.file_path} to comply with corporate naming standards.",
                        )
                    )

        # Sort violations deterministically by severity then resource
        violations.sort(key=lambda v: (SEVERITY_ORDER.get(v.severity, 99), v.resource_type, v.resource_name))

        return ComplianceReport(
            target_dir=str(target_dir),
            subscription=subscription,
            inspected_files=inspected_paths,
            detected_resources=detected_resources,
            resources=all_resources,
            violations=violations,
            parse_warnings=parse_warnings,
        )

    def run_diagnostics(
        self,
        target_dir: Union[Path, str],
        check: bool = False,
    ) -> tuple[ComplianceReport, int]:
        """Execute diagnostic audit, display formatted terminal breakdown, and return status code.

        Args:
            target_dir: Directory path to inspect.
            check: When True, return exit code 1 if violations are found (CI quality gate mode).

        Returns:
            Tuple of (ComplianceReport, exit_code).
        """
        try:
            report = self.inspect_directory(target_dir)
        except FileNotFoundError as exc:
            self.terminal.print_error(str(exc))
            return (
                ComplianceReport(
                    target_dir=str(target_dir),
                    violations=[],
                    parse_warnings=[str(exc)],
                ),
                1,
            )

        # Header summary
        self.terminal.print_info(f"Inspecting directory: {target_dir}")
        self.terminal.print(f"  Target Path:        {Path(target_dir).resolve()}")
        self.terminal.print(f"  Subscription:       {report.subscription or 'unassigned'}")
        self.terminal.print(f"  Files Inspected:    {len(report.inspected_files)}")
        res_summary = ", ".join(report.detected_resources) if report.detected_resources else "None"
        self.terminal.print(f"  Detected Resources: {res_summary}")

        if report.parse_warnings:
            for w in report.parse_warnings:
                self.terminal.print_warning(f"Parse Warning: {w}")

        if not report.inspected_files:
            self.terminal.print_warning(f"No .tf files discovered in directory '{target_dir}'.")
            return report, 0

        # Compliance status breakdown
        if report.is_compliant:
            self.terminal.print()
            self.terminal.print_success(
                "Compliance Audit: 100% compliant with corporate standards (0 violations detected)."
            )
            return report, 0

        # Non-compliant: render diagnostic table
        self.terminal.print()
        self.terminal.print_warning(
            f"Compliance Audit: Found {len(report.violations)} violation(s) "
            f"({report.critical_count} critical, {report.high_count} high, {report.medium_count} medium, {report.low_count} low)."
        )

        headers = ["Severity", "Violation Category", "Target Resource", "File", "Remediation Hint"]
        rows = [
            [
                v.severity.value,
                v.violation_type.value,
                f"{v.resource_type}.{v.resource_name}",
                Path(v.file_path).name,
                v.remediation_hint,
            ]
            for v in report.violations
        ]

        if hasattr(self.terminal, "display_table"):
            self.terminal.display_table("Non-Compliance Diagnostics", headers, rows)
        else:
            for v in report.violations:
                self.terminal.print(
                    f"  [{v.severity.value}] {v.violation_type.value}: {v.resource_type}.{v.resource_name} - {v.message}"
                )

        exit_code = 1 if (check and not report.is_compliant) else 0
        return report, exit_code

    def stage_remediation(
        self,
        target_dir: Union[Path, str],
        report: Optional[ComplianceReport] = None,
    ) -> StagedWorkspace:
        """Stage surgical in-memory repairs for detected compliance violations.

        Args:
            target_dir: Directory containing Terraform files to remediate.
            report: Optional pre-computed ComplianceReport.

        Returns:
            StagedWorkspace containing surgically patched in-memory file buffers.
        """
        dir_path = Path(target_dir).resolve()
        if report is None:
            report = self.inspect_directory(dir_path)

        rel_dir = dir_path.name
        workspace = StagedWorkspace(target_dir=rel_dir)
        if not report.inspected_files or report.is_compliant:
            return workspace

        # Read existing file contents into workspace buffers
        file_buffers: dict[str, str] = {}
        for file_str in report.inspected_files:
            p = Path(file_str)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.warning(f"Could not read {p}: {exc}")
                content = ""
            file_buffers[str(p)] = content
            file_buffers[p.name] = content

        resource_map: dict[str, ParsedResource] = {
            f"{r.resource_type}.{r.resource_name}": r for r in report.resources
        }

        # Group violations by (file_path, resource_type, resource_name)
        tag_patches: dict[tuple[str, str, str], dict[str, str]] = {}
        pna_patches: dict[tuple[str, str, str], bool] = {}
        missing_pes: list[ComplianceViolation] = []

        for v in report.violations:
            key = (v.file_path, v.resource_type, v.resource_name)
            if v.violation_type in (
                ComplianceViolationType.PUBLIC_NETWORK_ACCESS_ENABLED,
                ComplianceViolationType.MISSING_PUBLIC_NETWORK_ACCESS_DENIAL,
            ):
                pna_patches[key] = False
            elif v.violation_type in (
                ComplianceViolationType.MISSING_TAG,
                ComplianceViolationType.INVALID_TAG_VALUE,
            ):
                if key not in tag_patches:
                    tag_patches[key] = {}
                tag_name = v.attribute_name.replace("tags.", "") if v.attribute_name else ""
                expected = (
                    str(v.expected_value)
                    if v.expected_value and v.expected_value not in ("<compliant_value>", "<non_empty_value>")
                    else "..."
                )
                if tag_name:
                    tag_patches[key][tag_name] = expected
            elif v.violation_type == ComplianceViolationType.MISSING_PRIVATE_ENDPOINT:
                missing_pes.append(v)

        # 1. Apply surgical PNA patches
        for (f_path, r_type, r_name), enabled in pna_patches.items():
            f_name = Path(f_path).name
            curr_content = file_buffers.get(f_path) or file_buffers.get(f_name, "")
            patched = patch_public_network_access(curr_content, r_type, r_name, enabled=enabled)
            file_buffers[f_path] = patched
            file_buffers[f_name] = patched

        # 2. Apply surgical tag patches
        for (f_path, r_type, r_name), missing_tags in tag_patches.items():
            f_name = Path(f_path).name
            curr_content = file_buffers.get(f_path) or file_buffers.get(f_name, "")
            patched = patch_tags(curr_content, r_type, r_name, missing_tags)
            file_buffers[f_path] = patched
            file_buffers[f_name] = patched

        # 3. Apply companion Private Endpoint generation
        for v in missing_pes:
            primary_r = resource_map.get(f"{v.resource_type}.{v.resource_name}")
            loc = primary_r.attributes.get("location") if primary_r else None
            rg = primary_r.attributes.get("resource_group_name") if primary_r else None
            pe_block = generate_companion_private_endpoint(
                resource_type=v.resource_type,
                resource_name=v.resource_name,
                location=loc,
                resource_group_name=rg,
            )
            target_f = "main.tf" if "main.tf" in file_buffers else Path(v.file_path).name
            curr_content = file_buffers.get(target_f, "")
            file_buffers[target_f] = curr_content.rstrip() + pe_block
            for k in list(file_buffers.keys()):
                if Path(k).name == target_f:
                    file_buffers[k] = file_buffers[target_f]

        # Populate StagedWorkspace with modified files
        for file_str in report.inspected_files:
            p = Path(file_str)
            rel_name = p.name
            orig_text = p.read_text(encoding="utf-8", errors="replace")
            new_text = file_buffers.get(str(p), file_buffers.get(rel_name, orig_text))
            if new_text != orig_text:
                staged = StagedFile(
                    path=f"{rel_dir}/{rel_name}",
                    content=new_text,
                    is_new=False,
                )
                workspace.add_file(staged)

        # Check for any new files created during remediation
        for f_key, new_text in file_buffers.items():
            if "/" not in f_key and "\\" not in f_key:
                if not any(Path(f).name == f_key for f in report.inspected_files):
                    staged = StagedFile(
                        path=f"{rel_dir}/{f_key}",
                        content=new_text,
                        is_new=True,
                    )
                    workspace.add_file(staged)

        return workspace

    def run_remediation(
        self,
        target_dir: Union[Path, str],
        check: bool = False,
        auto_approve: bool = False,
    ) -> tuple[ComplianceReport, int]:
        """Execute full remediation: audit, stage surgical diff, preview, and atomically commit.

        Args:
            target_dir: Target directory path.
            check: When True, audit mode only (exit code 1 on violations, no diff or writes).
            auto_approve: When True, bypass confirmation gate and commit immediately.

        Returns:
            Tuple of (ComplianceReport, exit_code).
        """
        report, diag_exit_code = self.run_diagnostics(target_dir, check=check)
        if check or report.is_compliant or not report.inspected_files:
            return report, diag_exit_code

        # Stage surgical remediation in-memory
        dir_path = Path(target_dir).resolve()
        workspace = self.stage_remediation(target_dir, report=report)

        # Compute unified diff
        disk_files: dict[str, str] = {}
        for file_str in report.inspected_files:
            p = Path(file_str)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                disk_files[p.name] = content
                disk_files[str(p)] = content
                disk_files[f"{dir_path.name}/{p.name}"] = content
            except Exception:
                pass

        workspace_diff = compute_workspace_diff(workspace, existing_files=disk_files)
        if not workspace_diff.has_changes:
            return report, 0

        # Display unified diff preview
        self.terminal.print()
        self.terminal.display_diff(workspace_diff.diff_text)

        # Confirmation gate
        if auto_approve:
            if self.fs is None:
                raise RuntimeError("FileSystem port is required for committing remediation changes.")
            self.fs.commit_workspace(workspace, base_dir=dir_path.parent)
            self.terminal.print_success(
                f"Successfully committed surgical remediation across {len(workspace.files)} file(s)."
            )
            return report, 0

        confirmed = self.terminal.confirm(
            "Apply surgical remediation to disk?",
            default=True,
        )
        if confirmed:
            if self.fs is None:
                raise RuntimeError("FileSystem port is required for committing remediation changes.")
            self.fs.commit_workspace(workspace, base_dir=dir_path.parent)
            self.terminal.print_success(
                f"Successfully committed surgical remediation across {len(workspace.files)} file(s)."
            )
            return report, 0
        else:
            self.terminal.print_warning("Remediation cancelled. Disk left untouched.")
            return report, 0

