---
name: railway-region-sfo
description: "Production MOVED sfo → Singapore on 2026-09-04; origin latency 202ms → 66ms. Railway scale/freeze gotchas learned the hard way."
metadata:
  type: project
---

**Migration DONE 2026-09-04, 23:14–23:24 WIB. Downtime 9 min 46 s.** All four
Railway services now run in `asia-southeast1-eqsg3a` (Singapore): `timbangan`,
`kantor`, `penggilingan-beras`, and the new database `Postgres-NPz3`.

**Result, measured on warmed connections:** origin round-trip **202 ms → 66 ms**
(~3× faster). Measure it as `time_starttransfer - time_appconnect` on `/health`;
raw TTFB is noisy because it includes the local TLS handshake. Do NOT judge the
result from the first requests after a deploy — cold samples read ~300 ms and
look like the move failed.

**Verified after cutover:** 78/78 tables identical, all four alembic version
tables intact, old database untouched (44 transaksi / 247 audit before and
after — nothing written during the window), three internal connections from the
apps to the new DB, all pages 200, logs clean.

## Traps found — all cost real time

1. **`railway scale` ADDS a region, it does not move.** `southeast-asia=1` alone
   produced 2 replicas across two continents. For a database that means two
   volumes with diverging contents; for `kantor` it means two Telegram pollers
   on one token (409). Always zero the old region **in the same command**, then
   READ the output back: it must say 1 replica.
2. **Region names shift under you.** `sfo` is not `us-west` — but after zeroing
   `sfo`, Railway re-reported the old region as `US West`, so a second pass with
   `us-west=0` was needed. Never assume; read the printed region line every time.
3. **`railway scale <region>=0` does NOT stop running instances.** It only
   changes config; instances stay RUNNING. There is no safe CLI freeze —
   `railway down` removes the deployment, and for services whose source you
   cannot rebuild locally that risks not getting them back. **Use
   dump-then-verify instead**: fingerprint the old DB (counts + max audit
   timestamp), dump, cut over, then re-check the fingerprint is unchanged.
4. **`railway add` cannot set a region.** Create the DB, then scale it to the
   target region *while it is still empty*.
5. **New Railway Postgres gets no public TCP proxy.** Reach it with
   `railway connect <svc> --tunnel-only --port 55432`, which needs an SSH key
   registered (`railway ssh keys add`). **Its output prints the password** —
   never leave that in a file.
6. **Second restore needs `--clean --if-exists`.** After a rehearsal the target
   is no longer empty; without `--clean` the restore fails per table or, worse,
   half-lands and mixes two snapshots.

## Still open

- **Old `Postgres` (sfo) is still running**, nothing points at it. Kept
  deliberately as a safety net — review around **11 September 2026**, then
  delete to stop the cost. It is not a rollback path: the mill has been writing
  to Singapore since the cutover.
- SSH key `mac-wahid-migrasi` registered on the Railway account; revoke via
  `railway ssh keys` when no longer needed.

Runbook with every command and gate:
https://claude.ai/code/artifact/001fdbe2-8266-4ac8-9b06-1cdb11df6768

Related: [[railway-deploy]], [[railway-deploy-jebakan]], [[timbangan-module]].
