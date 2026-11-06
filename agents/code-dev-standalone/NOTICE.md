# Source and modification notices

This bundle includes adapted files from Anthropic's feature-dev project:
https://github.com/anthropics/claude-plugins-official/tree/fb370c077e8904ce5a0fbe5c89084f5171863c1f/plugins/feature-dev

Upstream files: agents/code-explorer.md, agents/code-architect.md,
agents/code-reviewer.md. The upstream Apache License 2.0 is included verbatim
as LICENSE. Keep this notice and LICENSE when redistributing the bundle.

Modified 2026-11-06 for CODEdev:

- Renamed the three agents with an ax- prefix to avoid name collisions.
- Replaced legacy tool lists with Read, Grep, Glob for local read-only analysis.
- Preserved the original specialist instruction bodies and Sonnet selection.
- Appended CODEdev boundaries, explicit review scope, and Wiki evidence mapping.
- Reconstructed the upstream commands/feature-dev.md workflow as ax-code-dev,
  adding a separate Wiki phase after Discovery and before Codebase Exploration.
- Adapted CODEdev agents/code-dev-wiki/wiki-explorer.md into a registered agent.
- Added standalone installation, reproducible packaging, and usage documentation.

This is a CODEdev adaptation, not an official Anthropic distribution.
