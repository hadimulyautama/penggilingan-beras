"""Pasangan aplikasi memeriksa identitas database yang sama sebelum SQL bisnis."""
import asyncio,json,os,subprocess
from pathlib import Path
import pytest
from tests.pg.test_ruang_perusahaan import siapkan,aktifkan,konfigurasi,A,B
from tests.pg.test_teraflow_kiriman import _skema_head
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from hmu_identitas.ruang_data import RuangData
pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi,pytest.mark.fondasi_multi]

async def test_interpreter_teraflow_menerima_perusahaan_pasangan_dan_menolak_salah_database(pg,running,monkeypatch):
    r=await siapkan(pg);await aktifkan(pg,r)
    root=Path(os.environ['UJI_TF_ROOT']);python=os.environ['UJI_TF_PYTHON']
    for candidate,allowed in [(r,True),(RuangData(r.company_id+1,B,r.sesi_lama_sampai),False),(RuangData(r.company_id,B,r.sesi_lama_sampai),False)]:
        konfigurasi(monkeypatch,candidate)
        env={**os.environ,'DATABASE_URL':os.environ['UJI_PG_URL'],'PYTHONPATH':str(root)}
        out=await asyncio.to_thread(subprocess.run,[python,'tests/integrasi_ruang_data.py'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert out.returncode==0,out.stderr
        result=json.loads(out.stdout)
        assert result['diizinkan']==allowed
        if allowed:assert result['gudang']>0
