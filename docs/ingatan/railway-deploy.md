---
name: railway-deploy
description: "Production is deployed on Railway — project, URL, how to redeploy, billing caveat"
metadata: 
  node_type: memory
  type: project
  originSessionId: 62a9df0a-25aa-4e6c-b138-e99a93884574
  modified: 2026-08-02T16:44:50.147Z
---

The rice-mill system ([[penggilingan-beras-project]]) is deployed to **Railway** (2026-07-05), running 24/7 — the laptop/local run is no longer the live system.

- **Railway account:** wahidnurhani20@gmail.com. **Project:** `penggilingan-beras` (id `5518c07b-e1c9-4876-ae5c-89ac304ca476`), environment `production`.
- **Services:** `Postgres` (postgres-ssl:18) + `penggilingan-beras` (app, Dockerfile build, single replica).
- **Public URL:** https://penggilingan-beras-production.up.railway.app — `/health`, `/api` (Mini App launch page). All 3 bots (@selepan_bot, @polesan_bot, @hmuadmin_bot) poll from Railway; menu button "Buka Dashboard" → `/api` set on all three.
- **Env vars set on Railway** (via CLI, secrets via `--set-from-stdin`): DATABASE_URL=`${{Postgres.DATABASE_URL}}`, ANTHROPIC_API_KEY, CLAUDE_MODEL=claude-sonnet-5, AGENT_MODEL, MINIAPP_MODEL=claude-haiku-4-5, BOT_*_TOKEN (×3), ADMIN_TELEGRAM_ID=1352846912, ADMIN_NAME, APP_TIMEZONE. Railway DB started empty; master + admin auto-seeded on boot.

**Redeploy — GitHub auto-deploy is CONNECTED (verified 2026-07-05):** the app service source is the GitHub repo `hadimulyautama/penggilingan-beras` branch `main` (connected via `railway service source connect`). A push to `main` auto-triggers build + deploy. Repo is PRIVATE; Railway GitHub App has access. Migrations run automatically on boot (`docker/entrypoint.sh` → `alembic upgrade head`).

**GOTCHA (2026-08-02): `railway up` is EPHEMERAL when GitHub deploy is connected.** A local `railway up` deploy works, but the NEXT GitHub-triggered rebuild — including a *variable change* (adding an env var auto-redeploys from GitHub `main`) — OVERWRITES it with whatever is on `main`. Symptom seen: `railway up` applied migration 0016 (stamped DB), then a var-add redeploy pulled old `main` (no 0016 file) → `alembic: Can't locate revision '0016_kantor'` + feature missing. FIX: always `git push origin main` for a durable deploy; treat `railway up` only as a throwaway smoke-test. The `mcp` service deploys from the SAME repo/main, so a main push redeploys BOTH services.

**Services now (2026-08-02): 4 bots** — gudang1/@selepan_bot, gudang2/@polesan_bot, admin/@hmuadmin_bot, **kantor/@hmu_hermes_bot** ('Kantor AI'). Plus 2nd service `mcp`. See [[kantor-ai-project]], [[mcp-server]].

**Critical:** only ONE poller per bot token. Do NOT run the laptop uvicorn while Railway is live (409 conflict). `railway.json` pins `numReplicas: 1`.

**Billing caveat:** Railway removed the free tier; the earlier "Free plan resource provision limit exceeded" was resolved by deleting two old test projects (`Ai-Agent HMU`, `exemplary-adventure`). Sustained 24/7 running likely needs the Hobby plan (payment method) — watch trial credit.
