from copy import deepcopy
from app.web.portal.proses_ringkas import angka,siapkan,status_tahap


def test_format_hanya_menghapus_nol_tanpa_membulatkan_berat():
    for a,b in [('30.251,50 kg','30.251,5 kg'),('≈ 8.000,00 kg','≈ 8.000 kg'),
                ('26.456,76 kg','26.456,76 kg'),('0,375 kg','0,375 kg'),
                ('Belum ditimbang','Belum ditimbang'),('-12,40 kg','-12,4 kg')]:
        assert angka(a)==b


def test_kadar_air_list_tidak_memakai_alat_tes_sebagai_pengganti_mesin():
    base=dict(jenis='pengeringan',status='Sedang berjalan',fakta=[('Kadar air','15.5%'),
        ('Bacaan mesin','16%'),('Acuan progres','Indikator mesin 16%'),('Target kadar air','13%')],
        bobot_pengeringan=[dict(basah='8.000,00 kg',kering=None,terukur=None)])
    original=deepcopy(base)
    r=siapkan(deepcopy(base))
    assert r['kadar_air']=='16%' and r['target_air']=='13%'
    assert r['bobot_pengeringan'][0]['basah']=='8.000 kg'
    assert base==original
    base['fakta']=[('Kadar air','15.5%'),('Target kadar air','13%')]
    assert siapkan(base)['kadar_air'] is None
    assert status_tahap('pengeringan','Dijeda')=='Dijeda'
    assert status_tahap('pendinginan','Sedang berjalan')=='Menunggu dingin'


def test_hasil_timbang_tidak_disebut_perkiraan_atau_belum_ditimbang():
    from app.web.tampilan import templates
    from bs4 import BeautifulSoup
    e=dict(kode='PGR-1',basah='30.251,5 kg',kering='26.456,76 kg',terukur='26.000,25 kg',historis=False)
    macro=templates.env.get_template('portal/_bobot_proses.html').module.bobot_proses
    s=BeautifulSoup(macro([e]),'html.parser')
    assert '26.000,25 kg' in s.get_text() and 'Hasil timbang' in s.get_text()
    assert '26.456,76 kg' not in s.get_text() and 'belum ditimbang' not in s.get_text()
    assert 'Berat setelah kering' in s.get_text()
