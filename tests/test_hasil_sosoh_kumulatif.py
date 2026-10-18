"""Total aktual menjadi selisih tanpa menggandakan stok."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.penggilingan.gudang2 import polishing as p


@pytest.fixture
def catatan(monkeypatch):
    proses = SimpleNamespace(id=1, kode_proses="POL-UJI", status="proses")
    baris = []

    class Db:
        async def execute(self, query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(one=lambda: proses))

        def add(self, row):
            row.id = len(baris) + 1
            baris.append(row)

        async def flush(self):
            pass

        async def commit(self):
            pass

    async def total(db, proc_id, jenis):
        return sum(float(r.berat_kg) for r in baris if r.jenis == jenis)

    monkeypatch.setattr(p, "_get_proc", AsyncMock(return_value=proses))
    monkeypatch.setattr(p, "_total_output", total)
    monkeypatch.setattr(p, "log_activity", AsyncMock())
    return Db(), baris, SimpleNamespace(id=1)


async def test_total_300_lalu_500_dan_kirim_ulang_tetap_500(catatan):
    db, baris, user = catatan
    for total in (300, 500, 500):
        hasil = await p.catat_output(db, user=user, kode="POL-UJI", jenis="premium",
                                    berat_kumulatif=total)
        assert hasil.berat_kumulatif == total
    assert [float(r.berat_kg) for r in baris] == [300, 200]
    assert hasil.berat_kg == 0
    with pytest.raises(p.Gudang2Error, match="tidak boleh lebih kecil"):
        await p.catat_output(db, user=user, kode="POL-UJI", jenis="premium",
                            berat_kumulatif=400)
    assert sum(float(r.berat_kg) for r in baris) == 500


async def test_total_per_jenis_dan_tambahan_lembar_lama(catatan):
    db, baris, user = catatan
    for jenis, muatan in (("premium", {"berat_kg": 300}),
                          ("premium", {"berat_kg": 200}),
                          ("broken", {"berat_kumulatif": 100})):
        hasil = await p.catat_output(db, user=user, kode="POL-UJI", jenis=jenis, **muatan)
    assert hasil.berat_kumulatif == 100
    hasil = await p.catat_output(db, user=user, kode="POL-UJI", jenis="premium",
                                berat_kumulatif=600)
    assert hasil.berat_kg == 100
    assert hasil.berat_kumulatif == 600
    with pytest.raises(p.Gudang2Error, match="jangan keduanya"):
        await p.catat_output(db, user=user, kode="POL-UJI", jenis="premium",
                            berat_kg=100, berat_kumulatif=700)
