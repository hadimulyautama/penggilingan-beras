---
name: timbangan-intake-integrasi
description: "Scheme to prevent double-entry of gabah/PK masuk between the timbangan (weighbridge) system and production PurchaseBatch — link (weighbridge = weight authority), not duplicate"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-31T15:18:07.969Z
---

**Problem (owner raised 2026-08-31):** the timbangan (weighbridge POS, `app/timbangan/`,
table `timbangan_transaksi`) records gabah/PK **MASUK** (netto weight, nopol, supplier,
jenis, karung, selisih/control). The production system ALSO records intake via
`PurchaseBatch` (`app/penggilingan/gudang1/models/gudang1.py`, table `purchase_batches`) and
`PkPurchaseBatch` (`app/penggilingan/gudang2/models.py`) — operator enters berat_total_kg,
no_polisi_truk, supplier, kondisi, kadar_air manually. **They overlap (berat/nopol/supplier/
jenis/tanggal) and are NOT linked** → double-entry risk + weight mismatch + double-counted
stock/HPP.

**STATUS: BUILT (2026-08-31, branch `feat/timbangan-intake-integrasi`, 4 commits, NOT
deployed, NOT merged).** Done: migrations 0027 (link cols timbangan_transaksi_id UNIQUE +
sumber_berat) & 0028 (berat_total_kg nullable); `timbang_link.py` (read active tickets +
sinkron_bobot_menunggu); `sinkron_bobot.py` poller (3-min, in main.py) fills "menunggu"
batch weights; `purchase.create_purchase_batch_dari_timbang` + gudang2
`create_pk_purchase_dari_timbang` (operator/staff pick a ticket, no weight/supplier typed;
batch creatable while "menunggu bobot"); `peta_jenis.py` (GABAH_BASAH→dryer wajib, GABAH_
KERING→silo/dryer, BERAS_PK→PK; BROKEN_MASUK/BERAS_MASUK unmapped); miniapp "Gabah masuk" &
"Catat PK luar" now pick timbang tickets; ~20 weight-readers made null-safe (menunggu=0
until synced); `rekonsiliasi.py` + mini-app staff report (unlinked tickets, nota↔timbang
selisih kg/pct/Rp, menunggu, manual). 101 tests pass. Approach A chosen (batch berat = synced
mirror of ticket; weight reference = ticket). Owner clarified: BROKEN_MASUK=beli broken luar,
BERAS_MASUK=beli beras medium luar → NO production intake model yet (options: 1 stock-in / 2
Kledo-only / 3 new model — undecided). REMAINING: broken/beras-masuk handling, KELUAR/sales
integration (timbang keluar ↔ penjualan output), then DEPLOY (only when weighbridge in
routine use — gabah/PK intake via ticket-pick). Merge the branch when ready.
**Manual fallback CLOSED (commit 78a69c5):** mini-app now has "Gabah masuk (MANUAL)" &
"Catat PK luar (MANUAL)" actions (old create_purchase_batch/create_pk_purchase) for when the
weighbridge isn't used; AND bot (gudang1/bot.py) + admin (admin.py) batches auto-tag
sumber_berat='manual' (model default) → visible in Rekonsiliasi, not a silent bypass. So
intake is never blocked if the bridge is down.
**Revision re-sync CLOSED (commit ad237c3):** resinkron_bobot_berubah() (in 3-min poller)
updates a linked batch's weight when the ticket is later corrected — but ONLY if the batch is
still flag_unverified (no price → no frozen money) AND (gabah) not yet 'digiling' (milling
snapshots its own weight in MillingProcess.berat_gabah_masuk_kg, so rendemen is unaffected).
Batches already verified/milled are NOT auto-changed; they surface in Rekonsiliasi section
"③ Bobot tiket berubah setelah verifikasi/giling" for manual review. Safety gate =
flag_unverified (flips False at gabah verification.py:85 / PK service.py:443). STILL OPEN:
(4) menunggu batch counts as 0 kg until synced (null-safe band-aid); plus broken/beras-masuk
& KELUAR below.

**BEST SCHEME (BUILT) — "link, not copy; weighbridge = weight authority":**
One physical event → one weighing (timbangan, the anti-selisih control) → flows into intake,
enriched not re-typed.
- Data flow: (1) truck weighed at bridge by petugas timbang → netto resmi; (2) SELESAI +
  unlinked MASUK ticket appears in operator's "perlu diproses" list; (3) operator picks it,
  system pulls berat/nopol/supplier/jenis from timbang, operator fills kadar air/kondisi/
  silo (NOT weight); (4) PurchaseBatch created, linked; admin fills harga → HPP/stok.
- Source of truth: **berat/nopol/karung/selisih = Timbangan**; kadar air/kondisi/silo/jenis PK
  = operator; harga = admin; HPP/stok = computed.
- Anti-dobel rules: add `timbangan_transaksi_id` (FK, **UNIQUE**) to purchase_batches &
  pk_purchase_batches (1 timbang→max 1 batch); berat read-only for operator (correct via
  timbang revision); linked timbang leaves the "perlu diproses" list; manual path flagged
  `sumber_berat='manual'` vs `'timbangan'`; reconciliation report matches timbang MASUK ↔
  batch (flag weighed-but-no-batch, and manual-batch-without-timbang).
- Keep the two systems separate (different roles/apps) — just LINK. Diagram at scratchpad
  `skema_timbangan_intake.html`.

**FINALIZED (2026-08-31) — separate apps, SHARED database.** Timbangan is now its OWN repo at
`~/Developer/timbangan` (split via commit af6a8d9 "lepas modul timbangan — kini repo
tersendiri"); this repo keeps only its migrations 0022-0026. Both apps use the SAME Postgres
(timbangan repo aligns to the same DATABASE_URL). So production reads `timbangan_transaksi`
DIRECTLY — **no cross-service API needed**. Both weights already exist on the timbang record:
**`netto_timbangan_kg` = bobot TIMBANG (measured, wajib)**, **`berat_acuan_kg` = bobot NOTA/
surat jalan (opsional; `acuan`="Foto nota / surat jalan", `nomor_acuan`=nota no.)**, plus
`selisih_kg`/`selisih_persen`. `status_tiket` **TERBUKA = tiket aktif** (SELESAI/DITUTUP_PAKSA
= closed). Timbang already REQUIRES nopol + supplier, and even has supplier scoring
(`timbangan_skor_supplier`). Build = mostly PRODUCTION side (no timbangan changes): add
`timbangan_transaksi_id` (UNIQUE) + `sumber_berat` ('nota'|'timbangan'|'manual') to
`purchase_batches` & `pk_purchase_batches`; read-only accessor over `timbangan_transaksi`;
operator mini-app "entry gabah masuk" = **pick an active (TERBUKA) MASUK ticket not yet
linked** (no weight/supplier input); reconciliation report. **HPP RULE (owner decided): basis
= bobot NOTA (berat_acuan_kg); but HPP/report MUST show the selisih nota↔timbang (kg, %, and
Rp = selisih×harga) so over-pay/short-receive is visible.** If no nota weight → fall back to
timbang netto (auto-filled when timbang-2 closes). Diagram (older "timbang selesai" flow) at
scratchpad `skema_timbangan_intake.html` — update to the TERBUKA-ticket + nota-basis flow.

**Also:** timbangan analytics is feasible (I queried it live — volume by arah/jenis, control
anomalies KURANG/INVESTIGASI/KELEBIHAN per supplier/vehicle, open tickets). Currently only 3
transactions (system just started 2026-08-31). Offered to build a `laporan_timbangan` tool in
the Kantor agent (like production/Kledo) once data grows. Related: [[timbangan-module]],
[[penggilingan-beras-project]], [[kledo-kontak-supplier-sync]] (supplier master),
[[no-redundancy-kledo]] (don't re-record what another system holds).
