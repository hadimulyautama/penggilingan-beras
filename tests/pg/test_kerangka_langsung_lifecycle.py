"""Barrier lifecycle native; file ini juga dapat disalin exact untuk kontrol eae.

Tidak mengimpor helper prototipe yang tidak ada pada baseline. Semua halaman,
footer, session dan pembaca berasal checkout yang sedang diuji.
"""
import asyncio
import hashlib
import json
import os
from urllib.parse import urlsplit
from pathlib import Path

import pytest
from playwright.async_api import expect, Error as BrowserError
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE

pytestmark=pytest.mark.asyncio
BM='/api/halaman-bertahap/barang-masuk'
WORK='/api/halaman-bertahap/pekerjaan'
SRC='/static/barang-masuk-pencarian.js'


@pytest.fixture(autouse=True)
def pin_runtime():
    import app.main
    import hmu_tampilan
    expected=Path(os.environ.get('OWNER_EXPECTED_SOURCE',str(Path(__file__).resolve().parents[2]))).resolve()
    assert Path(app.main.__file__).resolve()==expected/'app/main.py'
    assert Path(hmu_tampilan.__file__).resolve()==expected/'hmu_tampilan/__init__.py'
    sdk=hashlib.sha256((expected/'hmu_tampilan/static/pindah.js').read_bytes()).hexdigest()
    if os.environ.get('OWNER_EXPECTED_SDK_SHA'):
        assert sdk==os.environ['OWNER_EXPECTED_SDK_SHA']
    simpan('runtime-source',dict(app_main=str(Path(app.main.__file__).resolve()),package=str(Path(hmu_tampilan.__file__).resolve()),SDK_sha256=sdk,mode=os.environ.get('OWNER_SOURCE_MODE','candidate')))


async def menu(page,path):
    await page.locator('#buka-laci').click()
    await expect(page.locator('#laci')).to_be_visible()
    await page.locator('#laci a[href="'+path+'"]').click()
    await expect(page).to_have_url(BASE+path)
    await expect(page.locator('.halaman-memuat')).to_have_count(0)


async def bm_siap(page):
    await expect(page.locator('[data-bm-page]:not([data-bm-shell])')).to_be_visible()
    await expect(page.locator('[data-bm-results]')).not_to_have_attribute('aria-busy','true')


async def frame(page,selector):
    await expect(page.locator(selector)).to_be_visible()
    return await page.locator(selector).element_handle()


async def flush(page):
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


def simpan(name,data):
    if os.environ.get('PHASE_OUT'):
        engine=os.environ.get('OWNER_BROWSER','chromium')
        (Path(os.environ['PHASE_OUT'])/(engine+'-'+name+'.json')).write_text(json.dumps(data,indent=2)+'\n')


async def instrumentasi(page):
    await page.add_init_script("""(()=>{
      window.__life={pushes:[],escapeWrites:0,oldAsset:null};
      const push=history.pushState;history.pushState=function(...a){__life.pushes.push(a[2]);return push.apply(this,a);};
      __life.menuHandlers=[];__life.resizeEvents=0;__life.menuScripts=[];
      const diawasi=new WeakSet();
      function awasiScript(n){
        if(n.tagName!=='SCRIPT'||!n.src||!n.isConnected||diawasi.has(n)||new URL(n.src).pathname!=='/static/menu-layar.js')return;
        diawasi.add(n);const rec={id:__life.menuScripts.length+1,node:n,src:n.src,alamat:location.pathname+location.search,terminal:null,connectedAtTerminal:null};__life.menuScripts.push(rec);
        for(const jenis of ['load','error'])n.addEventListener(jenis,()=>{rec.terminal=jenis;rec.connectedAtTerminal=n.isConnected;if(window.__nativeMenuTerminal)window.__nativeMenuTerminal({id:rec.id,kind:jenis,connected:rec.connectedAtTerminal});},{once:true});
      }
      new MutationObserver(changes=>{for(const c of changes)for(const n of c.addedNodes){if(n.nodeType!==1)continue;awasiScript(n);n.querySelectorAll?.('script[src]').forEach(awasiScript);}}).observe(document,{childList:true,subtree:true});
      const tambah=EventTarget.prototype.addEventListener,hapus=EventTarget.prototype.removeEventListener,catatan=new WeakMap();
      EventTarget.prototype.addEventListener=function(jenis,fn,opsi){
        const src=document.currentScript?.src||'';
        if(src&&new URL(src).pathname==='/static/menu-layar.js'&&typeof fn==='function'){
          let daftar=catatan.get(this);if(!daftar){daftar=[];catatan.set(this,daftar);}
          const capture=typeof opsi==='boolean'?opsi:!!opsi?.capture;
          let rec=daftar.find(r=>r.jenis===jenis&&r.fn===fn&&r.capture===capture);
          if(!rec){rec={jenis,fn,capture,active:true,calls:0,target:this===window?'window':this===window.visualViewport?'visualViewport':this.id||this.tagName,scriptConnected:document.currentScript.isConnected,alamat:location.pathname+location.search,main:document.getElementById('isi-halaman')};rec.wrapped=function(...a){rec.calls++;return fn.apply(this,a);};daftar.push(rec);__life.menuHandlers.push(rec);}else rec.active=true;
          return tambah.call(this,jenis,rec.wrapped,opsi);
        }
        return tambah.call(this,jenis,fn,opsi);
      };
      EventTarget.prototype.removeEventListener=function(jenis,fn,opsi){
        const capture=typeof opsi==='boolean'?opsi:!!opsi?.capture;
        const rec=catatan.get(this)?.find(r=>r.jenis===jenis&&r.fn===fn&&r.capture===capture);
        if(rec){rec.active=false;return hapus.call(this,jenis,rec.wrapped,opsi);}
        return hapus.call(this,jenis,fn,opsi);
      };
      tambah.call(window,'resize',()=>__life.resizeEvents++);
      const set=Element.prototype.setAttribute;Element.prototype.setAttribute=function(k,v){
        if(this.isConnected&&this.id==='buka-laci'&&k==='aria-expanded'&&v==='false')__life.escapeWrites++;
        return set.call(this,k,v);
      };
    })();""")


async def buka_kerja_berjalan(page):
    await menu(page,'/pekerjaan')
    await expect(page.locator('nav[aria-label="Tab pekerjaan"]')).to_be_visible()
    await page.locator('nav[aria-label="Tab pekerjaan"] a[href="/pekerjaan?tab=berjalan"]').click()
    await expect(page).to_have_url(BASE+'/pekerjaan?tab=berjalan')


async def bungkus(c):
    native=c.request;reads=[]
    async def request(method,url,**kw):
        item=dict(method=method,url=str(url),headers={k:v for k,v in kw.get('headers',{}).items() if k.lower() in {'x-pindah','x-kerangka-halaman','x-barang-masuk-cari'}})
        reads.append(item)
        assert method=='GET','Uji lifecycle tidak mengirim transaksi'
        response=await native(method,url,**kw)
        if str(url).split('?')[0]=='/static/pindah.js':
            sdk=hashlib.sha256(response.content).hexdigest()
            import app.main
            expected=Path(app.main.__file__).resolve().parents[1]/'hmu_tampilan/static/pindah.js'
            assert sdk==hashlib.sha256(expected.read_bytes()).hexdigest()
            item['served_SDK_sha256']=sdk
        return response
    c.request=request
    return reads


async def amati_controller(page):
    await page.add_init_script("""(()=>{
      window.__bmR1={scripts:[],roots:[],fetches:[]};const ids=new WeakMap();
      function id(root){if(!root)return null;let n=ids.get(root);if(!n){n=__bmR1.roots.length+1;ids.set(root,n);__bmR1.roots.push({id:n,node:root,siapChanges:0});}return n;}
      function root(){return document.querySelector('[data-bm-page]');}
      const watched=new WeakSet();
      function script(n){if(n.tagName!=='SCRIPT'||!n.src||!n.isConnected||watched.has(n)||new URL(n.src).pathname!=='/static/barang-masuk-pencarian.js')return;
        watched.add(n);const r={id:__bmR1.scripts.length+1,node:n,src:n.src,root:id(root()),terminal:null};__bmR1.scripts.push(r);
        for(const kind of ['load','error'])n.addEventListener(kind,()=>{r.terminal=kind;r.connectedAtTerminal=n.isConnected;window.__controllerTerminal?.({id:r.id,kind,connected:n.isConnected});},{once:true});}
      new MutationObserver(changes=>{for(const c of changes){if(c.type==='attributes'&&c.target.matches('[data-bm-page]')){id(c.target);__bmR1.roots[ids.get(c.target)-1].siapChanges++;continue;}for(const n of c.addedNodes){if(n.nodeType!==1)continue;if(n.matches('[data-bm-page]'))id(n);n.querySelectorAll('[data-bm-page]').forEach(id);script(n);n.querySelectorAll('script[src]').forEach(script);}}}).observe(document,{childList:true,subtree:true,attributes:true,attributeFilter:['data-siap']});
      const native=window.fetch;window.fetch=function(...args){const u=new URL(typeof args[0]==='string'?args[0]:args[0].url,location.href);let r=null;
        if(u.pathname==='/api/halaman-bertahap/barang-masuk'||u.pathname==='/api/halaman-bertahap/pekerjaan'||u.pathname==='/barang-masuk'){r={path:u.pathname,query:u.search,owner:id(root()),method:args[1]?.method||'GET',terminal:null};__bmR1.fetches.push(r);}
        return native.apply(this,args).then(v=>{if(r){r.terminal='response';r.status=v.status;}return v;},e=>{if(r)r.terminal=e.name==='AbortError'?'aborted':'rejected';throw e;});};
    })();""")

async def snapshot(page):
    return await page.evaluate("""()=>({scripts:__bmR1.scripts.map(({node,...r})=>({...r,src:new URL(r.src).pathname,isConnected:node.isConnected})),roots:__bmR1.roots.map(({node,...r})=>({...r,isConnected:node.isConnected,siap:node.dataset.siap||null})),fetches:__bmR1.fetches,currentRoot:__bmR1.roots.find(r=>r.node===document.querySelector('[data-bm-page]'))?.id})""")

async def test_controller_src_tertunda_tiga_frame_native(pg,lengkap):
    """A1→Kabar→A2→Kabar→A3; src lama boleh execute, owner aktif satu."""
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
        before=await _sidik(pg);reads=await bungkus(c)
        async with peramban(c,390) as (page,t):
            await amati_controller(page)
            terminals={};terminal=asyncio.Event();old_id=None;old_request=None
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            asset={'selected':False,'resource_type':None,'delivered':False,'cancelled':False}
            def terminal_script(info):
                terminals[info['id']]=info
                if info['id']==old_id:terminal.set()
            def request_failed(r):
                if r==old_request:asset['request_terminal']='failed';terminal.set()
            await page.expose_function('__controllerTerminal',terminal_script)
            page.on('requestfailed',request_failed)
            async def tahan_src(route):
                nonlocal old_request
                request=route.request
                if request.resource_type!='script' or asset['selected']:
                    await route.fallback();return
                asset.update(selected=True,resource_type=request.resource_type,path=urlsplit(request.url).path)
                old_request=request;u=urlsplit(request.url)
                response=await c.request('GET',u.path+('?' + u.query if u.query else ''))
                import app.main
                native_path=Path(app.main.__file__).resolve().parents[1]/'app/web/static/barang-masuk-pencarian.js'
                asset['body_sha256']=hashlib.sha256(response.content).hexdigest()
                assert asset['body_sha256']==hashlib.sha256(native_path.read_bytes()).hexdigest()
                entered.set()
                try:
                    await release.wait()
                    await route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding','transfer-encoding','set-cookie'}})
                    asset['delivered']=True
                except BrowserError:
                    if not request.failure:raise
                    asset['cancelled']=True
                finally:done.set()
            await page.goto(BASE+'/kabar')
            await page.route('**/static/barang-masuk-pencarian.js*',tahan_src)
            observation={}
            try:
                await menu(page,'/barang-masuk');await asyncio.wait_for(entered.wait(),15)
                await expect(page.locator('[data-bm-page]')).to_be_visible()
                old_id=await page.evaluate("__bmR1.scripts.find(r=>r.node.isConnected)?.id")
                assert old_id is not None,'Indeterminate: old SCRIPT node not observed'
                if old_id in terminals:terminal.set()
                await menu(page,'/kabar')
                await menu(page,'/barang-masuk');await expect(page.locator('[data-bm-page]')).to_be_visible()
                await menu(page,'/kabar')
                await menu(page,'/barang-masuk');await expect(page.locator('[data-bm-page]')).to_be_visible()
                a3=await page.locator('[data-bm-page]').element_handle()
                a3_id=await page.evaluate("__bmR1.roots.find(r=>r.node===document.querySelector('[data-bm-page]'))?.id")
                assert a3_id is not None
                release.set();await asyncio.wait_for(done.wait(),15)
                await asyncio.wait_for(terminal.wait(),15)
                await bm_siap(page);await expect(page.locator('[data-bm-page]')).to_have_attribute('data-siap','1')
                await flush(page)
                observation=await snapshot(page)
                assert len([r for r in observation['fetches'] if r['path']==BM and r['owner']==a3_id])==1,'Current A3 shell must own one initial data GET'
                assert all(r['siapChanges']==1 for r in observation['roots'] if r['siapChanges']),'Each initialized root must cross native siap guard once'
                # Satu submit native yang terlihat harus menghasilkan satu GET pembaca,
                # bukan duplikasi handler. Tidak ada perubahan transaksi/otorisasi.
                start=len([r for r in reads if r['headers'].get('x-barang-masuk-cari')=='1'])
                search=page.locator('[data-bm-search] input[name=cari]:visible')
                await search.fill('R1 usual fixture search');await search.press('Enter')
                await page.wait_for_function("__bmR1.fetches.some(r=>r.path==='/barang-masuk'&&r.query.includes('R1')&&r.terminal==='response')")
                await flush(page)
                assert len([r for r in reads if r['headers'].get('x-barang-masuk-cari')=='1'])==start+1
                observation=await snapshot(page)
                observation.update(control=os.environ.get('OWNER_SOURCE_MODE','candidate'),asset=asset,old_script_id=old_id,old_terminal=terminals.get(old_id),A3_initial_root=a3_id,read_requests=reads,one_native_search_GET=True,all_public_tables_unchanged=await _sidik(pg)==before,business_POSTs=len(t['posts']),page_error_count=len(t['errors']))
                assert observation['all_public_tables_unchanged'] and not t['posts'] and not t['errors']
            finally:
                release.set()
                if asset['selected'] and not done.is_set():await asyncio.wait_for(done.wait(),15)
                await page.unroute('**/static/barang-masuk-pencarian.js*',tahan_src)
                page.remove_listener('requestfailed',request_failed)
                observation.update(final=await snapshot(page),asset=asset,old_terminal=terminals.get(old_id),no_PWA_claim=True)
                simpan('R1-controller',observation)

async def test_json_lama_A_berjalan_A(pg,lengkap):
    """Respons reader nyata ditahan; pisahkan aborted/response yang teramati."""
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
        before=await _sidik(pg);reads=await bungkus(c)
        async with peramban(c,390) as (page,t):
            await amati_controller(page);await page.goto(BASE+'/kabar')
            e1,r1,d1=asyncio.Event(),asyncio.Event(),asyncio.Event()
            eb,rb,db=asyncio.Event(),asyncio.Event(),asyncio.Event()
            e2,r2,d2=asyncio.Event(),asyncio.Event(),asyncio.Event()
            t['gates'][BM]=(e1,r1);t['completed'][BM]=d1
            try:
                await menu(page,'/barang-masuk');await asyncio.wait_for(e1.wait(),15)
                t['gates'][WORK]=(eb,rb);t['completed'][WORK]=db
                await buka_kerja_berjalan(page);await asyncio.wait_for(eb.wait(),15)
                t['gates'][BM]=(e2,r2)
                await menu(page,'/barang-masuk');await asyncio.wait_for(e2.wait(),15)
                current=await page.locator('[data-bm-page]').element_handle()
                r1.set();await asyncio.wait_for(d1.wait(),15);t['completed'][BM]=d2
                await flush(page);assert await current.evaluate('n=>n.isConnected')
                await expect(page.locator('[data-bm-results]')).to_have_attribute('aria-busy','true')
                rb.set();await asyncio.wait_for(db.wait(),15);await flush(page)
                assert await current.evaluate('n=>n.isConnected')
                r2.set();await asyncio.wait_for(d2.wait(),15);await bm_siap(page)
                observation=await snapshot(page)
                observation.update(control=os.environ.get('OWNER_SOURCE_MODE','candidate'),old_JSON_not_installed=True,read_requests=reads,all_public_tables_unchanged=await _sidik(pg)==before,business_POSTs=len(t['posts']),page_error_count=len(t['errors']),no_PWA_claim=True)
                simpan('R1-lateJSON',observation)
                assert observation['all_public_tables_unchanged'] and not t['posts'] and not t['errors']
            finally:r1.set();rb.set();r2.set()


async def test_segarkan_public_api_A_B_A(pg,lengkap):
    """R2 kontrol public API; bukan aksi operator/write yang direkayasa sukses."""
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
        before=await _sidik(pg);reads=await bungkus(c)
        async with peramban(c,390) as (page,t):
            await instrumentasi(page);await page.goto(BASE+'/kabar')
            await menu(page,'/barang-masuk');await bm_siap(page)
            visible_callers=await page.locator('[data-kirim]:visible').count()
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            fresh,fresh_release,fresh_done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            t['gates']['/barang-masuk']=(entered,release);t['completed']['/barang-masuk']=done
            try:
                await page.evaluate('()=>{window.__refreshDone=0;PINDAH.segarkan(()=>window.__refreshDone++);}')
                await asyncio.wait_for(entered.wait(),15)
                await menu(page,'/kabar')
                t['gates'][BM]=(fresh,fresh_release);t['completed'][BM]=fresh_done
                await menu(page,'/barang-masuk');await asyncio.wait_for(fresh.wait(),15)
                fresh_release.set();await asyncio.wait_for(fresh_done.wait(),15);await bm_siap(page)
                current=await page.locator('[data-bm-page]').element_handle()
                await page.locator('input[name=cari]:visible').fill('Isian baru fixture')
                release.set();await asyncio.wait_for(done.wait(),15)
                await page.wait_for_function('window.__refreshDone===1')
                await flush(page)
                observed=dict(callback_count=await page.evaluate('window.__refreshDone'),control=os.environ.get('OWNER_SOURCE_MODE','candidate'),public_API_only=True,visible_native_data_kirim=visible_callers,native_transaction_callers_not_invoked=True,
                    fresh_root_retained=await current.evaluate('n=>n.isConnected'),search_value=await page.locator('input[name=cari]:visible').input_value(),reads=reads,
                    all_public_tables_unchanged=await _sidik(pg)==before,business_POSTs=len(t['posts']))
                simpan('R2-publicAPI',observed)
                assert observed['all_public_tables_unchanged'] and not t['posts'] and not t['errors'],t['errors']
                assert observed['callback_count']==1
                assert observed['fresh_root_retained'],'Refresh generasi A lama tidak boleh menimpa A baru'
                assert observed['search_value']=='Isian baru fixture'
            finally:
                release.set();fresh_release.set()


async def test_segarkan_tanpa_navigasi_tetap_memasang_dan_callback_sekali(pg,lengkap):
    """Kontrol positif: guard generasi tidak menahan refresh halaman yang sama."""
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
        before=await _sidik(pg);reads=await bungkus(c)
        async with peramban(c,390) as (page,t):
            await page.goto(BASE+'/kabar');await menu(page,'/barang-masuk');await bm_siap(page)
            current=await page.locator('[data-bm-page]').element_handle()
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            t['gates']['/barang-masuk']=(entered,release);t['completed']['/barang-masuk']=done
            try:
                await page.evaluate('()=>{window.__refreshDone=0;PINDAH.segarkan(()=>window.__refreshDone++);}')
                await asyncio.wait_for(entered.wait(),15)
                assert await current.evaluate('n=>n.isConnected')
                assert await page.evaluate('window.__refreshDone')==0
                release.set();await asyncio.wait_for(done.wait(),15)
                await page.wait_for_function('window.__refreshDone===1');await bm_siap(page)
                observed=dict(public_API_only=True,callback_count=await page.evaluate('window.__refreshDone'),old_root_replaced=not await current.evaluate('n=>n.isConnected'),read_requests=reads,all_public_tables_unchanged=await _sidik(pg)==before,business_POSTs=len(t['posts']))
                simpan('R2-positive-refresh',observed)
                assert observed['callback_count']==1 and observed['old_root_replaced']
                assert observed['all_public_tables_unchanged'] and not t['posts'] and not t['errors'],t['errors']
            finally:release.set()
