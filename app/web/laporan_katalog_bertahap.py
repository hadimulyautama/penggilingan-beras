"""Native public catalog structure; native GET retains actual guards/counts."""

async def kerangka(request,akun):
    from app.web.portal.scope import is_customer_read
    if request.url.path!='/laporan' or request.url.query or is_customer_read(request):
        return None
    from app.web.halaman_bertahap import konteks_kerangka,penanda_konteks
    from app.web.laporan_navigasi import siapkan
    from app.web.laporan import _daftar,boleh_lihat,PERIODE
    from app.web.tampilan import render,templates
    context=await konteks_kerangka(request,akun)
    navigation={};await siapkan(request,navigation)
    data=dict(daftar=[dict(kode=l.kode,nama=l.nama,arti=l.arti,berperiode=l.berperiode,
                         boleh=boleh_lihat(akun.user,l)) for l in _daftar()],periode=PERIODE)
    template=templates.get_template('laporan.html')
    body=''.join(template.blocks['isi'](template.new_context(data)))
    return render(request,'laporan_katalog_bertahap.html',**context,
        layar='laporan',MENU_AKTIF='laporan',LAPORAN_NAV=None,
        KATALOG_NATIVE=body,KATALOG_NAV=navigation['LAPORAN_NAV'],
        KATALOG_STAMP=penanda_konteks(request,akun)+'|/laporan')
