---
name: kantor-org-rbac
description: Struktur organisasi PT HMU & pemetaan role→domain→persetujuan — dasar RBAC Kantor AI multi-agen
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-13T02:44:37.872Z
---

Struktur organisasi (dasar desain RBAC Kantor AI multi-agen), dikonfirmasi 2026-08-12:

- **Direksi ×2**: **Ahmad Wahid Nurhani** (Direktur Utama merangkap Direktur Keuangan, = user) & **Miftah** (Direktur Operasional). Akses penuh semua domain + kelas istimewa/global; **approver tertinggi** (salah satu cukup).
- **Muthia — HR Manager**: domain **HR/payroll** (GajiHub, gaji, cuti/lembur). Approver staf HR. Staf HR = **Elfira & Eka**.
- **Elfira — Office Manager**, merangkap Manager **Marketing/Penjualan, Akuntansi & Keuangan, Arsip, Sekretaris** + **staff HR** + **staff Legal**. Owner banyak domain (termasuk **Keuangan** sensitif). Approver **Eka**.
- **Legal Officer ×1 (Kurniawan Setiadi)**: domain **Legal** penuh — kontrak, legalitas, perjanjian, **TERMASUK berkas sengketa/Rajawali** (dikonfirmasi). Staf Legal = **Elfira & Eka**. Aksi berdampak → Direksi.
- **Eka — Staff**: **operasional + penjualan + Arsip + Sekretaris + staff HR + staff Legal**. Lapor ke Elfira (& Muthia utk HR). 

**NAMA LENGKAP (roster Drive per 25 Juli 2026):** Wahid = **Ahmad Wahid Nurhani** (Dirut+Keuangan) · Miftah = **Ahmad Tsalits Miftah Nurhani** (Dir Operasional) · Muthia = **Nurul Mutia Diansyah** (HR Manager) · Elfira = **Elfira Geya Ananda** (Office Manager) · **Kurniawan Setiadi** (juga tertulis "Setiyadi") (Legal Officer) · Eka = **Eka Wahyu Nugrahani** (Staff Operasional).
Selain itu ada **Komisaris ×3**: Nurhadi, Ninik Mulyani, Ahmad Isnaini Shidqi Nurhani — role **`komisaris` = read-only oversight** (laporan + knowledge umum; TAK lihat brankas, TAK bisa aksi). Identitas akun (Telegram ID tiap orang) masih perlu **onboarding** sebelum user↔role bisa diisi.

**Operator** juga pakai agent tapi MINIMAL: input data operasional + edit/revert/hapus **entry SENDIRI**, terikat **gudang sendiri** (g1/g2, tak lintas — sesuai `common.py` eksisting). Via mini-app tombol cepat + chat. Role `operator`, grant `operasional=write` (scope own-entry+gudang ditegakkan lapisan operasional eksisting).

**Katalog role (di-seed 2026-08-12):** pegawai(base), direksi, komisaris, hr_manager, office_manager, legal_officer, staff_hr, staff_legal, staff_ops, operator, it_manager(kosong). Grant per role tersimpan di tabel `kantor_grant`. Multi-hat via `kantor_user_role` (mis. Elfira = office_manager+staff_hr+staff_legal+pegawai; Eka = staff_ops+staff_hr+staff_legal+pegawai).

**Cakupan pengguna agen Kantor AI = tingkat kantor/manajemen saja** (Direksi, Muthia, Elfira, Legal Officer, Eka). **Operator pabrik TIDAK pakai agen** — cukup mini-app Telegram (bot pabrik yang sudah ada). Jadi RBAC ini tak perlu menangani operator.

**Elfira & Eka ≈ akses hampir universal** (Manager/staff lintas HR, Legal, Keuangan, Arsip, Sekretaris, Marketing, Ops). Model izin = **gabungan grant per orang**.

**IMPLIKASI PENTING:** karena 2 orang kunci sudah lintas-domain, **silo domain memberi sedikit isolasi bagi mereka**. Kontrol nyata bergeser ke: (1) **sub-scope sensitif** yang dibatasi walau mereka "di dalam" domain — mis. **gaji** (HR), **berkas sengketa Rajawali** (Legal), **eksekusi/approval keuangan**; (2) **wewenang persetujuan / segregation-of-duties** (siapa boleh MENYETUJUI, bukan hanya membaca); (3) **audit** (karena akses luas, log jadi kontrol utama).

**SUB-SCOPE SENSITIF (dikonfirmasi 2026-08-12):**
- **Lihat angka GAJI** → hanya **Muthia & Elfira** (Direksi inherent penuh). Eka = staff HR TANPA akses gaji (hanya presensi/cuti/lembur). Jadi HR punya 2 lapis: payroll (Muthia/Elfira) vs administrasi (Eka).
- **Berkas SENGKETA (Rajawali)** → **Direksi, Legal Officer, Elfira, Eka**. Muthia TIDAK.
- **Folder IT** → hanya **Direksi + Elfira**. (Muthia, Legal Officer, Eka TIDAK.) Saat ini IT di-handle Wahid (Direksi); **KELAK ada role IT Manager** sbg pemilik domain IT → **registry role harus extensible** (tambah role/orang tanpa desain ulang).
- **APPROVAL KEUANGAN (bayar/transfer)**: sistem sekarang **maker–checker**; **maker = semua staff bisa**; **approve dilakukan DI SISTEM BANK**, pemegang = **Wahid (Direksi) + Muthia**. → **Agen TIDAK PERNAH mengeksekusi pembayaran**; peran agen = sisi maker saja (siapkan/catat/usul/ingatkan). Eksekusi = di bank, oleh Wahid+Muthia. (Selaras aturan: transfer dana bukan wewenang agen.)

**PERSETUJUAN DIREKSI (dikonfirmasi):** cukup **salah satu** Direksi menyetujui (tak wajib keduanya). Wahid = **Direktur Utama merangkap Direktur Keuangan** (sebab itu ia + Muthia pemegang approval bank).

**PRINSIP WAJIB — role fleksibel & data-driven (dikonfirmasi):** organisasi akan bertambah manager/staff/role ke depan. Maka:
- Role, orang, grant (alat+scope+brankas), dan **garis pelaporan** disimpan sebagai **DATA** (tabel/registry), bukan hardcode.
- **Approval hierarchy relatif-role**: "staf → manager-nya → Direksi" di-resolve dari org-tree di registry, bukan nama orang di kode → manager/staf baru langsung masuk tanpa ubah kode.
- Domain/scope didefinisikan lepas dari orang; orang→role, role→grant (komposisi, mendukung multi-hat).
- Tambah/ubah/cabut = edit data (insert/update/disable), tanpa deploy ulang. Ada **role template** (mis. base "Staff") utk default masuk akal.

**Persetujuan berjenjang (dikonfirmasi):** staf → Manager domainnya → (aksi besar) Direksi. Manager & Legal → Direksi.

**Catatan kontrol (segregation of duties):** Elfira memusatkan Keuangan + Arsip + Marketing + Sekretaris. Untuk aksi keuangan berdampak, pertimbangkan approval ke Direksi (bukan swa-setujui) agar ada pemisahan pencatat vs penyetuju.

**Implikasi routing eskalasi agen otonom:** aksi Arsip Eka → Elfira; aksi HR → Muthia; materi Legal/Rajawali → Legal Officer/Direksi; lintas-domain/istimewa → Direksi.

**STATUS BUILD (2026-08-12, belum commit/deploy):**
- **Tahap 0 (pengaman biaya) SELESAI**: `app/ai/guard.py` (kill-switch, spend-cap, catat pemakaian, degradasi anggun), 8 call-site LLM diarahkan via `guard.panggil`, tabel `kantor_config`+`kantor_llm_usage` (migrasi 0020, terterap prod), cap **$50/bln** terset. Kontrol chat: `matikan ai`/`nyalakan ai` (Direksi, konfirmasi, deterministik) di `app/kantor/kendali.py`+bot; biaya via tool `status_biaya` (bahasa natural).
- **Tahap 1 (RBAC) — backbone SELESAI (shadow), commit sampai e123cb5**: tabel role/user_role/grant (migrasi 0021, prod); seed 11 role+28 grant (`rbac_seed.py`, prod); scope-checker `rbac.py` (`boleh`/`grants_user`); onboarding primitif (`tetapkan_role`/`cabut_role`); peta resource→domain `rbac_map.py` (folder Drive ID/mailbox/GajiHub); **enforcement** `rbac.cek_tool_akses` (gate tool email per-mailbox + GajiHub) & `knowledge_larang` (anti-bocor knowledge); flag `kantor_config.rbac_enforce`=**shadow** (cek+log, belum menolak; prod). `run_kantor_agent(user_id=...)` diteruskan dari bot. 43 tes lolos.
- **BELUM (butuh live/konten)**: onboarding nyata (Telegram ID → `tetapkan_role`) · **flip rbac_enforce=on** setelah onboarding · enforcement Drive per-file (parent-walk runtime) · **RETAG knowledge lama** ke domain (item lama masih ranah 'umum') · routing approval berjenjang (`atasan_user_id`) · **commit code sudah, tapi belum `railway up`**.
- **Onboarding SIAP**: `app/kantor/rbac_onboard.py` (RENCANA 9 orang + `onboard(bindings)`); runner siap-isi = `memory/kantor-onboarding-runner.py` (isi telegram_id → jalankan; butuh DB publik, TIDAK butuh API). **Insight**: onboarding butuh bot **DEPLOYED** (tangkap Telegram ID via jalur "belum terdaftar" yang deterministik) tapi **TIDAK butuh API Anthropic** → bisa deploy + onboarding duluan walau API masih limit.
- **PENGINGAT AKTIVASI**: JANGAN set rbac_enforce=on sebelum user↔role terisi (semua ditolak → bot lumpuh). Urutan: **deploy** (railway up) → orang chat → isi runner → onboarding → amati log shadow → (naikkan limit API utk uji LLM) → **enforce=on** → jalankan [[kantor-uji-nanti]].

Related: [[kantor-ai-project]], [[gajihub-kledo-integration]], [[no-redundancy-kledo]], [[drive-audit-subfolder-lesson]], [[sop-mastery-principle]], [[bulk-llm-audit-cost]]
