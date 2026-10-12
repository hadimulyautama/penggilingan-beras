from app.services.jasa import pemilik_hasil


def test_bekatul_jasa_tetap_milik_pelanggan_sampai_dipindah():
    # Bahkan kesepakatan lama yang menyebut bekatul ditahan tidak boleh
    # memindahkannya otomatis. Perubahan ke pabrik dilakukan lewat aksi stok.
    assert pemilik_hasil(73, "sekam,bekatul", "bekatul") == 73
    assert pemilik_hasil(73, "sekam", "bekatul") == 73
    assert pemilik_hasil(None, "", "bekatul") is None


def test_hasil_lain_tetap_mengikuti_kesepakatan_jasa():
    assert pemilik_hasil(73, "sekam,broken", "broken") is None
    assert pemilik_hasil(73, "sekam", "broken") == 73
