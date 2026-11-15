"""Filter-detail-kembali asli; semua permintaan browser berupa GET fixture."""
from contextvars import ContextVar
import json,os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app.services import berjalan
from tests.pg.test_riwayat_pengeringan import pabrik,_klien
from tests.pg.data_pendinginan_baca import isi,WAKTU

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_HISTORI')!='1',reason='Browser fixture eksplisit')]

@pytest.mark.parametrize('role',['operator','admin','superadmin'])
@pytest.mark.parametrize('width',[1440,390])
async def test_alur_baca_pendinginan(pg,pabrik,monkeypatch,role,width):
    from playwright.async_api import async_playwright,expect
    await isi(pg,pabrik,40);monkeypatch.setattr(berjalan,'now_local',lambda:WAKTU)
    out=Path(os.environ['BUKTI_OPERASI']);label=os.environ.get('BUKTI_LABEL','browser')
    current=ContextVar('queries_ui',default=None);requests=[];errors=[];blocked=[]
    def sql(*a):
        q=current.get()
        if q is not None:q.append(1)
    event.listen(Engine,'before_cursor_execute',sql)
    try:
      async with await _klien(pg,peran=role,gudang='Gudang 1') as c:
       async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page(viewport={'width':width,'height':950},service_workers='block',reduced_motion='reduce')
        await page.context.add_cookies([dict(name=k.name,value=k.value,url='http://uji') for k in c.cookies.jar])
        await page.add_init_script('window.EventSource=undefined;window.print=()=>{throw Error("Physical print forbidden")};')
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def route(r):
            req=r.request;u=urlsplit(req.url)
            if u.netloc!='uji' or req.method!='GET' or req.resource_type=='eventsource':
                if req.method!='GET':blocked.append(req.method+' '+u.path)
                return await r.abort()
            queries=[];tok=current.set(queries)
            try:res=await c.get(u.path+('?' +u.query if u.query else ''),headers={k:v for k,v in req.headers.items() if k.lower().startswith('x-')})
            finally:current.reset(tok)
            if u.path=='/pekerjaan' or u.path.startswith('/proses-aktif/'):
                requests.append(dict(path=u.path,query=u.query,status=res.status_code,queries=len(queries),bytes=len(res.content)))
            await r.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items() if k.lower() not in ('content-length','content-encoding')})
        await page.route('**/*',route)
        try:
            await page.goto('http://uji/pekerjaan?tab=berjalan')
            form=page.locator('form[role=search]');await form.wait_for(state='visible')
            await form.locator('[name=cari]').fill('OPR')
            await form.get_by_role('button',name='Cari',exact=True).focus();await page.keyboard.press('Enter')
            await page.wait_for_function('new URLSearchParams(location.search).get("cari")==="OPR"')
            origin=page.url
            target=page.locator('.proses-aktif-list__row').filter(has=page.locator('strong',has_text='OPR-000')).locator('a').first
            await target.focus();await page.keyboard.press('Enter')
            await expect(page.locator('[data-pendinginan-aktif]')).to_be_visible()
            await expect(page.locator('.rhs-code')).to_have_text('OPR-000')
            await page.locator('.rhs-back').focus();await page.keyboard.press('Enter')
            await expect(form).to_be_visible()
            assert parse_qs(urlsplit(page.url).query)==parse_qs(urlsplit(origin).query)
            assert await form.locator('[name=cari]').input_value()=='OPR'
            box=await target.bounding_box();focused=await target.evaluate('e=>document.activeElement===e')
            recovery=0
            await page.mouse.move(width//2,500)
            visible=bool(box and 60<=box['y']<900)
            while not visible and recovery<25:
                await page.mouse.wheel(0,700);await page.wait_for_timeout(75);recovery+=1
                rect=await target.bounding_box();visible=bool(rect and 60<=rect['y']<900)
            assert visible,'Fixture could not recover target by ordinary scroll'
            result=dict(role=role,width=width,origin=origin,returned=page.url,target_on_return=box,focused=focused,
                steps=['buka-daftar','isi-filter','Enter-cari','Enter-detail','Enter-kembali'],
                recovery_scrolls_700px=recovery,requests=requests,errors=errors,blocked_mutations=blocked)
            (out/f'{label}-{role}-{width}.json').write_text(json.dumps(result,indent=2)+'\n')
            await page.screenshot(path=str(out/f'{label}-{role}-{width}.png'))
            assert not errors and not blocked
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        finally:
            await page.unroute_all(behavior='ignoreErrors');await browser.close()
    finally:event.remove(Engine,'before_cursor_execute',sql)
