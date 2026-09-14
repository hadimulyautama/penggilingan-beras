---
name: pisah-kantor-produksi
description: "Kantor AI SUDAH terpisah TUNTAS (repo + service Railway sendiri, 2026-09-02); MCP dipensiunkan & app/kantor dihapus; DB tetap bersama; sisa cuma Fase B webapp"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-09-01T14:57:55.326Z
---

**WORKSPACE CONSOLIDATION DONE (2026-09-01):** the project folder `~/Developer/AI Project` was
RENAMED to `~/Developer/Hadi Mulya Systems` (now a workspace, still also the live production git
repo until Fase A migrates code out). It now holds FIVE sub-repos (each gitignored in the prod
repo): `core/` `kantor/` `produksi/` (scaffolded — README only, empty), plus `timbangan/` and
`website/` (moved in from ~/Developer/timbangan and ~/Developer/hadimulya-website; website folder
renamed to `website`). Decision: core layer = **Opsi A** (shared git submodule for master schema:
User/Warehouse/Supplier/Pelanggan/Silo/Dryer/Heartbeat), NOT a shared pip package or a
production-owned core (User+Pelanggan need ORM+write in BOTH → submodule). App glue
(database.py/config.py/app.ai) still COPIED per repo. Root docs tidied into `docs/` (commit
bdfd5af). Memory pre-seeded to new project key `-Users-wahidnurhani-Developer-Hadi-Mulya-Systems`
+ backup at `~/Developer/_memory-backup-20260901-*`. Fase A STEP 1 DONE — `core/` now BUILT (commits 47bbf4c + 539905c): package `hmu_core` (Base,
TimestampMixin, 6 master models faithfully extracted from app/models/master.py), pyproject
(installable/submodule), Alembic with `version_table=alembic_version_core` + baseline
`0001_baseline_master`. VALIDATED read-only vs live DB: all 6 tables + columns + server-defaults
match; only drift = status/access_level/wa_broadcast_opt_in NULLABLE in 4 legacy tables
(suppliers/users/silos/dryers) vs model NOT NULL, but 0 real NULLs → harmless, core kept NOT NULL
(correct schema), optional future core migration 0002 to tighten. Baseline safe to `alembic stamp`
on live. STEP 2 DONE: core pushed to GitHub **github.com/hadimulyautama/hmu-core** (PRIVATE; org
hadimulyautama, same as penggilingan-beras/timbangan/website; gh user wahidnurhani20). Added as
git **submodule** `core/` in produksi/ and kantor/ (pinned to 539905c), verified `import hmu_core`
works via submodule. Timbangan SKIPPED (uses raw SQL, no hmu_core consumer). STEP 3 DONE: `alembic stamp 0001_baseline_master` applied to LIVE DB — created
`alembic_version_core` (=0001_baseline_master); production `alembic_version` still `0029_pelanggan`
(UNTOUCHED). Two migration chains now coexist in one DB via separate version tables, proven. Also
FIXED core env.py: was sync (needed psycopg2, not installed) → rewrote ASYNC (asyncpg) mirroring
app's migrations/env.py + sslmode strip (core commit 1102d46, pushed; produksi/kantor submodule
pins updated to 1102d46). NOTE: folder rename ALSO broke `.venv/bin/alembic` console-script shebang
(hardcoded old path) — worked around with `python -m alembic`; the venv scripts (alembic, etc.)
have stale shebangs and may need `pip install --force-reinstall` or venv recreate eventually.
STEP 4 FUNCTIONAL PART DONE & PROVEN (branch `feat/core-master-extract`, commit 1e7e074, NOT
merged, NOT deployed; main is pristine): app/database.py now `from hmu_core import Base,
TimestampMixin` (removed its own Base/TimestampMixin defs); app/models/master.py now re-exports
the 6 models from hmu_core. Result: ONE shared Base (app.database.Base IS hmu_core.Base), master
+ domain share ONE registry (PurchaseBatch.registry IS Supplier.registry) so relationships
resolve, 58 tables in metadata, **all 109 tests pass**. hmu_core made importable locally via
`.venv/bin/python -m pip install -e ./core` (editable). Local working tree returned to main
(clean/live). STEP 4 FULLY DONE + DEPLOYED + VERIFIED LIVE (2026-09-02, maintenance window): chose option (c)
VENDOR — copied hmu_core package to root repo top-level `hmu_core/` + `COPY hmu_core ./hmu_core`
in Dockerfile (commit a5f07f4; branch merged to main, pushed). Deployed via `railway up --service
penggilingan-beras`. Verified from logs+health: uvicorn up, alembic upgrade ran (hmu_core imported
fine in image), all 4 bots + pollers up, `/health {"status":"ok"}`. The TelegramConflictError
during deploy was the normal swap-window overlap (old+new both polling briefly) → self-resolved
(all bots "Connection established"). Production now runs with master from hmu_core. NOTE: vendored
hmu_core is a TEMPORARY copy — if core changes, re-sync root `hmu_core/`; replaced by submodule
when app moves to produksi/ (step 5). Also: `railway status` has no `--service` flag in this CLI;
folder rename had broken `railway link` (re-linked) + `.venv/bin/alembic` shebang (used `python -m
alembic`). REMAINING: STEP 5 (populate produksi/ & kantor/ from app/). **STEP 5 BLOCKER FOUND (2026-09-02):
the Kantor extraction is NOT mechanical copying — it needs a REFACTOR of the shared bot/AI layer.**
Kantor→production is 0 DIRECT imports but TRANSITIVELY coupled: app/kantor/bot.py → app.bots.common
→ app/ai/nlp_parser.py → **app.penggilingan.gudang1.nlp + gudang2.nlp (PRODUCTION domain)**. Also
app.bots.common → app.services.user_admin (link_by_contact); app/kantor/agent.py → app.services.
analytics; app/kantor/proaktif/briefing.py → app.services.dashboard.dashboard_data. So `app/ai`
(2769 lines) is NOT pure foundation — nlp_parser is entangled with production. Kantor's bot only
USES generic bits of bots.common (authenticate, get_session, handle_shared_contact, confirm words)
but IMPORTING the module drags in production NLP. Proper plan: (1) split the generic bot/AI helpers
(auth/session/LLM client) from production-NLP so kantor takes only generic — a refactor of SHARED
code (bots.common, ai) used by production too → must test BOTH sides; (2) rewire the 2 production-
data reads (analytics, dashboard_data) to MCP (~527 + ~413 lines, pure production, DON'T copy);
(3) kantor gets own main.py + own Alembic for its ~10 tables + own Railway service; (4) cutover
(remove kantor from root registry+heartbeat+main pollers, one-shot bot-token switch). This is a
DEDICATED refactor project, NOT to be rushed — Kantor manages email/Kledo/Drive/approvals (critical).
Step-5 refactor blueprint artifact: https://claude.ai/code/artifact/b89ded93-dafc-41fd-b796-0f4076ff5525 . I stopped step 5 deliberately at this finding. Live system healthy & running new code (master from
hmu_core). Kantor code (app/kantor) NOT moved yet.
**STEP 5 REFACTOR + REPO KANTOR SELESAI — SIAP CUTOVER, BELUM DIDEPLOY (2026-09-02).**
Branch produksi `feat/pisah-kantor` (commit 8fcd23a, belum merge/deploy) memutus SEMUA jerat:
KantorConfig/KantorLLMUsage → `app/ai/models.py` (nama tabel tetap); `_date_context` → `app/ai/tanggal.py`
(lepas dari ai/base yang menyeret ai/tools 1.6k baris tool pabrik); bots/common pakai TYPE_CHECKING +
hmu_core; 3 seam data produksi → **API internal** `app/web/internal.py`
(/internal/produksi/{tanya,hpp,operasional}, ber-token INTERNAL_API_TOKEN, read-only) dipanggil
`app/kantor/klien_produksi.py`. Terbukti: import app.kantor.* hanya memuat config/database/
ai(claude_client,guard,models,tanggal)/bots.common — NOL modul produksi; 109 tes lulus.
Repo `kantor/` (commit fdc95e5, remote GitHub BELUM dibuat) lengkap: app/ (domain + fondasi salinan
mandiri: config ramping, database, ai/, bots/{common generik,registry 1 bot}, services/{akun,heartbeat}),
main.py sendiri (FastAPI /health + bot + 7 poller + heartbeat), Alembic sendiri
(version_table=alembic_version_kantor + include_object hanya `kantor_`), baseline 0001 dibangkitkan dari
model & DIVERIFIKASI di Postgres docker kosong (core dulu → kantor → `alembic check` = no new ops),
Dockerfile+entrypoint+requirements(httpx eksplisit)+.env.example+README. Drift diketahui: 13 kolom
kantor_* NULLABLE di live tapi NOT NULL di model (sama pola seperti core; tak berbahaya).
Kantor juga MENGADOPSI SKEMA LAMA OTOMATIS (commit e9886a8): env.py lihat tabel kantor_* ada tapi alembic_version_kantor belum → stamp baseline lewat MigrationContext.stamp, bukan jalankan → langkah stamp manual di DB live DICORET. Jebakan yang terbukti saat uji: adopsi HARUS di koneksi/transaksi sendiri — kueri apa pun sebelum alembic membuka transaksi implisit, lalu context.begin_transaction() tak memiliki transaksinya dan SELURUH migrasi ter-rollback diam-diam. Ketiga jalur diuji di Postgres docker (kosong / sudah ter-chain / tabel+data tanpa chain). **Checklist cutover ada di `docs/pemisahan-kantor-cutover.md`** (repo GitHub → stamp Alembic di live →
service Railway → lepas BOT_KANTOR_TOKEN dari produksi lalu isi di kantor → uji → rollback).
JEBAKAN: begitu branch produksi dideploy, WAJIB set INTERNAL_API_TOKEN + PRODUKSI_API_URL (URL publik
service produksi sendiri) + PRODUKSI_API_TOKEN, kalau tidak tanya_produksi/simulasi HPP/bagian
operasional briefing mati. Catatan: `alembic check` produksi melaporkan drift tabel `timbangan_*`
(chain produksi membuatnya, aplikasi timbangan pakai SQL mentah tanpa model) — PRA-ADA, jangan
autogenerate-apply tanpa disaring. Heartbeat ikut pindah ke Kantor → produksi kehilangan deteksi
downtime sendiri (opsi: poller Kantor ping /health produksi).

**CUTOVER SELESAI & TERVERIFIKASI (2026-09-02).** Kantor AI kini hidup di repo
**github.com/hadimulyautama/kantor** (privat) + service Railway **`kantor`** di proyek yang sama
(penggilingan-beras). Bukti: /health produksi = bots ['gudang1','gudang2','admin'] (Kantor hilang);
log kantor = "Bot aktif ['kantor'] · poller: ya" + 7 poller + heartbeat + Telegram "Connection
established"; Alembic kantor di DB LIVE mengadopsi sendiri ("mengadopsi skema: stamp
0001_baseline_kantor", 0 tabel disentuh); /internal/produksi/{operasional,hpp,tanya} diuji (403 tanpa
token / 403 token salah / data + jawaban agen pabrik dgn token benar). Tes: produksi 16, kantor 97
(13 berkas tes Kantor dipindah). BOT_KANTOR_TOKEN kini HANYA di service kantor (dihapus dari
produksi). Commit produksi: 09a9c2e (merge fondasi+API internal) → 7c60932 (lepas bot/poller/
heartbeat, include_object saring kantor_* di migrations/env.py) → 4288618 (docs). Variabel Kantor
(25) disalin otomatis dari service produksi; token bot DISET MANUAL oleh pemilik — upaya menyalinnya
lewat CLI diblokir classifier (membaca nilai token mentah), dan itu memang benar: minta pemilik yang
isi lewat dashboard Railway.
**SISA (belum dikerjakan):** (1) `app/kantor/` di repo produksi = SALINAN BEKU (ditandai di
__init__.py) karena mcp_server.py masih membungkus tool arsip/Drive/dokumen dari sana → untuk
menghapusnya, server MCP harus dipecah dulu (tool pabrik di produksi, tool Kantor di repo kantor);
BUTUH keputusan pemilik karena agen Hermes/Cowork jadi menunjuk 2 endpoint. SAMPAI ITU: kembangkan
Kantor HANYA di repo kantor, jangan sentuh salinan beku. (2) service `mcp` menandai deploy gagal tiap
push padahal instance berjalan sehat (HTTP 200) — pra-ada sebelum pemisahan, belum ditelusuri.
(3) produksi tak punya deteksi downtime sendiri (heartbeat ikut Kantor). (4) Fase B belum mulai.
Sakelar `POLLER_AKTIF` di service kantor dipakai bila perlu instance kedua untuk uji tanpa memproses
email/invoice dua kali. Catatan lengkap: `docs/pemisahan-kantor-cutover.md` di repo produksi.

**PEMISAHAN TUNTAS + MCP DIPENSIUNKAN (2026-09-02, lanjutan hari yang sama).** Pemilik menyatakan
tak memakai Hermes lagi; log service `mcp` tak pernah mencatat SATU PUN permintaan nyata (cuma 3 baris
healthcheck) → **service mcp DIHAPUS dari Railway**, dan `mcp_server.py` + `Dockerfile.mcp` +
`requirements-mcp.txt` + `.venv-mcp` dibuang. Itu melepas penahan terakhir → **`app/kantor/` DIHAPUS
dari repo produksi** (tak ada lagi salinan beku), `app/models/__init__.py` tak lagi mendaftarkan tabel
Kantor (metadata produksi 45 tabel, nol `kantor_*`). Commit: 0e0a0aa. `docs/ARSITEKTUR.md` ditulis
ulang ke v1.4 (tiga repo, cara lingkaran ai→kantor→ai dipotong, satu-satunya sambungan HTTP
antar-service, tiga chain migrasi + dua penjaganya, topologi Railway tanpa mcp).
JEBAKAN YANG TERJADI & DIPERBAIKI: `git mv tests/... kantor/tests/` ternyata IKUT MENDAFTARKAN berkas
ke repo produksi meski /kantor/ ada di .gitignore (git menghormati permintaan eksplisit) → 12 berkas
tes punya dua salinan terlacak di dua repo; dicabut dengan `git rm --cached` (commit a5c1c0a-ish).
Kalau memindah berkas ANTAR-repo: salin lalu `git rm` di asal, JANGAN `git mv`.
Workspace juga dirapikan — lihat [[workspace-layout]]. Temuan sampingan: [[gmail-pribadi-token-mati]].

This session is `hadi-mulya-systems-7b`. NOTE: folder rename UNLINKED Railway CLI — re-linked via
`railway link` (project penggilingan-beras, id 5518c07b-e1c9-4876-ae5c-89ac304ca476); production
deploy itself was never affected.

Owner (2026-09-01) decided to SPLIT Kantor AI and the production (rice-mill) system into two
SEPARATE GitHub repos + two Railway services, mirroring the timbangan split. Blueprint artifact:
https://claude.ai/code/artifact/51137f02-9b0c-4b5c-8df3-469903c5a72d

**Coupling reality (measured):** Kantor → production = **0 imports** (Kantor never touches
production code; it reads production DATA). Production → Kantor = **only 2 refs**:
`app/bots/registry.py` (registers the Kantor bot) + `app/services/heartbeat.py` (uses the
`Heartbeat` model from app/kantor/models). Kantor owns its own tables (SopDokumen, SopChunk,
AksiPending, KantorAuditLog, KantorChatRiwayat, Aset, NomorDokumen, KartuPemeliharaan,
AturanEmail, Heartbeat). Kantor's shared-foundation deps: `app.database` (13x), `app.config`
(13x), `app.ai` (agentic, 9x), minor `models/services/bots.common`. Sizes: kantor ~9k lines,
penggilingan ~7k, shared models ~341.

**Decisions locked:** (1) Shared DB — both repos use the SAME Postgres (not separate). (2)
Foundation = COPY into each repo (self-contained, like timbangan), NOT a shared pip package —
avoids re-coupling; configs differ anyway (Kantor: Kledo/Gmail/Drive/agentic; prod: bot tokens/
mill params). (3) Kantor reads production data via the existing **MCP server** (read-only
HPP/stok/laporan) — NOT code import. (4) Blueprint-first before moving files (both live 24/7).

**Fase A (this migration) — repo split, bots+mini-app stay:** (1) new repo `~/Developer/kantor`
= app/kantor + copied foundation (database.py/config.py/app.ai) + own main.py (Kantor bot +
Kantor pollers) + docker + own Alembic. (2) Split Alembic ownership on the SAME DB via separate
`version_table` per repo (e.g. alembic_version vs alembic_version_kantor); Kantor tables → Kantor
repo, production tables → production repo. (3) CRITICAL switchover: cut 2 refs in production
(registry Kantor bot, heartbeat) + remove Kantor pollers from main.py, deploy production, then
immediately deploy new Kantor service — ONE bot token = ONE process, so no parallel polling. (4)
Repoint Kantor's production-data reads to MCP. (5) Remove app/kantor from production repo, new
GitHub repo, docs. Rollback noted per phase.

**Fase B (LATER, separate effort) — production becomes bot-less webapp:** owner wants production
with NO Telegram bot (like timbangan). Drop gudang1/gudang2/admin bots; evolve the existing
mini-app (app/web/api) into a STANDALONE webapp. Key issue "jika tidak dengan telegram":
mini-app currently trusts Telegram identity (`require_miniapp_user`); a bot-less webapp needs its
own login (username/PIN) — REUSE timbangan's already-bot-less auth model. Do this AFTER Fase A is
clean (don't stack two big migrations). Nothing built yet — awaiting owner's go on Fase A step 1.

Note: another session/commit (07be7b6, customer master from Kledo) touches this repo concurrently
— coordinate. Related: [[kantor-arsitektur-terintegrasi]] (supersedes its shared-process idea
with full repo split), [[timbangan-module]] (split precedent), [[mcp-server]] (the read seam),
[[kledo-redesign-blueprint]], [[railway-deploy]].
