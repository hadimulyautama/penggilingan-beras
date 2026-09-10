---
name: agentic-layer
description: "How the AI works in the rice-mill system — Haiku parser vs Sonnet agent layer, and the controlled-write pattern"
metadata: 
  node_type: memory
  type: project
  originSessionId: 62a9df0a-25aa-4e6c-b138-e99a93884574
  modified: 2026-08-10T15:48:22.754Z
---

The system has TWO AI layers (see [[penggilingan-beras-project]]):

1. **Parser (per-message, deterministic):** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`, `settings.claude_model`) with FORCED tool-use — 1 message = 1 structured extraction → 1 service call. This is `app/ai/base.py` + domain `nlp.py` parsers. Business logic lives in services, not the model.

2. **Agent (agentic loop, added 2026-07-05):** Claude Sonnet 5 (`settings.agent_model`) in `app/ai/agent.py`. Runs as the LAST-RESORT fallback in all 3 bots when no deterministic handler matches. Can call multiple READ tools (stock summaries, G1/G2 status, finished goods, packaging, pending tasks, financials) then synthesize an answer.

**Controlled-write pattern (important):** the agent NEVER executes writes itself. It calls `usulkan_perintah` → returns `AgentReply(propose_command, propose_summary)`. The bot stores it (`session.agent_command`, stage `awaiting_agent_write`), asks the user to confirm (`ya`/`batal`), and on confirm re-runs the proposed command through the SAME deterministic handler chain (`_try_command_handlers` in admin, `_try_operator_commands` in gudang1, `_try_g2_commands` in gudang2) via an `agent_flow.agent_confirm_pending` dispatch callback. So writes always go through tested deterministic paths.

**Role gating:** `run_agent(financial=...)` — financial tools + money figures only when `financial=True` (staff/admin, via `can_see_financials`). Operators never see harga/HPP. Shared flow: `app/bots/agent_flow.py`.

**Why:** user asked to "naikkan ke pola agentic" with choices: read+write terkontrol, Sonnet 5, all bots. Verified with live tests (read synthesis, write-propose-then-confirm executes, operator financial refusal).

**KANTOR bot triage layer (added 2026-08-10, cost):** the Kantor AI bot ([[kantor-ai-project]]) previously sent EVERY message to Sonnet 5 (`agent_model`) — no cheap tier. Added `app/kantor/triage.py`: a Haiku (`settings.miniapp_model`) forced-tool classifier (`putuskan` → `perlu_agen` bool + `balasan`) called in `bot.handle_message` BEFORE `run_kantor_agent`. Pure smalltalk (greetings/thanks/acknowledgments) → Haiku answers directly & saves the turn to riwayat; anything needing data/tools/actions or referencing prior context, or any doubt → escalate to Sonnet (conservative default TRUE). On any Haiku error → escalate (never blocks). Owner chose Haiku over Gemini Flash: at ~tens-of-msgs/day the rupiah difference is ~$1/mo, not worth a 2nd provider + free-tier rate limits. (The bot's big cost driver is the 42-tool ~8–10k-token prompt prefix, already prompt-cached.)

**Model policy per surface (decided 2026-07-05):** BOT chat = Sonnet (`claude_model` + `agent_model`), because Haiku "sering tidak nyambung" — misread intent on conversational messages. MINI APP = Haiku (`settings.miniapp_model = claude-haiku-4-5`), reserved for light/structured tasks (quick-entry parsing) where Haiku is cheap and adequate; Mini App is mostly non-AI (forms/dashboards → deterministic API). Also added a single Sonnet intent ROUTER (`app/ai/router.py`, `route_domain`) replacing the ~15-parser cascade in the admin bot: one classify call → the matching domain handler → deterministic answer; falls back to full chain / agent. Operator bots (gudang1/gudang2) still use the old cascade — router rollout pending. Key principle reaffirmed: accuracy of numbers (stok/HPP) comes from routing to deterministic SQL functions, NOT the model — the model only classifies + extracts.
