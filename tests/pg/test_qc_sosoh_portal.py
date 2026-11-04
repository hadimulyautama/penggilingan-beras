"""Daftar dan detail QC sosoh pelanggan tetap terbatas pada proses miliknya."""
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from app.database import now_local
from app.models import PolishingProcess, SampelQcSosoh
from tests.pg.test_portal_pelanggan import client, portal  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('pemilik', [0, 1])
async def test_riwayat_qc_sosoh_hanya_proses_pelanggan(pg, portal, pemilik):
    async with pg() as db:
        for i in (0, 1):
            proc = await db.get(PolishingProcess, portal.process[i]['sosoh'])
            for _ in range(i + 1):
                db.add(SampelQcSosoh(polishing_process_id=proc.id, jenis='medium',
                    waktu_sampel=proc.waktu_mulai, dicatat_pada=now_local(),
                    pengambil_id=proc.created_by, pemeriksa_id=proc.created_by,
                    hasil_pada=now_local(), md=Decimal('110.21'), catatan_lab=f'LAB-MILIK-{i}'))
        await db.commit()
    async with client(portal.accounts[pemilik]) as c:
        daftar = await c.get('/pelanggan/riwayat-sosoh')
        assert daftar.status_code == 200
        assert f'QC beras · {pemilik + 1} sampel' in daftar.text
        assert f'POL-PORTAL-{1-pemilik}' not in daftar.text
        detail = await c.get(f"/pelanggan/riwayat-sosoh/{portal.process[pemilik]['sosoh']}")
        assert detail.status_code == 200
        assert f'LAB-MILIK-{pemilik}' in detail.text and 'MD 110,21' in detail.text
        assert f'LAB-MILIK-{1-pemilik}' not in detail.text
        assert not BeautifulSoup(detail.text, 'html.parser').select('[data-qc-editor],[data-qc-baru],[data-qc-lengkapi]')
        assert (await c.get(f"/pelanggan/riwayat-sosoh/{portal.process[1-pemilik]['sosoh']}")).status_code == 404
