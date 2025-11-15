# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Game recommendation system using IGDB API, AI-based similarity matching, Discord notifications, and Streamlit dashboard. Currently ships only the architecture skeleton (Typer CLI, Discord, Streamlit). Tech stack: Python 3.11+, uv, typer, Streamlit, SQLite3.

## Where To Look

- Project goals & structure → `.serena/memories/project_overview.md`, `architecture_structure.md`
- Coding rules & formatting → `.serena/memories/style_and_conventions.md`
- Commands & completion checklist → `.serena/memories/suggested_commands.md`, `post_task_checklist.md`

## Minimal Workflow

1. Read the relevant Serena memories before touching code; they contain the authoritative instructions for every layer.
2. Follow the commands referenced there (e.g., `uv run ruff check`, `uv run pytest`) and validate against the completion checklist.
3. If you discover new conventions or workflows, update the appropriate Serena memory first.

## Key Constraints

- **Layering:** Core (pure domain logic) → Infra (IGDB/Discord/AI/SQLite abstractions) → CLI/Web. Do NOT access external APIs or SQLite directly outside infra layer.
- **Environment:** Copy `.env.example` to `.env` and populate IGDB/Discord/AI credentials. Never commit credentials.
- **Skeleton State:** Unless explicitly tasked, limit work to scaffolding, configuration, or documentation—do not implement product logic.
