"""Klik muat memakai HTML/API asli dan browser pada data Postgres sementara."""
from urllib.parse import urlsplit
import pytest
from sqlalchemy import select
from app.models import User, ActivityLog
from tests.pg.test_barang_keluar import gudang, _perintah, _klien, _stok
from hmu_identitas import peran as P

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]
BASE='http://127.0.0.1:59997'


@pytest.mark.parametrize('role',[P.OPERATOR,P.SUPERADMIN])
async def test_operator_dan_super_admin_membuka_muat_dari_perintah(pg,gudang,role):
    from playwright.async_api import async_playwright, expect
    r=await _perintah(pg,gudang,karung=40)
    uid=gudang['op'] if role==P.OPERATOR else gudang['adm']
    async with pg() as db:
        u=await db.get(User,uid);u.role=role;await db.commit()
        audit_awal=(await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()
    async with await _klien(pg,uid,'uji-browser-muat') as client:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            ctx=await browser.new_context(viewport={'width':390,'height':840},service_workers='block')
            await ctx.add_cookies([{'name':k.name,'value':k.value,'url':BASE} for k in client.cookies.jar])
            writes=[]
            async def aplikasi(route):
                req=route.request
                if not req.url.startswith(BASE+'/'):
                    await route.abort();return
                if req.method!='GET':
                    writes.append(req.url);await route.abort();return
                target=urlsplit(req.url)
                if target.path=='/api/aliran':
                    await route.fulfill(status=204,body='');return
                response=await client.get(target.path+('?' + target.query if target.query else ''),
                    headers={k:v for k,v in req.headers.items() if k.lower() in ('x-pindah','accept')})
                headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding')}
                await route.fulfill(status=response.status_code,headers=headers,body=response.content)
            await ctx.route('**/*',aplikasi)
            page=await ctx.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto(BASE+f'/barang-keluar/{r.rec.id}')
            await page.get_by_role('link',name='Muat semua sesuai perintah',exact=True).click()
            await expect(page).to_have_url(BASE+f'/muatan?perintah={r.rec.id}')
            await expect(page.locator('[data-catat-muatan]')).to_be_visible()
            await expect(page.get_by_role('button',name='Muat semua sesuai perintah',exact=True)).to_be_enabled()
            assert not errors,errors
            assert not writes,writes
            await ctx.close();await browser.close()
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        assert (await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()==audit_awal
        assert (await db.get(User,uid)).role==role
