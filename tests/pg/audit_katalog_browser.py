"""Persiapan tangkapan eksplisit; hanya pada database uji lokal berpagar fixture pg."""
from tests.pg.test_tiket_antrean_produksi import _klien, pabrik


async def test_siapkan_browser_lokal(pg,pabrik):
    import json
    from pathlib import Path
    from app.services.seed import seed_master
    await seed_master()
    async with await _klien(pg,role='admin') as c:
        assert (await c.get('/pekerjaan')).status_code == 200
        Path('/tmp/hmu-katalog-cookies.json').write_text(json.dumps(dict(c.cookies)))
