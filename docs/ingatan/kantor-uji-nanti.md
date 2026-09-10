---
name: kantor-uji-nanti
description: Daftar uji Tahap 0 (pengaman biaya) & Tahap 1 (RBAC) — dijalankan saat API Anthropic nyala lagi + bot di-deploy
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-13T01:36:24.734Z
---

Yang WAJIB diuji nyata begitu **limit API dinaikkan + `railway up`**. (Unit-test lokal 39 sudah hijau; ini uji runtime/integrasi.)

## A. Tahap 0 — pengaman biaya (langsung setelah deploy)
1. **Kill-switch alur**: Direksi ketik `matikan ai` → bot minta konfirmasi → `ya` → "dimatikan". Lalu kirim pesan biasa → harus dapat **pesan degradasi** ("layanan AI dimatikan sementara"). Lalu `nyalakan ai` → `ya` → nyala → pesan biasa jalan lagi.
2. **Non-Direksi** ketik `matikan ai` → ditolak ("hanya Direksi").
3. **Biaya via bahasa natural**: "berapa biaya AI bulan ini?" / "sisa budget?" → tool `status_biaya` jawab spend + cap $50.
4. **Pencatatan**: setelah beberapa interaksi → tabel `kantor_llm_usage` terisi (pemanggil/tokens/biaya); spend naik di `status_biaya`.
5. **Ambang cap**: sementara set `spend_cap_usd_bulan` sangat kecil (mis 0.01) → LLM berhenti + pesan degradasi `BatasBiayaLLM`; kembalikan ke 50.
6. **Degradasi limit asli**: saat masih kena limit Anthropic, pastikan bot **membalas sopan**, bukan diam.

## B. Tahap 1 — RBAC (SETELAH onboarding + wiring enforcement; wiring BELUM dibuat)
7. **Onboarding**: tiap orang chat bot sekali → catat Telegram ID → `rbac.tetapkan_role`:
   Wahid/Miftah=`direksi`(+pegawai) · Muthia=`hr_manager`+pegawai · Elfira=`office_manager`+`staff_hr`+`staff_legal`+pegawai · Kurniawan=`legal_officer`+pegawai · Eka=`staff_ops`+`staff_hr`+`staff_legal`+pegawai · Komisaris×3=`komisaris`. Verifikasi `daftar_role_user`.
8. **Deny nyata Eka**: minta data keuangan/gaji/folder IT → ditolak/tanpa tool.
9. **Boleh Eka**: presensi/cuti (hr write), arsip, penjualan, operasional.
10. **Muthia**: gaji ✓ · sengketa ✗ · keuangan ✗.
11. **Elfira**: keuangan ✓ · gaji(read) ✓ · folder_it(read) ✓ · sengketa(read) ✓ · tulis gaji ✗.
12. **Kurniawan**: legal ✓ · sengketa(write) ✓ · gaji ✗ · keuangan ✗.
13. **Komisaris**: laporan + knowledge umum ✓ · email/aksi ✗ · brankas ✗.
14. **Operator**: input/edit/revert/hapus entry SENDIRI, gudang sendiri; domain kantor ✗.
15. **Knowledge filtering**: Eka cari → TAK muncul fakta gaji/legal/sengketa (perlu tag domain di knowledge dulu).
16. **Drive scope** (`rbac_map.domain_folder`): Eka buka/pindah file di folder keuangan/IT/sengketa → ditolak.
17. **Email scope** (`rbac_map.domain_mailbox`): Eka baca finance@ → ditolak; wahidnurhani@ (pribadi) → hanya Direksi.
18. **Approval berjenjang**: aksi berdampak Eka → tombol ke atasannya (Elfira/Muthia), bukan langsung Direksi.
19. **Deprovisioning**: `rbac.cabut_role` → akses hilang seketika.

## C. Deploy
20. `railway up` → cek startup (heartbeat, poller), alembic head=`0021_kantor_rbac`, seed idempoten (tak dobel).

**Catatan:** item 8–19 butuh **wiring enforcement** (gate tiap tool pakai `rbac.boleh` + `rbac_map`) yang **belum dibuat** — komponennya (scope-checker + peta) sudah ada & unit-tested. Related: [[kantor-org-rbac]].
