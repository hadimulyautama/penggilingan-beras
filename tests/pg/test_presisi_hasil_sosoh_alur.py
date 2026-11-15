"""Satu alur sintetis output kumulatif → sisa silo → koreksi operator."""
import json
from pathlib import Path
import os
from io import BytesIO
from decimal import Decimal as D

import pytest
from sqlalchemy import select, func

from app.models import User, PolishingOutputLog, PolishingSiloUsage, Silo
from app.penggilingan.gudang2 import polishing as p, service as g2
from app.services.stok import output_sosoh
from tests.pg.test_form_selesai_penyosohan import proses, gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio
OUT = Path(os.environ['BUKTI_PRESISI']) if os.environ.get('BUKTI_PRESISI') else None

async def inspect_outputs(pg, pid):
    async with pg() as db:
        outputs = await output_sosoh(db, pid)
        usages = list((await db.scalars(select(PolishingSiloUsage).where(
            PolishingSiloUsage.polishing_process_id == pid))).all())
        used = sum(D(str(x.berat_terpakai_kg)) for x in usages)
        n = p.neraca_sosoh(float(used), outputs)
        logs = list((await db.scalars(select(PolishingOutputLog).where(
            PolishingOutputLog.polishing_process_id == pid).order_by(PolishingOutputLog.id))).all())
        return dict(outputs=outputs, bahan_terpakai_kg=str(used),
            pemakaian=[dict(awal=str(x.berat_awal_kg), masuk=str(x.berat_masuk_kg),
                           sisa=str(x.berat_akhir_kg), terpakai=str(x.berat_terpakai_kg)) for x in usages],
            beras_kg=n.beras.kg, keluar_kg=n.keluar_kg, susut_kg=n.susut.kg,
            persen_total=n.beras.persen+sum(x.persen for x in n.samping)+n.susut.persen,
            log=[dict(id=x.id,jenis=x.jenis,kg=str(x.berat_kg)) for x in logs])

async def test_dua_desimal_dari_input_koreksi_sampai_laporan(pg, proses):
    precision='two_decimals'
    kode, pid = proses['kode'], proses['pid']
    evidence = dict(baseline='85ff604718cbd76b3b99c1e6cd73d70c05b9640a',
                    fixture='private PostgreSQL UTF8; synthetic lot, operator and supplier',
                    precision=precision,requests=[], expected={})
    first=3000.12
    input_extra, input_remaining=1000.01,800.00
    expected_output={'premium':7000.24,'medium':1000.12,'broken':1000.11,
                     'menir':300.22,'bekatul':500.33,'reject':49.44}
    expected_used=D('9800')+D(str(input_extra))-D(str(input_remaining))
    expected_loss=expected_used-sum(map(lambda x:D(str(x)),expected_output.values()))
    def save():
        if OUT:(OUT/('flow-'+precision+'.json')).write_text(json.dumps(evidence,indent=2,ensure_ascii=False,default=str))
    async with pg() as db:
        user=await db.get(User,proses['user'].id)
        await g2.pindah_tumpukan_ke_silo(db,user=user,intake_id=proses['intake_tumpukan'],nama_silo='B',berat=input_extra)
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        base='/api/actions/sosoh-ringkas/'+kode
        async def post_results(rows):
            state=(await c.get(base)).json()
            body=dict(dasar=state['dasar'],hasil=[dict(jenis=k,total=v) for k,v in rows])
            response=await c.post(base+'/hasil/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
            evidence['requests'].append(dict(action='hasil/periksa',payload=body,status=response.status_code,response=response.json()))
            assert response.status_code==200,response.text
            body.update(pemeriksaan=response.json()['pemeriksaan'],konfirmasi=True)
            response=await c.post(base+'/hasil/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
            evidence['requests'].append(dict(action='hasil/simpan',status=response.status_code))
            assert response.status_code==200,response.text
        await post_results([('premium',first)])
        await post_results(list(expected_output.items()))
        async with pg() as db:
            await p.selesai_penyosohan(db,user=await db.get(User,proses['user'].id),
                kode=kode,nama_silo='B',sisa_kg=input_remaining)
        evidence['before']=await inspect_outputs(pg,pid)
        evidence['expected'].update(before_outputs=expected_output,
            input_extra=input_extra,input_remaining=input_remaining,
            bahan_terpakai_kg=str(expected_used),before_susut_kg=str(expected_loss))
        save()
        before=evidence['before']
        checks=dict(before_outputs_exact=before['outputs']==expected_output,
            input_used_exact=D(before['bahan_terpakai_kg'])==expected_used,
            output_log_count=len(before['log'])==7,
            before_loss_exact=abs(D(str(before['susut_kg']))-expected_loss)<D('0.000001'),
            before_percent_conserves=abs(before['persen_total']-100)<0.000001)
        # Koreksi dua desimal mempertahankan bahan dan jenis hasil lainnya.
        correction='/api/actions/koreksi-bahan/sosoh/'+kode
        response=await c.get(correction)
        assert response.status_code==200,response.text
        body=dict(dasar=response.json()['dasar'],bahan=[],hasil={'premium':7000.23},
                  alasan='Pemeriksaan hasil sintetis: pembetulan total premium',
                  kunci='qa-massa-correction-20261115-0001')
        from tests.pg.test_form_selesai_penyosohan import fakta
        unchanged=await fakta(pg)
        rejected=await c.post(correction+'/periksa',json={**body,'hasil':{'premium':7000.231}},headers={'X-CSRF-Token':cap_formulir(c)})
        assert rejected.status_code==409,rejected.text
        assert await fakta(pg)==unchanged
        evidence['correction_rejected']=dict(status=rejected.status_code,response=rejected.json())
        response=await c.post(correction+'/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
        evidence['requests'].append(dict(action='koreksi/periksa',status=response.status_code))
        evidence['correction_preview']=response.json()
        save()
        assert response.status_code==200,response.text
        body.update(pemeriksaan=response.json()['pemeriksaan'],konfirmasi=True)
        response=await c.post(correction+'/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
        evidence['requests'].append(dict(action='koreksi/simpan',status=response.status_code))
        evidence['correction_response']=response.json()
        assert response.status_code==200,response.text
        evidence['after']=await inspect_outputs(pg,pid)
        state=(await c.get(base)).json()
        evidence['after_operator_neraca']=state['neraca_lembar']
        after_outputs={**expected_output,'premium':7000.23}
        after_loss=expected_used-sum(D(str(x)) for x in after_outputs.values())
        evidence['expected'].update(after_premium_kg=7000.23,after_susut_kg=str(after_loss))
        after=evidence['after']
        checks.update(after_premium_exact=D(str(after['outputs']['premium']))==D('7000.230'),
            other_outputs_unchanged={k:v for k,v in after['outputs'].items() if k!='premium'}=={k:v for k,v in expected_output.items() if k!='premium'},
            after_input_used_exact=D(after['bahan_terpakai_kg'])==expected_used,
            after_loss_exact=abs(D(str(after['susut_kg']))-after_loss)<D('0.000001'),
            after_percent_conserves=abs(after['persen_total']-100)<0.000001)
        evidence['checks']=checks
        save()
        assert all(checks.values()),checks

        # Laporan yang diunduh memakai hasil setelah koreksi dan neto yang sama.
        async with pg() as db:
            await p.akhiri_penyosohan(db,user=await db.get(User,proses['user'].id),kode=kode)
        from app.web.laporan_sosoh import ambil_data
        from pypdf import PdfReader
        data=await ambil_data(pid)
        assert data['outputs']==after_outputs
        balance=data['balance']
        assert D(str(balance.bahan_kg))==expected_used
        assert abs(D(str(balance.susut.kg))-after_loss)<D('0.000001')
        pdf=await c.get(f'/riwayat-sosoh/{pid}/laporan.pdf')
        assert pdf.status_code==200,pdf.text[:100] if pdf.status_code!=200 else ''
        text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        for number in ('10.000,01','7.000,23','1.000,12','149,56'):
            assert number in text,(number,text)
        evidence['report']=dict(status=pdf.status_code,outputs=data['outputs'],net_kg=balance.bahan_kg,loss_kg=balance.susut.kg,text=text)
        save()
