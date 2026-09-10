---
name: bulk-llm-audit-cost
description: "Bulk LLM/OCR Drive jobs share the bot's Anthropic key and can trip the monthly spend limit, taking the whole bot offline"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-12T00:57:41.451Z
---

On 2026-08-12 a full Drive file audit (~776 of 1533 files processed: Haiku classification + OCR of many images/scanned PDFs) exhausted the account's monthly Anthropic API budget. The API returned HTTP 400 "You have reached your specified API usage limits. You will regain access on 2026-09-01 00:00 UTC." This **took the production Kantor AI bot offline** (same ANTHROPIC_API_KEY), not just the audit.

**Why:** OCR in `app/kantor/ocr.py` uses `settings.agent_model` (Sonnet/Opus-tier, expensive) and was called on hundreds of image/scanned-PDF files in one batch. Bulk offline jobs and the live bot draw from the SAME API account/spend cap.

**How to apply:**
- Before any bulk LLM/OCR job over Drive, estimate cost and check remaining monthly budget in the Anthropic Console; cap the batch (e.g. process N files/run) or spread across days.
- Use Haiku (`settings.miniapp_model`) for OCR/classification in bulk jobs, not `agent_model`.
- The fix when the cap is hit: raise the monthly spend limit in Anthropic Console (Billing → Limits) — access restores immediately; otherwise it resets on the 1st of next month.
- Consider graceful degradation: catch the 400 usage-limit error in the bot and reply with a friendly "layanan AI sedang mencapai batas" instead of failing silently.

Related: [[kantor-ai-project]], [[agentic-layer]], [[drive-audit-subfolder-lesson]]
