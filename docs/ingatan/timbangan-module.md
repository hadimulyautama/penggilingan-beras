---
name: timbangan-module
description: Pos timbang (weighbridge) — its OWN repo ~/Developer/timbangan since 2026-08-31; shares the penggilingan database; prices deliberately absent by design
metadata: 
  node_type: memory
  type: project
  originSessionId: 3cb6a7a5-749c-43bc-b394-ab6ae8359aa6
  modified: 2026-08-30T02:23:09.326Z
---

Modul **Timbangan** (pos timbang) shipped 2026-08-30. Since **2026-08-31 it is a
SEPARATE REPO**: `~/Developer/timbangan` → `github.com/hadimulyautama/timbangan`
(private, branch `main`). It is no longer in `app/timbangan/` of the penggilingan
repo — don't look for it there. Docs are `docs/` inside that repo (RANCANGAN.md =
design, DEPLOY.md = runbook, pedoman-admin.html / pedoman-petugas.html = the
guides for people).

Still the same Railway service `timbangan`, and **still the same PostgreSQL** as
penggilingan — code separated, data did not. Five foreign keys leave the module
into penggilingan-owned tables (`users`, `suppliers`, `pelanggan`,
`purchase_batches`, `pk_purchase_batches`); they are mapped read-only in
`app/models.py` of the timbangan repo, which is written as the CONTRACT for that
seam. Its own Alembic chain uses version table `alembic_version_timbangan`, and
autogenerate is restricted to `timbangan_*` tables.

Kantor AI deliberately did NOT get the same treatment: `app/ai`, `app/models`,
and `app/bots` depend on it, so it is circled by the foundation rather than
sitting on top of it. Reasons recorded in `docs/ARSITEKTUR.md` §1.

**The defining constraint: no prices anywhere.** Weighbridge operators must not
know prices, so the module has no price/money column in any of its 13 tables —
enforced by absence, not by hiding. A test scans every table, every operator
screen, and the CSV export for money words; keep it strict, and reword pages
rather than loosening it. Purchasing/payment stays in Kledo. See
[[no-redundancy-kledo]].

Other design commitments worth preserving:

- **Commodity rules live in data** (`timbangan_jenis`), copied into each
  transaction on save, so revising a threshold never changes past verdicts.
  Deliberately NOT editable from the UI — that requires an SOP revision.
- **Five operational params ARE editable** by Admin from `/timbangan/pengaturan`
  (`timbangan_config`): bridge capacity, tera step, lock hours, idle-ticket
  hours, max photo MB. Precedence: DB row → env var → code default.
- **Transaction codes are device-generated** (`<awalan>-<tanggal>-<perangkat>-<urut>`)
  so the PWA works offline without collisions. Server upsert is idempotent on the code.
  Since **2026-09-04 the prefix follows the direction of goods**, not a single
  `TRX-`: MSK (masuk), KLR (pengiriman), BBS (jasa timbang), TRF (transfer),
  RTP (retur dari pelanggan), RTS (retur ke supplier) — `service.AWALAN_KODE`.
  A printed bukti now says what kind of event it was without opening the system.
  Sequence runs independently per prefix per day per device. The 43 pre-existing
  `TRX-` tickets were renumbered in production the same day
  (`scripts/ganti_awalan_kode.py`, audit rows reassigned, old code kept as
  `nilai_sebelum`), so no ticket in the database carries the old prefix.
- **Retur is its own direction, not a signed variant** of masuk/keluar, because
  the counterparty CROSSES: goods returned by a customer come IN but the party
  is a pelanggan; goods we reject go OUT but the party is a supplier.
  `service.PIHAK_ARAH` picks the party table from `arah`, so folding retur into
  MASUK/KELUAR would make the operator hunt for a customer in the supplier list.
  Seeded as ONE jenis row per direction (`RETUR_PELANGGAN`, `RETUR_SUPPLIER`)
  following the Transfer Internal precedent — commodity goes in the note, tara
  is manual, threshold is 2 kg/ton symmetric against the surat jalan retur.
  Splitting it per commodity later needs master rows only, no code.
- **Gabah control results are confidential** (SOP butir 8) — selisih is NOT
  printed on the supplier's receipt. Beras PK is the opposite (Sistem Tara
  butir 9): the nota must be given.
- Nothing is ever hard-deleted; VOID with a reason. Audit is append-only.

Migrations `0022_timbangan` + `0023_timbangan_config` are owned by service `app`
— only `app` runs alembic; `timbangan` uses `docker/entrypoint-timbangan.sh`
which deliberately skips migration. Deploy order when the schema changes:
`app` first, then `timbangan`. See [[railway-deploy]].
