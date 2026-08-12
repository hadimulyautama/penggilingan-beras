"""Tes resolusi mailbox (alias 'pribadi', alamat lengkap, multi-akun) — regresi
bug 'agen salah pilih mailbox / menolak akses email pribadi'."""
import pytest


@pytest.fixture
def mg(monkeypatch):
    monkeypatch.setenv(
        "GMAIL_MAILBOXES",
        "finance@hadimulya.com,admin@hadimulya.com,wahidnurhani@hadimulya.com")
    monkeypatch.setenv("GMAIL_PRIBADI_EMAIL", "wahidnurhani20@gmail.com")
    monkeypatch.setenv("GMAIL_PRIBADI_REFRESH_TOKEN", "tok1")
    monkeypatch.setenv("GMAIL_PRIBADI2_EMAIL", "wahidnurhani@gmail.com")
    monkeypatch.setenv("GMAIL_PRIBADI2_REFRESH_TOKEN", "tok2")
    from app.kantor import mail_gmail
    return mail_gmail


def test_daftar_5_mailbox(mg):
    boxes = mg.daftar_mailbox()
    assert len(boxes) == 5
    assert "wahidnurhani20@gmail.com" in boxes
    assert "wahidnurhani@gmail.com" in boxes


def test_pribadi_map(mg):
    m = mg._pribadi_map()
    assert m["wahidnurhani20@gmail.com"] == "tok1"
    assert m["wahidnurhani@gmail.com"] == "tok2"


def test_alias_pribadi(mg):
    assert mg._mailbox_sah("pribadi") == "wahidnurhani20@gmail.com"
    assert mg._mailbox_sah("personal") == "wahidnurhani20@gmail.com"


def test_alamat_lengkap(mg):
    assert mg._mailbox_sah("finance@hadimulya.com") == "finance@hadimulya.com"
    assert mg._mailbox_sah("wahidnurhani@gmail.com") == "wahidnurhani@gmail.com"


def test_nama_pendek(mg):
    assert mg._mailbox_sah("finance") == "finance@hadimulya.com"
    # 'wahidnurhani' pendek → akun KANTOR (Workspace) lebih dulu (didokumentasikan)
    assert mg._mailbox_sah("wahidnurhani") == "wahidnurhani@hadimulya.com"


def test_mailbox_tak_sah(mg):
    with pytest.raises(ValueError):
        mg._mailbox_sah("orang@luar.com")


def test_tanpa_pribadi(monkeypatch):
    monkeypatch.setenv("GMAIL_MAILBOXES", "finance@hadimulya.com")
    monkeypatch.delenv("GMAIL_PRIBADI_EMAIL", raising=False)
    monkeypatch.delenv("GMAIL_PRIBADI_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GMAIL_PRIBADI2_EMAIL", raising=False)
    monkeypatch.delenv("GMAIL_PRIBADI2_REFRESH_TOKEN", raising=False)
    from app.kantor import mail_gmail
    assert mail_gmail._pribadi_map() == {}
    assert mail_gmail.daftar_mailbox() == ["finance@hadimulya.com"]
