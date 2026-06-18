# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VitePress documentation site ("Career Hub") for interview preparation materials. Content is in Chinese, covering AI/Agent engineering, Java backend, system design, and interview retrospectives.

Deployed with base path `/agent-docs/`.

## Commands

```bash
npm run docs:dev      # Dev server with hot reload
npm run docs:build    # Production build
npm run docs:preview  # Preview production build locally
```

## Architecture

- `docs/` — VitePress content root
  - `.vitepress/config.mjs` — Site config (nav, sidebar, mermaid plugin)
  - `prep/` — Interview prep articles (AI Agent, Java, system design, projects)
  - `resume/` — Resume content
  - `retrospectives/` — Interview retrospective notes
- `modify_ai_agent.py` — One-off Python script for transforming `docs/prep/ai-agent.md` (inserts TOC, removes example code blocks, adds new chapters)

## Key Details

- Uses `vitepress-plugin-mermaid` for diagram rendering in markdown
- Config wraps `defineConfig` with `withMermaid()` — maintain this pattern when modifying config
- Content language is Chinese; keep all documentation in Chinese
- Sidebar structure is defined per-section in config.mjs — update it when adding/removing pages
