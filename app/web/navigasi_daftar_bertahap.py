"""Pemasangan adapter aplikasi; tidak menyalin atau menyunting base paket.

Script berada di wilayah isi agar dokumen lama yang memakai PINDAH juga
memasangnya. Efeknya dibatasi ke dua alamat daftar, bukan navigasi global.
"""
def pasang(response, request):
    if response.status_code != 200 or not getattr(request.state, "akun", None):
        return response
    marker = b"<!-- isi-halaman:akhir -->"
    if marker not in response.body:
        return response
    from hmu_tampilan import CAP_ASET
    from app.web.halaman_bertahap import penanda_konteks
    konteks = penanda_konteks(request, request.state.akun)
    script = ('<script src="/static/navigasi-daftar-bertahap.js?v='
              + CAP_ASET + '" data-konteks="' + konteks + '"></script>').encode()
    response.body = response.body.replace(marker, script + marker, 1)
    response.headers["content-length"] = str(len(response.body))
    return response
