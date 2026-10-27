"""Audit opt-in UI dengan data fixture Postgres lokal dan sesi akun asli."""
import asyncio,json,os,re
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit,parse_qs

import pytest
from sqlalchemy import select
from app.models import User,Warehouse,ProduksiAkun
from hmu_identitas import peran as P,sandi as S
from tests.pg.test_permintaan_empat_langkah import pabrik,_minta,_acc,_kirim
from tests.pg.test_barang_keluar import gudang
from tests.pg.test_draf_keluar import _isi
from tests.pg.test_retur_supplier import asal,skema_retur_timbang,buat,tiket,user,jumlah
from tests.pg.test_retur_supplier_koreksi import keluar_dua,payload,terapkan

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(not os.getenv('HMU_AUDIT_UI_OUT'),reason='Audit browser lokal opt-in')]
OUT=Path(os.getenv('HMU_AUDIT_UI_OUT','/tmp/hmu-audit-tidak-aktif'))
BASE=os.environ.get('HMU_AUDIT_UI_BASE','http://127.0.0.1:8882')
assert urlsplit(BASE).hostname in ('127.0.0.1','localhost')
ROLES={'superadmin':P.SUPERADMIN,'admin':P.ADMIN,'operator_g1':P.OPERATOR,'operator_g2':P.OPERATOR}

async def akun_lokal(pg,case,ids=None):
    ids=ids or {};result={}
    async with pg() as db:
        wh={w.kode_fungsi:w.id for w in (await db.scalars(select(Warehouse))).all()}
        for key,role in ROLES.items():
            u=await db.get(User,ids[key]) if key in ids else User(nama='Uji lokal '+key,role=role,status='aktif')
            u.role=role;u.status='aktif'
            if key.startswith('operator_'):u.default_warehouse_id=wh['g1' if key=='operator_g1' else 'g2']
            db.add(u);await db.flush()
            username='audit_'+case+'_'+key
            db.add(ProduksiAkun(user_id=u.id,username=username,password_hash=S.hash_sandi('rahasia123'),status='aktif',harus_ganti_sandi=False))
            result[key]={'uid':u.id,'username':username,'role':role}
        await db.commit()
    return result

class Audit:
    def __init__(self,case,accounts):self.case=case;self.accounts=accounts;self.contexts={};self.records=[];self.probes=[];self.writes=[]
    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self.p=await async_playwright().start();self.browser=await self.p.chromium.launch()
        for key,a in self.accounts.items():
            c=await self.browser.new_context(viewport={'width':390,'height':740},service_workers='block')
            page=await c.request.get(BASE+'/masuk')
            csrf=re.search(r'name="_csrf" value="([^"]+)"',await page.text())
            fields={'username':a['username'],'sandi':'rahasia123','tujuan':'/'}
            if csrf:fields['_csrf']=csrf[1]
            login=await c.request.post(BASE+'/masuk',form=fields,max_redirects=0)
            assert login.status==303,(key,login.status,(await login.text())[:250])
            me=await c.request.get(BASE+'/api/me');assert me.status==200,(key,await me.text())
            assert (await me.json())['role']==a['role']
            self.contexts[key]=c
        return self
    async def __aexit__(self,*exc):
        for c in self.contexts.values():await c.close()
        await self.browser.close();await self.p.stop()
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/(self.case+'.json')).write_text(json.dumps({'case':self.case,'sumber':'Postgres loopback uji_audit_peran_20261028','hasil':self.records,'probes':self.probes,'mutasi_browser_diblokir':self.writes},ensure_ascii=False,indent=2))
    async def capture(self,state,urls):
        scan=Path(__file__).with_name('_audit_kontrol.js').read_text()
        for key,c in self.contexts.items():
            for i,url in enumerate(urls):
                response=await c.request.get(BASE+url,max_redirects=0)
                status=response.status
                if self.case=='pk':
                    expected=403 if '/permintaan-pk/' in url and (key=='operator_g2' or key=='operator_g1' and state in ('diminta','ditolak')) else 200
                elif self.case=='draf':
                    expected=403 if key=='operator_g1' or key=='operator_g2' and '/draf/' in url else (404 if '/draf/' in url and not url.endswith(self.accounts[key].get('draft_id','NO_DRAFT')) else 200)
                else:
                    expected=403 if key=='operator_g1' or key=='operator_g2' and '/tindakan' in url and '/hasil/' not in url else 200
                assert status==expected,(self.case,state,key,url,status,expected,(await response.text())[:150])
                record={'state':state,'role':key,'url':url,'http':status,'lebar':[]}
                self.records.append(record)
                if status!=200:
                    assert status in (303,403,404),(state,key,url,status,(await response.text())[:150])
                    continue
                html=await response.text()
                if 'text/html' not in response.headers.get('content-type',''):continue
                record['aksi_html']=re.findall(r'buka=([a-z0-9_]+)',html)
                for width in (320,390):
                    page=await c.new_page();await page.set_viewport_size({'width':width,'height':740})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    async def guard(route):
                        if urlsplit(route.request.url).hostname!='127.0.0.1':await route.abort();return
                        if route.request.method!='GET' and urlsplit(route.request.url).path!='/api/actions/pratinjau-kiriman':self.writes.append({'role':key,'url':route.request.url,'method':route.request.method});await route.abort();return
                        if urlsplit(route.request.url).path=='/api/aliran':await route.fulfill(status=204,body='');return
                        await route.continue_()
                    await page.route('**/*',guard)
                    await page.goto(BASE+url,wait_until='load');await page.wait_for_timeout(350)
                    if self.case=='draf' and '/draf/' in url:
                        await page.locator('#draf-kelompok .draf-item').first.wait_for()
                        if state=='tersimpan':
                            await page.wait_for_function('document.querySelector("#draf-saldo-status").textContent.includes("Saldo diperiksa ulang saat perintah dibuat.")')
                    before=await page.evaluate(scan,{'expand':False})
                    after=await page.evaluate(scan,{'expand':True})
                    catalog=await c.request.get(BASE+'/api/actions/menu');menu={a['id']:a for a in await catalog.json()}
                    active=await page.locator('a[href*="buka="]:visible').evaluate_all('(els)=>els.map(e=>({href:e.getAttribute("href"),label:e.textContent.trim()}))')
                    forbidden=[]
                    for link in active:
                        action=parse_qs(urlsplit(link['href']).query).get('buka',[''])[0]
                        if action in menu and not menu[action]['boleh']:forbidden.append(dict(action=action,**link))
                    record_control=await page.locator('main :is(button,a.pilihan__satu,span.pilihan__satu):visible').evaluate_all('(els)=>els.map(e=>({label:e.textContent.trim(),disabled:e.matches(":disabled,[aria-disabled=true]"),href:e.getAttribute("href")}))')
                    if self.case=='retur' and state=='formulir':
                        button=page.get_by_role('button',name='Retur ke Supplier',exact=True)
                        assert await button.count()==1
                        assert await button.is_disabled()==(key=='operator_g2')
                    assert not forbidden,(state,key,url,forbidden)
                    assert not errors,(state,key,url,errors)
                    assert not before['findings'] and not after['findings'],(state,key,url,before['findings'],after['findings'])
                    name=f'{self.case}-{state}-{key}-{i}-{width}.png'
                    await page.screenshot(path=str(OUT/name))
                    record['lebar'].append({'width':width,'awal':before,'rincian':after,'galat_js':errors,'aksi_aktif_tanpa_izin':forbidden,'screenshot':name,'kontrol':record_control})
                    await page.close()
        print('AUDIT_LOKAL '+self.case+' '+state+' selesai',flush=True)
    async def denied(self,key,method,url,body,expected=(403,404)):
        c=self.contexts[key];page=await c.request.get(BASE+'/pengaturan')
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',await page.text())[1]
        r=await c.request.fetch(BASE+url,method=method,data=json.dumps(body),headers={'Content-Type':'application/json','X-CSRF-Token':token},max_redirects=0)
        self.probes.append({'role':key,'method':method,'url':url,'http':r.status})
        assert r.status in expected,(key,method,url,r.status,await r.text())

async def test_pk_semua_status(pg,pabrik):
    from app.services.permintaan_pk import tutup_admin,tolak
    from app.services.seed import seed_master
    await seed_master()
    accounts=await akun_lokal(pg,'pk',{'admin':pabrik['admin'],'operator_g1':pabrik['op1'],'operator_g2':pabrik['op2']})
    async with Audit('pk',accounts) as audit:
        pid=await _minta(pg,pabrik,berat=1000)
        urls=lambda n:[f'/pekerjaan/permintaan/{n}',f'/permintaan-pk/{n}',f'/permintaan-pk/{n}?tab_detail=permintaan']
        await audit.capture('diminta',urls(pid))
        await _acc(pg,pabrik,pid,berat=1000)
        await audit.capture('disetujui',urls(pid))
        await _kirim(pg,pabrik,pid,berat=1000)
        await audit.capture('dikirim',urls(pid))
        for key in ('operator_g1','operator_g2'):
            await audit.denied(key,'POST','/api/actions/tutup-permintaan-pk',dict(permintaan=str(pid),berat=1000))
        async with pg() as db:
            await tutup_admin(db,user=await db.get(User,pabrik['admin']),permintaan_id=pid,berat_final=1000)
        await audit.capture('selesai',urls(pid))
        pid2=await _minta(pg,pabrik,berat=500)
        async with pg() as db:await tolak(db,user=await db.get(User,pabrik['admin']),permintaan_id=pid2,sebab='Skenario uji lokal ditolak')
        await audit.capture('ditolak',urls(pid2))

async def test_draf_tersimpan_dan_kepemilikan(pg,gudang):
    from app.web.draf_keluar import simpan,SimpanDraf
    accounts=await akun_lokal(pg,'draf',{'admin':gudang['adm'],'operator_g2':gudang['op']})
    ids={};isi=await _isi(pg,gudang)
    for key in ('superadmin','admin'):
        ident=uuid4();ids[key]=str(ident);accounts[key]['draft_id']=str(ident)
        async with pg() as db:await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),await db.get(User,accounts[key]['uid']))
    async with Audit('draf',accounts) as audit:
        await audit.capture('tersimpan',['/barang-keluar',f'/barang-keluar/draf/{ids["superadmin"]}',f'/barang-keluar/draf/{ids["admin"]}'])
        for key in ('superadmin','admin'):
            async with pg() as db:
                await simpan(__import__('uuid').UUID(ids[key]),SimpanDraf(revisi=1,kiriman=uuid4(),isi={'pelanggan':'','barang':[{'pilih':'','jumlah':''}]}),await db.get(User,accounts[key]['uid']))
        await audit.capture('parsial',[f'/barang-keluar/draf/{ids["superadmin"]}',f'/barang-keluar/draf/{ids["admin"]}'])
        for key in ROLES:
            other='admin' if key=='superadmin' else 'superadmin'
            await audit.denied(key,'PUT',f'/api/actions/draf-perintah/{ids[other]}',dict(revisi=1,kiriman=str(uuid4()),isi={}))

async def test_retur_pengajuan_sampai_keluar(pg,asal):
    from sqlalchemy import text
    from app.services import retur_supplier as s,retur_supplier_selesai as f
    accounts=await akun_lokal(pg,'retur',{'admin':asal['uid']})
    async with Audit('retur',accounts) as audit:
        await audit.capture('formulir',[f'/barang-masuk/{asal["tid"]}/retur-supplier'])
        async with pg() as db:r=await buat(db,asal);await db.commit();rid=r.id
        await audit.capture('diajukan',[f'/retur-supplier/{rid}'])
        async with pg() as db:
            tid=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.commit()
            await s.hubungkan(db,user=user(asal),identitas=rid,tiket_id=tid);await db.commit()
        await audit.capture('tiket_terbuka',[f'/retur-supplier/{rid}',f'/retur-supplier/{rid}/penyelesaian'])
        async with pg() as db:
            await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5249.50,berat_barang_kg=249.50,status_tiket='SELESAI' WHERE id=:id"),{'id':tid});await db.commit()
        await audit.capture('siap_periksa',[f'/retur-supplier/{rid}/penyelesaian'])
        for key in ('operator_g1','operator_g2'):
            await audit.denied(key,'POST',f'/barang-masuk/{asal["tid"]}/retur-supplier/periksa',dict(jumlah=jumlah(asal),alasan='Mutu tidak sesuai',catatan='Uji lokal'))
        async with pg() as db:
            from app.models.retur_supplier import ReturSupplierItem
            i=await db.scalar(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==rid))
            snap=await f.periksa(db,identitas=rid,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
            await f.catat_keluar(db,identitas=rid,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        await audit.capture('keluar',[f'/riwayat-retur-supplier/{rid}?tab={tab}' for tab in ('ringkasan','timbang','stok','jejak')])

async def test_retur_koreksi_dan_batal(pg,keluar_dua):
    from app.services import retur_supplier_koreksi as k
    x=keluar_dua;accounts=await akun_lokal(pg,'koreksi',{'admin':x['uid']})
    async with Audit('koreksi',accounts) as audit:
        await audit.capture('formulir',[f'/retur-supplier/{x["rid"]}/tindakan?jenis={jenis}' for jenis in ('jumlah','keterangan','batal')])
        async with pg() as db:
            _,rec=await terapkan(db,x,payload(x));loc=f'/retur-supplier/{x["rid"]}/tindakan/hasil/{rec.peristiwa_id}'
        await audit.capture('dikoreksi',[loc,f'/riwayat-retur-supplier/{x["rid"]}?tab=jejak'])
        for key in ('operator_g1','operator_g2'):
            body=payload(x);body.pop('identitas')
            await audit.denied(key,'POST',f'/retur-supplier/{x["rid"]}/tindakan/periksa',body)
        async with pg() as db:
            pp=dict(identitas=x['rid'],kunci=uuid4().hex,jenis='batal',alasan='Pembatalan administratif uji lokal',konfirmasi=True,keberadaan='kembali')
            snap=await k.periksa(db,user=user(x),**pp);await db.commit()
            await k.simpan(db,user=user(x),identitas=x['rid'],kunci=pp['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit()
        await audit.capture('dibatalkan',[f'/riwayat-retur-supplier/{x["rid"]}?tab={tab}' for tab in ('ringkasan','stok','jejak')])

async def _capture_open(audit,state,key,page,url):
    scan=Path(__file__).with_name('_audit_kontrol.js').read_text()
    record={'state':state,'role':key,'url':url,'http':200,'lebar':[]};audit.records.append(record)
    for width in (320,390):
        await page.set_viewport_size({'width':width,'height':740});await page.wait_for_timeout(150)
        before=await page.evaluate(scan,{'expand':False});after=await page.evaluate(scan,{'expand':True})
        assert not before['findings'] and not after['findings'],(key,state,before['findings'],after['findings'])
        name=f'{audit.case}-{state}-{key}-{width}.png';await page.screenshot(path=str(OUT/name))
        controls=await page.locator('button:visible').evaluate_all('(els)=>els.map(e=>({label:e.textContent.trim(),disabled:e.matches(":disabled")}))')
        record['lebar'].append({'width':width,'awal':before,'rincian':after,'galat_js':[],'aksi_aktif_tanpa_izin':[],'kontrol':controls,'screenshot':name})

async def test_retur_tahapan_browser_tanpa_simpan(pg,asal):
    from sqlalchemy import text,func
    from app.models.retur_supplier import ReturSupplier,ReturSupplierKeluar
    from tests.pg.test_retur_supplier import siap_keluar
    accounts=await akun_lokal(pg,'wizard',{'admin':asal['uid']})
    async with Audit('wizard',accounts) as audit:
        # Browser boleh meminta pratinjau lokal; simpan akhir tetap diblokir.
        async def guard(route):
            u=urlsplit(route.request.url)
            if u.hostname!='127.0.0.1':await route.abort();return
            if u.path=='/api/aliran':await route.fulfill(status=204,body='');return
            if route.request.method!='GET' and not u.path.endswith('/periksa'):
                audit.writes.append({'method':route.request.method,'url':route.request.url});await route.abort();return
            await route.continue_()
        for key in ('superadmin','admin'):
            page=await audit.contexts[key].new_page();await page.route('**/*',guard)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            url=f'/barang-masuk/{asal["tid"]}/retur-supplier'
            await page.goto(BASE+url);await page.get_by_role('button',name='Retur ke Supplier',exact=True).click()
            await page.locator('input[name="pilih"]').first.check()
            await page.locator('[data-rsp-qty]').first.fill('5')
            await page.locator('textarea[name="alasan"]').fill('Mutu tidak sesuai berdasarkan pemeriksaan uji lokal')
            await _capture_open(audit,'pilih_jumlah',key,page,url)
            await page.get_by_role('button',name='Periksa pengajuan →',exact=True).click()
            await page.locator('[data-rsp-stage="3"]:visible').wait_for()
            assert await page.locator('[data-rsp-save]').is_enabled()
            await _capture_open(audit,'konfirmasi_pengajuan',key,page,url)
            assert not errors,errors
            await page.close()
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(ReturSupplier))==0
            r,i,_=await siap_keluar(db,asal)
        for key in ('superadmin','admin','operator_g2'):
            page=await audit.contexts[key].new_page();await page.route('**/*',guard)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            url=f'/retur-supplier/{r.id}/penyelesaian';await page.goto(BASE+url)
            await page.get_by_role('button',name='Periksa & lanjutkan',exact=True).click()
            await page.locator('[data-rsf-stage="2"]:visible').wait_for()
            await _capture_open(audit,'konfirmasi_keluar',key,page,url)
            assert not errors,errors
            await page.close()
        async with pg() as db:assert await db.scalar(select(func.count()).select_from(ReturSupplierKeluar))==0

async def test_potret_kontrol_perbaikan(pg,pabrik,keluar_dua):
    accounts=await akun_lokal(pg,'potret',{'admin':pabrik['admin'],'operator_g1':pabrik['op1'],'operator_g2':pabrik['op2']})
    pid=await _minta(pg,pabrik,berat=1000);await _acc(pg,pabrik,pid,berat=1000);await _kirim(pg,pabrik,pid,berat=1000)
    cases=[('pk_tutup',f'/permintaan-pk/{pid}','[data-aksi-permintaan="tutup_permintaan_pk"]:visible','operator_g2'),
           ('retur_mulai',f'/barang-masuk/{keluar_dua["tid"]}/retur-supplier','[data-rsp-mulai]','operator_g1'),
           ('retur_koreksi',f'/riwayat-retur-supplier/{keluar_dua["rid"]}',None,'operator_g1')]
    snapshots=[]
    async with Audit('potret',accounts) as audit:
        for key,c in audit.contexts.items():
            for state,url,selector,denied in cases:
                page=await c.new_page();await page.route('**/api/aliran',lambda r:r.fulfill(status=204,body=''))
                response=await page.goto(BASE+url);expected=403 if key==denied else 200
                assert response.status==expected
                record={'state':state,'role':key,'url':url,'http':response.status}
                if expected==200:
                    await page.wait_for_timeout(150)
                    target=page.locator(selector).first if selector else page.locator('.rsp-actions').first
                    await target.evaluate('(e)=>e.scrollIntoView({block:"center",behavior:"instant"})')
                    if state=='pk_tutup':assert (await target.get_attribute('aria-disabled')=='true')==(key=='operator_g1')
                    if state=='retur_mulai':assert await target.is_disabled()==(key=='operator_g2')
                    if state=='retur_koreksi' and key=='operator_g2':assert await page.get_by_role('button',name='Koreksi pencatatan',exact=True).is_disabled()
                    filename=f'potret-{state}-{key}.png';await page.screenshot(path=str(OUT/filename));record['screenshot']=filename
                snapshots.append(record);await page.close()
    (OUT/'perbandingan.json').write_text(json.dumps(snapshots,indent=2))
