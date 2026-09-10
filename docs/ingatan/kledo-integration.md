---
name: kledo-integration
description: "Integrasi Kledo finance READ-ONLY — endpoint, field, tool, snapshot; referensi untuk ekspansi"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-13T14:42:24.669Z
---

Integrasi Kledo (akuntansi) READ-ONLY untuk domain keuangan Kantor AI. `app/kantor/kledo.py`. Aktif via env **`KLEDO_API_KEY`** (PAT finance; berbeda dari GAJIHUB_API_KEY yang HR-only). Host: `https://pthadimulyautama.api.kledo.com/api/v1`. Gate: Direksi (admin) ATAU grant RBAC baca `keuangan` (mis. Elfira).

**TOOL (live, 5):** `tagihan_kledo` (purchaseInvoices — total belum lunas + daftar jatuh-tempo-terdekat) · `faktur_kledo` (invoices/piutang) · `kontak_kledo` (contacts) · `akun_kledo` (accounts) · `neraca_kledo` (balanceSheet — total aset/hutang/modal RESMI). Terdaftar di agen Kantor + router domain keuangan + rbac `_KLEDO_READ`. **Belum ada tool tulis** (tahap awal).

**ENDPOINT finance (data):** `/finance/{accounts,invoices,purchaseInvoices,contacts,products,quotes}` — respons `{success,data:{...pagination..., data:[items]}}` (item di `data.data`). Field transaksi: `ref_number`, `contact.name`, `amount_after_tax` (total), **`due`** (sisa; 0=LUNAS), `due_date`, `status_id`. Kontak: `name,company,receivable,payable`. Akun: `ref_code,name,balance`.

**ENDPOINT report ada di `/reportings/*`** (BUKAN `/finance/reports` yang 404):
- `/reportings/balanceSheet?date=YYYY-MM-DD` → `{date:{assets:{total,data}, liabilities_equity:{total,data:[Liabilitas Jangka Pendek/Panjang, Perubahan Modal]}}}`.
- `/reportings/agedPayable?date=` & `agedReceivable` → aging per kontak (`due` bucket -2..4).
- `/reportings/profitLoss`, `/reportings/cashFlow`, `/reportings/trialBalance`, `/reportings/generalLedger`, `/reportings/receivablePayable` (butuh param, 400 tanpa).
- Spec OpenAPI: `https://pthadimulyautama.api.kledo.com/docs/api-docs.json`.

**SNAPSHOT (2026-08-13):** Total Aset Rp 22,93 M · **Total Hutang (liabilitas) Rp 8,996 M** (semua jangka pendek) · Total Modal Rp 13,93 M · tagihan invoice belum lunas Rp 1,78 M (27) · ledger payable Rp 8,85 M. → "total hutang" resmi = **neraca**, bukan invoice-due.

**BERIKUTNYA:** tool laba-rugi/aging/arus-kas (pola sama); **webhook** untuk proaktif (notif tenggat/pembayaran) di fase proaktif — app sudah punya server FastAPI utk endpoint webhook. Related: [[no-redundancy-kledo]], [[gajihub-kledo-integration]], [[kantor-arsitektur-terintegrasi]], [[kantor-proaktif]].
