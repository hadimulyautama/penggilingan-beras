---
name: kantor-email-gmail
description: "Kantor AI agent manages 3 Google Workspace mailboxes (finance@/admin@/wahidnurhani@) via Service Account + Domain-wide Delegation; send is gated, admin-only, no permanent delete"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-11T03:09:22.353Z
---

Kantor AI agent MANAGES EMAIL for 3 company mailboxes — **finance@, admin@, wahidnurhani@hadimulya.com** (part of [[kantor-ai-project]]; on Google Workspace after [[company-website-project]]'s sibling email migration Zoho→Google, 2026-08-10). Module `app/kantor/mail_gmail.py` (replaces the Zoho `surel.py` backend; code falls back to Zoho if `GMAIL_SA_JSON` absent).

**Wewenang ("Kelola penuh (aman)", ADMIN-only):** read/triage (`baca_email` with Gmail-style `kueri`, `cari_email`, `baca_email_isi`) + draft (`draft_email` → saved as Gmail draft, does NOT send) + organize reversibly (`arsip_email`, `tandai_dibaca_email`, `label_email`) — all direct. **Send (`kirim_email`) goes through the human button gate** ([[agentic-layer]]): `mail_gmail.usul_kirim` → `persetujuan.buat_pending(jenis="email_kirim", payload{mailbox,ke,subjek,isi,balas_ke_id})` → owner taps ✅ → `_lakukan` → `mail_gmail.kirim`. **No permanent delete** (scopes are only `gmail.modify` + `gmail.send`). Every email tool requires `mailbox` arg and is refused for non-admins.

**Personal mailboxes added (2026-08-11):** TWO personal Gmails — **wahidnurhani20@gmail.com** (alias "pribadi", the primary) and **wahidnurhani@gmail.com** — are now managed mailboxes (5 total), scope "kelola penuh". Personal Gmail CANNOT use DWD (Workspace-only), so each uses its own **OAuth user credentials**: `mail_gmail._svc` branches — if the mailbox is in `_pribadi_map()`, build `google.oauth2.credentials.Credentials` from that account's refresh token + OAuth client `GMAIL_OAUTH_CLIENT_ID/SECRET` (falls back to `GDRIVE_OAUTH_*`). Multi-account env scheme: `GMAIL_PRIBADI_EMAIL`/`GMAIL_PRIBADI_REFRESH_TOKEN` (acct 1) + `GMAIL_PRIBADI2_EMAIL`/`GMAIL_PRIBADI2_REFRESH_TOKEN` (acct 2), up to `GMAIL_PRIBADI4_*`. Both refresh tokens minted from the SAME OAuth client via Playground (sign in as each account). NOTE short-name collision: "wahidnurhani" matches both wahidnurhani@hadimulya.com and wahidnurhani@gmail.com — use full addresses; alias "pribadi" = the -20 account. The OAuth client + consent were set up in the `kantor-mail` GCP project (Google Auth Platform: External + Testing, test users wahidnurhani20@ & wahidnurhani@gmail.com, scopes gmail.modify+gmail.send, a Web client with redirect `https://developers.google.com/oauthplayground`); the refresh token was minted via OAuth Playground ("use your own OAuth credentials"). `daftar_mailbox()` appends the personal email so ALL tools + proactive pollers cover it. Verified: read its inbox (Bank Mandiri statement, Railway/Stripe receipt). **All mailboxes (incl. personal): OTP/login/security emails are NEVER auto-archived** (owner rule 2026-08-11 — enforced in `rapi._SYS`).

**Auth = Service Account + Domain-wide Delegation** (impersonation, `.with_subject(mailbox)`) for the 3 Workspace mailboxes:
- SA: `kantor-mail-agent@kantor-mail.iam.gserviceaccount.com`, **Unique/Client ID `106679404201770058641`**, Google Cloud project `kantor-mail`, org `hadimulya.com` (**org id `152066329883`**).
- DWD authorized in Admin Console (Security → API controls → Domain-wide delegation): that Client ID + scopes `https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/gmail.send`.
- Creds env on `penggilingan-beras` service: `GMAIL_SA_JSON` (SA key JSON, or base64) + `GMAIL_MAILBOXES` (comma list = also the security allow-list). Verified live 2026-08-10 (read inbox of all 3; deploy `railway up` clean).

**Gotcha — org "secure by default" blocks SA keys:** constraint `iam.managed.disableServiceAccountKeyCreation` (managed org policy) denies creating SA keys. To create/rotate a key: grant admin@ **Organization Policy Administrator** (`roles/orgpolicy.policyAdmin`), set the policy to **Not enforced** briefly, create the JSON key, then **restore Policy source = "Google-managed default"** (NOT "Inherit parent's policy" — at the org root that leaves it Not enforced). Existing keys keep working after re-enabling; the effective-status display lags ~1 min after changing it. Same admin@ account is Workspace super-admin and did the DWD auth.

Related admin-only sensitive integration: [[gajihub-kledo-integration]]. Reframe on how the agent "remembers": [[kantor-otak-perusahaan]].
