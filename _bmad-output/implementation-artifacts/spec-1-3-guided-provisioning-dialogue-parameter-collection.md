---
title: 'Story 1.3: Guided Provisioning Dialogue & Parameter Collection'
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

**Problem:** Infrastructure developers frequently misconfigure new cloud workloads or violate corporate standards because they must memorize obscure Azure naming rules, required tagging baselines, and subscription state keys across disparate monorepo folders.

**Approach:** Implement an interactive guided provisioning dialogue (`ttassistant new`) in `ttassistant.application.provisioning_flow` using `TerminalUIPort` that prompts step-by-step for Target Subscription, Resource Type, and Workload Name with live inline validation against `StandardsEngine`, keyboard navigation, and clean non-TTY and abort handling.

## Boundaries & Constraints

**Always:**
- Keep pure business domain models (`ttassistant.domain.models.ProvisioningParameters`) free of UI and filesystem dependencies (AD-1).
- Implement interactive dialogue orchestration in the application layer (`ttassistant.application.provisioning_flow.ProvisioningFlow`) relying strictly on abstract ports (`TerminalUIPort`, `StandardsEngine`).
- Validate user input inline during typing using `StandardsEngine` naming rules (allowed character regex, min/max length), displaying actionable error feedback without crashing or exiting.
- Support clean keyboard navigation (arrows, Enter, Tab) in interactive TTY terminals, and graceful numbered/text line fallbacks with validation loops in non-TTY or `TERM=dumb` environments.
- Handle `Ctrl+C`, `Escape`, or EOF cleanly by raising or catching `Abort` and exiting with code 130 or user-facing cancellation message without unhandled stack traces.
- Ensure cold boot and prompt presentation executes within the <= 1.5s latency budget.

**Never:**
- Never import `rich`, `questionary`, or `typer` directly inside `ttassistant.domain` or `ttassistant.application` (AD-1).
- Never invoke external `terraform` or `az` binaries.
- Never write files to disk during parameter collection; parameters are staged strictly in memory.
- Never crash on invalid characters; reject invalid input inline and allow immediate correction.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Happy path guided dialogue | User runs `ttassistant new`, selects subscription `sub-prod`, selects `azurerm_storage_account`, enters `appdata` | Successful collection returning `ProvisioningParameters` object with computed compliant resource name `stappdataprod` | N/A |
| Invalid character in workload name | User enters uppercase or special characters (e.g. `App-Data!`) for storage account | Prompt rejects input inline with message "Invalid name: must match ^[a-z0-9]+$" | Reprompts inline until valid without crashing |
| Name length violation | User enters workload name exceeding max length (e.g. 30 chars for storage account max 24) | Prompt rejects input inline with message "Name exceeds maximum length of 24 characters" | Reprompts inline until valid |
| Non-TTY execution with invalid input | Non-interactive stdin feeds invalid name followed by valid name | Non-TTY fallback prints error message and reads next line | Recovers and succeeds when valid line encountered |
| User cancellation via Ctrl+C / Esc | User presses Ctrl+C or Escape at any prompt | CLI aborts cleanly with exit code 130 and "Aborted." message | Clean `typer.Abort` handling |
| Custom subscription entry | User selects "Other (Enter custom...)" from subscription menu | Prompts for custom subscription name and validates against naming/backend standards | Falls back to default backend rule if not pre-configured |
| Pre-populated CLI flags | User runs `ttassistant new --subscription sub-prod --resource-type azurerm_storage_account --workload appdata` | Skips interactive prompts for provided valid flags and validates parameters | If flag invalid, exits with code 2 / validation error |

</frozen-after-approval>

## Code Map

- `ttassistant/ports/terminal.py` -- Update `TerminalUIPort.prompt_text` signature to accept optional `validate: Callable[[str], bool | str] | None = None`.
- `ttassistant/adapters/terminal_adapter.py` -- Update `RichTerminalAdapter.prompt_text` to wire `validate` callback into `questionary.text(validate=...)` in TTY mode, and execute validation retry loop in non-TTY mode.
- `ttassistant/domain/models.py` -- Define `ProvisioningParameters` Pydantic model (`subscription`, `resource_type`, `workload_name`, `environment`, `resource_name`, `tags`).
- `ttassistant/application/provisioning_flow.py` -- Implement `ProvisioningFlow` orchestrating step-by-step parameter collection, subscription selection, resource type selection, and workload validation.
- `ttassistant/cli.py` -- Register `new` command invoking `ProvisioningFlow` with standards engine from context and optional pre-seeded flags.
- `tests/test_provisioning_flow.py` -- Unit tests for `ProvisioningFlow` using mock `TerminalUIPort` covering valid flows, invalid inputs, and cancellations.
- `tests/test_terminal_prompts.py` -- Unit tests for `RichTerminalAdapter` prompt validation across TTY and non-TTY modes.
- `tests/test_cli_new.py` -- Integration tests executing `ttassistant new` via Typer `CliRunner` and subprocess.
- `tests/test_architecture.py` -- Verify `ttassistant.application` and `ttassistant.domain` maintain AD-1 boundary isolation.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/ports/terminal.py` -- Extend `TerminalUIPort.prompt_text` to support `validate: Callable[[str], bool | str] | None = None`.
- [x] `ttassistant/adapters/terminal_adapter.py` -- Implement validation callback wiring in `RichTerminalAdapter.prompt_text` for interactive Questionary and non-TTY line streams.
- [x] `ttassistant/domain/models.py` -- Add `ProvisioningParameters` Pydantic model capturing user selections and computed attributes.
- [x] `ttassistant/application/provisioning_flow.py` -- Create `ProvisioningFlow` orchestrator guiding subscription, resource type, and workload name collection with inline validation.
- [x] `ttassistant/cli.py` -- Add `new` command wiring `ProvisioningFlow` with CLI options `--subscription`, `--resource-type`, `--workload`, and `--env`.
- [x] `tests/test_terminal_prompts.py` -- Test `prompt_text` validation logic with valid and invalid inputs in TTY and non-TTY modes.
- [x] `tests/test_provisioning_flow.py` -- Unit test `ProvisioningFlow` with mock terminal covering happy path, validation errors, and aborts.
- [x] `tests/test_cli_new.py` -- CLI integration tests verifying `ttassistant new` interactive prompts and flag bypass.
- [x] `tests/test_architecture.py` -- Assert `ttassistant.application.provisioning_flow` contains zero forbidden UI imports.

**Acceptance Criteria:**
- Given a valid `common_standards/` specification, when the developer starts the provisioning flow in the terminal (`ttassistant new`), then the CLI presents progressive prompts for: Target Subscription, Target Resource Type, and Workload Name.
- User input is validated inline against naming rules (character set, min/max length) from `common_standards/` with immediate non-crashing error feedback on invalid characters.
- Users can navigate prompts using arrow keys, Enter, and Tab completion, or exit cleanly using Ctrl+C or Escape without unhandled exceptions.

## Implementation Notes

- Extended `TerminalUIPort.prompt_text` signature with optional `validate: Callable[[str], bool | str] | None = None`.
- Enhanced `RichTerminalAdapter.prompt_text` to pass validation callbacks to `questionary.text` in TTY mode, and run a validation retry loop with error reporting in non-TTY mode. Added clean `KeyboardInterrupt` and EOF abort handling across prompts.
- Added `ProvisioningParameters` Pydantic model in `ttassistant.domain.models` capturing `subscription`, `resource_type`, `workload_name`, `environment`, `resource_name`, and `tags`.
- Implemented `StandardsEngine.compute_resource_name` and `infer_environment` in `ttassistant.domain.standards`.
- Created `ttassistant.application.provisioning_flow.ProvisioningFlow` orchestrating subscription, resource type, and workload name collection with inline live validation against corporate naming rules.
- Registered `new` command on Typer CLI in `ttassistant/cli.py` supporting flags `--subscription`, `--resource-type`, `--workload`, and `--env`, with parameter validation error handling exiting code 2.
- Added test suites in `tests/test_terminal_prompts.py`, `tests/test_provisioning_flow.py`, `tests/test_cli_new.py`, and verified AD-1 hexagonal isolation in `tests/test_architecture.py`. All 122 tests pass.

## Spec Change Log

## Review Triage Log

| Finding | Layer | Verdict | Evidence | Route |
| :--- | :--- | :--- | :--- | :--- |
| Non-TTY prompt_select silently accepts invalid index | blind-hunter | medium | Out-of-range index or text silently picked default. Added retry loop with error reporting in non-TTY mode. | patch |
| Missing Tab completion on prompt_text | blind-hunter | low | Added `completer` parameter to `TerminalUIPort.prompt_text` and forwarded to `questionary.text(completer=...)`. | patch |
| compute_resource_name premature environment suffix avoidance | blind-hunter | medium | Workloads ending with env name without explicit separator (e.g. `contest` with `test`) avoided suffix. Fixed separator checks. | patch |
| infer_environment fallback unverified | verification-gap | medium | Tests only checked subscriptions with explicit env tokens. Added test asserting `infer_environment("corp-hub")` returns `"dev"`. | patch |
| Subscription selection includes wildcard glob tokens | edge-case-hunter | medium | Filtered glob patterns (`*`, `?`, `[`, `default`) from concrete choices in subscription menu. | patch |
| TyperException lacking show attribute in TTAssistantCLI | edge-case-hunter | low | Added safe callable check for `show` and clean exit code fallback. | patch |
| Unverified pre-seeded --env option | verification-gap | medium | Added tests in `test_provisioning_flow.py` and `test_cli_new.py` for valid env override and invalid env code 2 exit. | patch |
| Unverified pre-seeded subscription validation | verification-gap | medium | Added unit and CLI tests asserting invalid subscription raises `ValueError` and exits code 2. | patch |
| Unverified prefix preservation in compute_resource_name | verification-gap | medium | Added unit test asserting workloads already prefixed (e.g. `rg-mygroup`) do not duplicate prefix. | patch |
| Untested ProvisioningParameters empty string validation | verification-gap | medium | Added `TestProvisioningParameters` in `tests/test_standards_models.py` verifying `ValidationError` on empty strings. | patch |
| Application layer boundary test missing ttassistant.adapters/cli | verification-gap | medium | Added `"ttassistant.adapters"` and `"ttassistant.cli"` to prohibited set in `test_application_layer_isolation_ad1`. | patch |
| prompt_select non-TTY invalid input recovery unverified | verification-gap | low | Added `test_prompt_select_nontty_invalid_input_recovery` in `tests/test_terminal_prompts.py`. | patch |

## Design Notes

- `ProvisioningFlow` accepts `TerminalUIPort` and `StandardsEngine` via constructor dependency injection.
- Available subscriptions are populated from `StandardsBundle.backend_rules`, with an "Other (Enter custom...)" fallback choice.
- Available resource types are populated from `StandardsBundle.naming_rules`.
- Workload validation creates a temporary candidate name or checks the naming rule's regex pattern directly, giving instant inline error text.
- If command-line options (`--subscription`, `--resource-type`, `--workload`) are supplied, `ProvisioningFlow` validates them directly and only prompts for missing parameters.

## Verification

**Commands:**
- `./.venv/bin/pytest` -- expected: 100% tests pass including all new unit and integration tests.
- `./.venv/bin/python -m ttassistant new --help` -- expected: Displays command options and help.
- `./.venv/bin/python -m ttassistant new --subscription sub-prod --resource-type azurerm_storage_account --workload validname` -- expected: Validates parameters cleanly and outputs parameters summary.

