# Repository Guidelines

## Overview
This repository currently ships only the architecture skeleton for IGDB-based recommendations (Typer CLI, Discord, Streamlit). Full details for the tech stack, directory purposes, and validation flow live in Serena memories; treat them as the canonical handbook and keep this document slim.

## Where To Look
- Project goals & structure → `project_overview`, `architecture_structure`
- Coding rules & formatting → `style_and_conventions`
- Commands & completion checklist → `suggested_commands`, `post_task_checklist`

## Minimal Workflow
1. Read the relevant memories before touching the tree; they contain the authoritative instructions for every layer.
2. Follow the commands referenced there (e.g., `uv run ruff check`, `uv run pytest`) and record results in PRs instead of repeating guidance here.
3. If you discover new conventions or workflows, update the appropriate Serena memory first and only then decide whether AGENTS.md needs an additional pointer.

## Expectations
Keep AGENTS.md restricted to high-level orientation so we avoid dual maintenance. When in doubt about requirements, reference the memories or ask for clarification rather than inventing new patterns. Unless explicitly tasked, do not implement product logic—limit work to scaffolding, configuration, or documentation to preserve the skeleton state.
