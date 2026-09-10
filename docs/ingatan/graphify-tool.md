---
name: graphify-tool
description: graphify code-knowledge-graph tool installed for the AI Project repo — CLI + /graphify skill to query code structure instead of grep
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-31T15:25:41.897Z
---

Installed 2026-08-31 in the AI Project repo (user asked "install graphify"). It's a DEV
tool + Claude Code skill, NOT an app dependency — does not touch requirements/venv or the
Railway production app. Local-only: tree-sitter AST, no API key, nothing leaves the machine.
Verified authentic: PyPI `graphifyy` (double-y) → github.com/Graphify-Labs/graphify (there
are typosquat repos with the same name; the double-y PyPI pkg is the real one).

**Install path used:** `brew install uv` → `uv tool install graphifyy` → `graphify install
--platform claude`. Binaries `graphify` + `graphify-mcp` live in `~/.local/bin` (NOT on PATH
by default — prefix commands with `export PATH="$HOME/.local/bin:$PATH";`). Skill at
`~/.claude/skills/graphify/SKILL.md`; it also created `~/.claude/CLAUDE.md` (3-line pointer).

**Graph built** for this repo via `graphify update .` (deterministic AST, no LLM): output in
`graphify-out/` (graph.json, graph.html, GRAPH_REPORT.md) — 2276 nodes / 5867 edges / 137
communities. `graphify-out/` is gitignored. Community names are file-based placeholders
(deterministic build skipped LLM naming); for LLM-named communities run `/graphify .` in a
FRESH Claude Code session (skill loads at session start, so it was NOT available the session
it was installed).

**Useful CLI (from repo root):**
- `graphify explain "create_purchase_batch"` — node + its callers/callees (great for "who
  calls X"). Proven: instantly found both manual/bot intake entry points.
- `graphify path "A" "B"` — shortest path between two symbols/modules.
- `graphify update .` — rebuild after code changes (fast, no LLM).
Honest scope: helps CODE navigation on this large interconnected repo; does NOT help the
business/data decisions (Kledo contacts, HPP basis, timbang opsi) that dominate the work, and
doesn't cover DB/external-API context. Related: [[penggilingan-beras-project]].
