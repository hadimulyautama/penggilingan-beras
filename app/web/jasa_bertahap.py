"""Descriptor/presentasi daftar Jasa; stamp, metadata dan API memakai B1."""
from __future__ import annotations


async def kerangka(request, akun, konteks):
    from app.services.jasa_pelanggan import STATUS
    from app.web.tampilan import render

    status = request.query_params.get('status', '')
    if status not in dict(STATUS):
        status = ''
    cari = request.query_params.get('cari', '').strip()[:200]
    data = konteks.pop('SHELL')
    data.update(url=data['data_url'], filtered=bool(cari or status))
    response = render(request, 'jasa_bertahap.html', **konteks,
                      JASA_SHELL=data, STATUS_PILIHAN=STATUS, tapis=status, cari=cari)
    # Kontrol asli tetap digunakan, tetapi mencetak daftar yang belum dibaca
    # menyesatkan. Ini hanya atribut pada keluaran shell, bukan vendor patch.
    response.body = response.body.replace(
        b'data-js-cetak', b'disabled aria-describedby="jasa-cetak-alasan" data-js-cetak')
    if getattr(request.state, 'frame_kerangka_langsung', False):
        from app.web.jasa_kerangka_aset import paket_lokal
        response.body = paket_lokal(response.body)
    response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    return response
