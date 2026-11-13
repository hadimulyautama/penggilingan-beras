"""PadiFlow dan interpreter TeraFlow membaca ID organisasi yang sama."""
import asyncio,json,os,subprocess
from pathlib import Path
from dataclasses import asdict
import pytest
from hmu_identitas.organisasi import konteks_kerja
from tests.pg.test_master_organisasi import organisasi,pilihan
from tests.pg.test_teraflow_kiriman import _skema_head
from tests.pg.test_masuk_detail_timbang import sidik

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi,pytest.mark.fondasi_multi]


async def test_id_perusahaan_lokasi_dan_hak_akses_sama_di_kedua_aplikasi(pg,organisasi):
    x=organisasi;requests=[pilihan(x,0),pilihan(x,1)]
    requests += [dict(pilihan(x),company_id=x['c'][1]),dict(pilihan(x),user_id=x['luar'])]
    async with pg() as db:
        awal=await sidik(db)
        expected=[dict(diizinkan=True,konteks=asdict(await konteks_kerja(db,**a))) for a in requests[:2]]
    expected += [dict(diizinkan=False),dict(diizinkan=False)]
    root=Path(os.environ['UJI_TF_ROOT']);python=os.environ['UJI_TF_PYTHON']
    r=await asyncio.to_thread(subprocess.run,[python,'tests/integrasi_organisasi.py',json.dumps(requests)],
        cwd=root,env={**os.environ,'DATABASE_URL':os.environ['UJI_PG_URL'],'PYTHONPATH':str(root)},
        capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)==expected
    async with pg() as db:assert await sidik(db)==awal
