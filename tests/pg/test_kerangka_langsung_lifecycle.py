"""Barrier lifecycle native; file ini juga dapat disalin exact untuk kontrol eae.

Tidak mengimpor helper prototipe yang tidak ada pada baseline. Semua halaman,
footer, session dan pembaca berasal checkout yang sedang diuji.
"""
import asyncio
import hashlib
import json
import os
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


async def test_footer_asli_tiga_swap_dan_json_lama(pg,lengkap):
    """R1 paired; tidak menganggap src dilepas pasti dieksekusi atau dibatalkan."""
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
        before=await _sidik(pg);reads=await bungkus(c)
        async with peramban(c,390) as (page,t):
            terminals={};terminal=asyncio.Event();old_id=None;old_request=None
            def terminal_script(info):
                terminals[info['id']]=info
                if info['id']==old_id:terminal.set()
            await page.expose_function('__nativeMenuTerminal',terminal_script)
            await instrumentasi(page)
            await page.goto(BASE+'/kabar')
            entered,release,done=asyncio.Event(),asyncio.Event(),asyncio.Event()
            asset=dict(selected=False,resource=None,delivered=False,cancelled=False)
            async def tahan_src(route):
                nonlocal old_request
                request=route.request
                if request.resource_type!='script' or asset['selected']:
                    await route.fallback();return
                old_request=request
                asset.update(selected=True,resource=request.resource_type,url=request.url)
                response=await c.request('GET','/static/menu-layar.js?'+request.url.split('?',1)[1])
                asset['body_sha256']=hashlib.sha256(response.content).hexdigest()
                import hmu_tampilan
                assert asset['body_sha256']==hashlib.sha256((Path(hmu_tampilan.__file__).parent/'static/menu-layar.js').read_bytes()).hexdigest()
                entered.set()
                try:
                    await release.wait()
                    await route.fulfill(status=response.status_code,body=response.content,
                        headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding','transfer-encoding','set-cookie'}})
                    asset['delivered']=True
                except BrowserError:
                    if not request.failure:raise
                    asset['cancelled']=True
                finally:done.set()
            def request_gagal(request):
                if request==old_request:
                    asset['terminal']='requestfailed';terminal.set()
            page.on('requestfailed',request_gagal)
            await page.route('**/static/menu-layar.js*',tahan_src)
            try:
                await menu(page,'/barang-masuk')
                await asyncio.wait_for(entered.wait(),15)
                await frame(page,'[data-bm-page]')
                old_id=await page.evaluate("src=>__life.menuScripts.find(r=>r.src===src&&r.alamat.startsWith('/barang-masuk'))?.id",asset['url'])
                assert old_id is not None,'Indeterminate: node SCRIPT native tidak berhasil diamati'
                if old_id in terminals:terminal.set()
                # Tiga frame nyata dipasang selagi src frame pertama ditahan.
                await menu(page,'/kabar');await frame(page,'.kb')
                await menu(page,'/barang-masuk');await frame(page,'[data-bm-page]')
                await menu(page,'/kabar');await frame(page,'.kb')
                release.set();await asyncio.wait_for(done.wait(),15)
                try:
                    await asyncio.wait_for(terminal.wait(),15)
                    await page.wait_for_function("__life.menuHandlers.some(r=>r.active&&r.target==='window'&&r.jenis==='resize'&&r.scriptConnected&&r.main===document.getElementById('isi-halaman'))",timeout=15000)
                except Exception:
                    simpan('R1-indeterminate',dict(asset=asset,old_script=terminals.get(old_id),reason='Terminal oldsrc atau registrasi currentframe belum terverifikasi'))
                    raise
                await flush(page)
                start=await page.evaluate('__life.escapeWrites')
                await page.locator('#buka-laci').click()
                await expect(page.locator('#laci')).to_be_visible()
                await page.keyboard.press('Escape')
                await expect(page.locator('#laci')).to_be_hidden()
                assert await page.evaluate('__life.escapeWrites')==start+1,'Satu Escape harus satu penutupan laci current'
                await page.wait_for_function("__life.menuHandlers.some(r=>r.active&&r.target==='window'&&r.jenis==='resize')")
                active=await page.evaluate("__life.menuHandlers.filter(r=>r.active).map(({fn,wrapped,main,...r})=>({...r,currentMain:main===document.getElementById('isi-halaman')}))")
                at=await page.evaluate('__life.pushes.length')
                resize_before=await page.evaluate("({events:__life.resizeEvents,calls:__life.menuHandlers.filter(r=>r.active&&r.target==='window'&&r.jenis==='resize').reduce((s,r)=>s+r.calls,0)})")
                count=len(reads)
                await page.set_viewport_size({'width':430,'height':900});await flush(page)
                await page.set_viewport_size({'width':390,'height':900});await flush(page)
                resize_after=await page.evaluate("({events:__life.resizeEvents,calls:__life.menuHandlers.filter(r=>r.active&&r.target==='window'&&r.jenis==='resize').reduce((s,r)=>s+r.calls,0)})")
                observed=dict(control=os.environ.get('OWNER_SOURCE_MODE','candidate'),asset={**asset,'old_script_terminal':terminals.get(old_id)},reads=reads,active_menu_handlers=active,resize_before=resize_before,resize_after=resize_after,three_full_swaps=True,Escape_current_close_once=True,all_public_tables_unchanged=await _sidik(pg)==before,business_POSTs=len(t['posts']))
                simpan('R1-footer',observed)
                assert observed['all_public_tables_unchanged'] and not t['posts']
                assert await page.evaluate('__life.pushes.length')==at
                assert len([r for r in active if r['target']=='window' and r['jenis']=='resize'])==1,'Listener resize current dari asset native tidak boleh ganda'
                assert resize_after['events']>resize_before['events']
                assert resize_after['calls']-resize_before['calls']==resize_after['events']-resize_before['events']
                assert not any(r['url'].split('?')[0] in {'/barang-masuk','/pekerjaan',BM,WORK} for r in reads[count:]),'Resize murni tidak membaca ulang halaman/data'
            finally:
                release.set()
                await page.unroute('**/static/menu-layar.js*',tahan_src)
                page.remove_listener('requestfailed',request_gagal)
            # A1 -> Berjalan -> A2. Lepaskan A1 hanya setelah A2 sudah ada.
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
                current=await frame(page,'[data-bm-page]')
                r1.set();await asyncio.wait_for(d1.wait(),15)
                t['completed'][BM]=d2
                await flush(page)
                assert await current.evaluate('n=>n.isConnected')
                await expect(page.locator('[data-bm-results]')).to_have_attribute('aria-busy','true')
                rb.set();await asyncio.wait_for(db.wait(),15);await flush(page)
                assert await current.evaluate('n=>n.isConnected')
                r2.set();await asyncio.wait_for(d2.wait(),15);await bm_siap(page)
                assert not t['posts'] and not t['errors'],t['errors']
                assert await _sidik(pg)==before
                simpan('lateJSON-A-B-A',dict(control=os.environ.get('OWNER_SOURCE_MODE','candidate'),old_JSON_not_installed=True,reads=reads,all_public_tables_unchanged=True,business_POSTs=0))
            finally:
                r1.set();rb.set();r2.set()


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
                await page.evaluate('()=>PINDAH.segarkan()')
                await asyncio.wait_for(entered.wait(),15)
                await menu(page,'/kabar')
                t['gates'][BM]=(fresh,fresh_release);t['completed'][BM]=fresh_done
                await menu(page,'/barang-masuk');await asyncio.wait_for(fresh.wait(),15)
                fresh_release.set();await asyncio.wait_for(fresh_done.wait(),15);await bm_siap(page)
                current=await page.locator('[data-bm-page]').element_handle()
                await page.locator('input[name=cari]:visible').fill('Isian baru fixture')
                release.set();await asyncio.wait_for(done.wait(),15);await flush(page)
                observed=dict(control=os.environ.get('OWNER_SOURCE_MODE','candidate'),public_API_only=True,visible_native_data_kirim=visible_callers,native_transaction_callers_not_invoked=True,
                    fresh_root_retained=await current.evaluate('n=>n.isConnected'),search_value=await page.locator('input[name=cari]:visible').input_value(),reads=reads,
                    all_public_tables_unchanged=await _sidik(pg)==before,business_POSTs=len(t['posts']))
                simpan('R2-publicAPI',observed)
                assert observed['all_public_tables_unchanged'] and not t['posts'] and not t['errors'],t['errors']
                assert observed['fresh_root_retained'],'Refresh generasi A lama tidak boleh menimpa A baru'
                assert observed['search_value']=='Isian baru fixture'
            finally:
                release.set();fresh_release.set()
