# Native function fixture from 17bbcf3eb8715ac5ef072230a3a419bd45420055; AST only, never run.
@router.get('/muatan')
@router.get('/barang-keluar/{perintah:int}/muatan')
async def halaman(request:Request,perintah:int|None=None,akun=Depends(butuh_akun)):
    boleh=await boleh_catat(akun.user)
    wajib(boleh or can_see_financials(akun.user))
    async with SessionLocal() as db:
        from app.web.selesai_muatan import papan_selesai
        data=await papan_selesai(db,perintah)
    return await render_laci(request,'catat_muatan.html',awal=data,boleh_catat=boleh,
        perintah=perintah,item_awal=request.query_params.get('item',''),
        semua_awal=request.query_params.get('semua',''))
