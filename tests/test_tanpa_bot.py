"""Tak ada lagi pintu perintah lewat percakapan.

Keputusan pemilik: perintah lewat agen dihapus; agen hanya untuk Direksi dan
pengawas yang BERTANYA; operasional dan timbangan murni lewat aplikasinya.
Satu-satunya bot yang tersisa adalah Kantor AI, di repo & service-nya sendiri.

Yang dijaga di sini bukan selera, melainkan satu sifat: kemampuan menulis lewat
percakapan tidak dimatikan dengan bendera, melainkan DIBUANG. Bendera yang mati
cuma menunggu seseorang menyalakannya kembali — dan yang menyalakannya tidak
akan tahu bahwa dulu ia sengaja dimatikan.
"""
import inspect
import pathlib

AKAR = pathlib.Path(__file__).resolve().parents[1]


def test_tak_ada_paket_bot():
    assert not (AKAR / "app/bots").exists(), "paket bot kembali"
    for mati in ("app/ai/nlp_parser.py", "app/ai/router.py", "app/ai/fast_route.py",
                 "app/web/telegram_auth.py", "app/penggilingan/gudang1/nlp.py"):
        assert not (AKAR / mati).exists(), f"{mati} kembali"


def test_tak_ada_pustaka_telegram_terpasang():
    """Pustaka yang masih terpasang adalah pintu yang masih ada daunnya."""
    for berkas in (AKAR / "app").rglob("*.py"):
        assert "aiogram" not in berkas.read_text(), f"aiogram dipakai lagi di {berkas}"
    assert "aiogram" not in (AKAR / "requirements.txt").read_text()


def test_agen_tak_punya_kemampuan_tulis():
    """Bukan `allow_write=False`, melainkan tak ada parameternya sama sekali."""
    from app.ai import agent

    tanda = inspect.signature(agent.run_agent).parameters
    assert "allow_write" not in tanda, "bendera tulis kembali"
    sumber = inspect.getsource(agent)
    assert "usulkan_perintah" not in sumber
    # Dan balasannya tak lagi bisa membawa usulan perintah.
    assert not hasattr(agent.AgentReply(), "propose_command")


def test_satu_satunya_pintu_agen_adalah_internal_read_only():
    """Kantor AI memanggil agen produksi lewat /internal. Tak ada pintu lain,
    dan kanal agen tetap hanya membaca. Verifikasi tiket Timbangan memiliki
    endpoint tersendiri; ia tidak memberi agen hak tulis."""
    pemanggil = []
    for berkas in (AKAR / "app").rglob("*.py"):
        if berkas.name == "agent.py":
            continue
        if "run_agent" in berkas.read_text():
            pemanggil.append(str(berkas.relative_to(AKAR)))
    assert pemanggil == ["app/web/internal.py"], f"pemanggil agen: {pemanggil}"

    teks = (AKAR / "app/web/internal.py").read_text()
    assert "@router.post" in teks
    # Hanya tanya & hitung — tak ada yang menyentuh data.
    from app.web import internal
    agen = inspect.getsource(internal.produksi_tanya)
    assert "_pastikan_token(x_internal_token)" in agen
    assert "run_agent(" in agen and "allow_write" not in agen
    assert "commit(" not in agen and "execute(" not in agen
    post = {r.path for r in internal.router.routes if "POST" in r.methods}
    assert post == {"/internal/produksi/tanya", "/internal/pengiriman/tiket/{tid}/verifikasi"}


def test_aksi_hanya_lewat_sesi_pos_produksi():
    """Jalur initData Telegram dibubarkan: tanpa bot, tak ada yang bisa
    menghasilkan tanda tangan yang sah — dan pintu tanpa kunci maupun tamu
    lebih baik ditutup daripada dibiarkan terpasang."""
    from app.web import deps

    sumber = inspect.getsource(deps)
    assert "initData" not in sumber or "dibubarkan" in sumber
    assert "require_miniapp_user" not in sumber
    assert "akun_opsional" in sumber
