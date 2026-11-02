"""Satu pemilik scheduler dan sinkronisasi, terpisah dari proses web."""
import asyncio
import logging
from contextlib import asynccontextmanager

log=logging.getLogger('proses_latar')

@asynccontextmanager
async def hidup(app):
    from app.services.seed import seed_master
    from app.web.seed_akun import seed_akun_awal
    from app.penggilingan.gudang1.services.sinkron_bobot import run_sinkron_bobot_poller
    from app.services.kledo_scheduler import run_kledo_scheduler
    from app.services.scheduler import run_late_drying_scheduler
    from app.services.retur_pekerja import jalankan
    for seed in (seed_master,seed_akun_awal):
        try:await seed()
        except Exception:log.exception('Inisialisasi %s gagal',seed.__name__)
    tasks=[asyncio.create_task(fn()) for fn in
        (run_late_drying_scheduler,run_sinkron_bobot_poller,run_kledo_scheduler,jalankan)]
    log.info('Pekerja latar siap; satu pemilik untuk seluruh proses web.')
    try:yield
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
