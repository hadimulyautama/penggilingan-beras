---
name: gajihub-kledo-integration
description: "Kantor AI ↔ GajiHub (HR/payroll) REST API — read-only, admin-only; served on the Kledo domain"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-10T04:36:17.708Z
---

GajiHub and Kledo are one company/group — GajiHub (HR/payroll) is **served on the Kledo domain**. The company's tenant API host is `https://pthadimulyautama.api.kledo.com`. This is the integration the user meant by "sambung GajiHub" (part of [[kantor-ai-project]]; aligns with [[no-redundancy-kledo]] — summarize, don't recompute).

**Auth:** `Authorization: Bearer <token>` where token is a GajiHub Personal Access Token (prefix `gajihub_pat_...`), generated in Kledo → Integrasi → "Buat Token API Key". Stored as Railway env `GAJIHUB_API_KEY` on the `penggilingan-beras` service (owner pasted it 2026-08-10). Base URL `https://pthadimulyautama.api.kledo.com/api/v1` (override via `GAJIHUB_BASE`).

**Discovering endpoints (the docs are a Scalar/JS SPA — WebFetch & the in-app browser can't read it):** the OpenAPI spec is at `GET /documentation/scalar/spec?app_code=hr` with header `X-App: hr` (found by reading the doc HTML's fetch config). That returns the full HR OpenAPI JSON — parse `paths`. Endpoints are under `/hr/...`.

**Module `app/kantor/gajihub.py`** (read-only, NO write tools) — `terkonfigurasi()`, `_get(path, params)` (Bearer), tools gated **admin-only** via `role` threaded from the agent (staff → refused, since salary/PII is sensitive). Three agent tools:
- `karyawan_gajihub` → `GET /hr/employees/pagination` (verified: 27 active; fields id/code/name/is_active/finance_contact_id).
- `payroll_gajihub` → `GET /hr/salarySlips/pagination` (verified: 3 periods; fields incl period/position_income/position_deduction). Salary slips = payroll periods; per-employee detail via `/hr/salarySlips/{id}`.
- `cuti_gajihub` → `GET /hr/leaves/all/employees` — **returns 200 but EMPTY** for all year/month params tried; leave data must live in a different endpoint (candidates seen in spec: `/hr/leaves/annualLeaves`, `/hr/leaves/permitLeaves/employees/balanced`, `/hr/specialLeaves`). TODO: find the right leave/quota endpoint for "sisa cuti si X".

**Overtime/lembur approval via Telegram — added 2026-08-10 (CORRECTED):** in THIS company's GajiHub, employee overtime is recorded as **attendance-log approvals** ("Mulai Lembur"/"Selesai Lembur"), NOT the `/hr/approvals` (leave) system and NOT `/hr/overtimes` (which has no status field). The `/hr/approvals` path I built first was wrong for lembur and was **removed** (owner: "cara lama di bot hapus saja") — `gajihub.setujui/tolak` (hr), `_menunggu`, `_urai_id` deleted; approval is presensi-only now.
- **List:** `GET /hr/attendanceLogs/approval/pagination?hr_attendance_log_status_id=1&date_started=…&date_ended=…` (status 1 = "Menunggu Persetujuan"; 2=Disetujui, 3=Ditolak — from `/hr/references/approvalStatuses`). `date_started`/`date_ended` are REQUIRED. Row has nested `hr_employee.name`, `hr_attendance_log_type.name` (Mulai/Selesai Lembur), `datetime`, `hr_attendance_location.name`, `note`. **DEFAULT WINDOW = current month only** (owner: "batasi ke bulan yang sama") — `date_started = 1st of month`; this matched the GajiHub UI exactly (4 pending: Eka ×2, Elfira ×2 for Aug). A 90-day window surfaced a 14-item backlog (June) that the UI hides — avoid.
- **Approve/reject:** `PATCH /hr/attendanceLogs/approve` and `/hr/attendanceLogs/reject`, body `{"ids": [<int>]}` — **`ids` MUST be a JSON array** (confirmed via bogus id → 400 "Ids.0 tidak valid" = format OK, id not found).

Kantor AI wiring: read tool `pengajuan_gajihub` (lists current-month pending presensi/lembur, admin-only); write tools `setujui_pengajuan(id)` / `tolak_pengajuan(id, alasan)` go through the human button gate ([[agentic-layer]]) — jenis `gajihub_setujui`/`gajihub_tolak` in `persetujuan._lakukan` → `gajihub.setujui_presensi/tolak_presensi`. Owner approves/rejects lembur from Telegram; writes back to GajiHub. NOT YET: proactive push (poller) when a new submission arrives — currently on-demand. Cuti approval: the `/hr/approvals` system may serve leave (untested/empty here) — re-add only if needed.

Other spec resources for later: `/hr/attendances/pagination` (absensi), `/hr/salaryComponents`, `/hr/employeeTerminations`, `/hr/timetracker/*`, plus Kledo Finance API (`/finance/*`) on the same host+token for the future CFO/Kledo work.
