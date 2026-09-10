---
name: kledo-tipe-kontak
description: Kledo contact type_id 1 = vendor, 3 = pelanggan — NOT type 4, which looks like vendors but is expenses
metadata:
  type: reference
---

In this company's Kledo (`pthadimulyautama.api.kledo.com`), `/finance/contacts`
returns `type_ids`, and **`type_id = 1` is the vendor/supplier type**. This is
counter-intuitive and was nearly got wrong:

| type | ~count | what it actually holds |
|---|---|---|
| **1** | 179 | **vendors/suppliers** — Catur, Umar Arifuddin, Pak Suparno, packaging vendors |
| 2 | 43 | employees — Ahmad Wahid Nurhani, Pegawai Umum |
| 3 | 299 | customers — Walk-in Customer, Angkringan Depan |
| 4 | 145 | expenses — PLN, Pertamina, Petugas Kebersihan, RT |

Type 4 *looks* like vendors. Verified against real data 2026-08-30: of 63
contacts that ever sold a commodity (gabah/beras/PK/broken/menir/reject),
**62 are type 1** and only 6 are type 4. Syncing type 4 would import PLN while
leaving out the actual rice suppliers.

Other facts worth keeping:
- Contacts carry multiple types (`[3, 1, 4]`); check membership, don't compare.
- `/finance/contactTypes` does not exist. `/finance/contactGroups` does but holds
  one barely-used group ("Vendor Beras PK", 7 contacts).
- ~1,400 purchase invoices; the dominant products are **Beras PK (1029)** and
  **Gabah (202)** — the rest is sacks/packaging. Filtering invoice product names
  is how you tell commodity suppliers from packaging vendors.
- Names repeat badly across the whole contact set ("Agus" matches 12), so never
  auto-match a supplier by name alone across types. Within type 1 alone, names
  happened to be unique.

**`type_id = 3` is pelanggan (customers)** — confirmed 2026-09-01 on real data:
301 of 601 contacts, and the only type carrying Kledo's built-in "Walk-in
Customer". The rest read like rice buyers (Toko beras handoko, Angkringan
Depan). Synced into its own `pelanggan` table by migration 0029; **24 contacts
are type 1 AND type 3**, which is fine — a person who sells gabah in the morning
and buys beras in the afternoon is a supplier on one record and a customer on
another. The weighbridge picks the list by DIRECTION, never by the contact.

**Trap, verified twice:** the `type_ids[]` query parameter on
`/finance/contacts` is **ignored** — any filter still returns all 601 contacts.
Filtering must happen client-side.

Implemented by `app/kantor/kledo_kontak.py` — one generic `sinkron(db, jenis)`
shared by `VENDOR` and `PELANGGAN` — plus the weekly poller. Its tests patch
`ambil_kontak`, the single place the network is touched. See
[[timbangan-module]] and [[kledo-kontak-supplier-sync]].
