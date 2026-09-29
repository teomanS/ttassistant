"""Domain layer for ttassistant.

Strictly pure business logic, models, policy evaluation, and diff generation.
Zero terminal UI dependencies (no rich, questionary, typer, prompt_toolkit),
zero external process execution, and zero filesystem writes (per AD-1).
"""

